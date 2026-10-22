"""Native FastAPI implementation of the hosted Automation Fabric API."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from automation_fabric import store
from automation_fabric.engine import AutomationError, create_plan, execute_plan
from automation_fabric.policy import (
    DEFAULT_CONSENT_TTL_SECONDS,
    MAX_CONSENT_TTL_SECONDS,
    normalize_scopes,
)
from automation_fabric.registry import tool_catalog
from fastapi_routes.auth import authenticate_identity
from services.revenue_entitlements import check_entitlement

router = APIRouter(prefix="/api/automation-fabric", tags=["Automation Fabric"])
logger = logging.getLogger("revelaai.fastapi.automation_fabric")
MAX_BODY_BYTES = 1024 * 1024
LOCAL_MODE = False


def _database_path() -> str | None:
    return os.getenv(
        "REVELAAI_AUTOMATION_DB",
        "/tmp/revelaai-automation-fabric.sqlite3",
    )


def _workspace_for_user(principal: str) -> Path:
    root = Path(
        os.getenv(
            "REVELAAI_AUTOMATION_SERVER_WORKSPACE",
            "/tmp/revelaai-automation-workspaces",
        )
    ).expanduser()
    key = hashlib.sha256(principal.encode("utf-8")).hexdigest()[:24]
    workspace = root / key
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        workspace.chmod(0o700)
    except OSError:
        pass
    return workspace.resolve()


def _principal(headers: Mapping[str, str]):
    identity, user_id, error = authenticate_identity(
        headers.get("authorization", ""),
        headers,
        {},
    )
    if error:
        return None, error
    return "user:" + str(user_id), None


def _automation_entitlement(headers: Mapping[str, str]):
    """Gate stateful hosted automation behind the caller's Smart AI entitlement."""
    _payload, error = check_entitlement(
        headers.get("authorization", ""),
        hub="smart_ai",
        feature="automation",
    )
    return error


def _json_error(code: str, status_code: int, message: str | None = None):
    payload: dict[str, Any] = {"status": "error", "code": code}
    if message:
        payload["message"] = message
    return JSONResponse(payload, status_code=status_code)


async def _payload(request: Request):
    try:
        raw = await request.body()
    except Exception:
        return {}, None
    if len(raw) > MAX_BODY_BYTES:
        return None, _json_error(
            "request_too_large",
            413,
            "Request body exceeds the 1 MiB limit.",
        )
    if not raw:
        return {}, None
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return {}, None
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}, None
    return (body if isinstance(body, dict) else {}), None


def _health():
    return {
        "status": "ok",
        "module": "revelaai-automation-fabric",
        "version": "1.0.0",
        "mode": "hosted-workspace",
        "execution": "deterministic",
        "models_required": False,
        "shell_execution": False,
        "generated_code_autorun": False,
        "hardware_actuation": False,
    }


def _tools(headers: Mapping[str, str]):
    principal, error = _principal(headers)
    if error:
        return error
    return {
        "status": "ok",
        "tools": tool_catalog(),
        "consent": store.list_scopes(principal, db_path=_database_path()),
        "runtime": "hosted-workspace",
        "note": "A hosted workspace is isolated from the user's personal device. Device-only tools require the separately installed local agent.",
    }


def _get_consent(headers: Mapping[str, str]):
    principal, error = _principal(headers)
    if error:
        return error
    return {"status": "ok", "scopes": store.list_scopes(principal, db_path=_database_path())}


def _grant_consent(headers: Mapping[str, str], body: dict[str, Any]):
    principal, error = _principal(headers)
    if error:
        return error
    if body.get("accepted") is not True:
        return _json_error(
            "explicit_consent_required",
            400,
            "Set accepted=true only after reviewing the requested permission scopes.",
        )
    try:
        scopes = normalize_scopes(body.get("scopes"))
        ttl = body.get("ttl_seconds", DEFAULT_CONSENT_TTL_SECONDS)
        if (
            isinstance(ttl, bool)
            or not isinstance(ttl, int)
            or ttl < 60
            or ttl > MAX_CONSENT_TTL_SECONDS
        ):
            raise ValueError("ttl_seconds must be an integer from 60 to 86400")
        reason = body.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 240:
            raise ValueError("reason must be a string of at most 240 characters")
        grants = store.grant_scopes(
            principal, scopes, reason=reason.strip(),
            ttl_seconds=ttl, db_path=_database_path(),
        )
        return JSONResponse(
            {
                "status": "ok",
                "granted": scopes,
                "scopes": grants,
                "expires_in_seconds": ttl,
            },
            status_code=201,
        )
    except ValueError as exc:
        return _json_error("invalid_consent", 400, str(exc))
    except Exception:
        logger.exception("Automation Fabric could not persist consent")
        return _json_error("consent_storage_unavailable", 503)


def _revoke_consent(headers: Mapping[str, str], body: dict[str, Any]):
    principal, error = _principal(headers)
    if error:
        return error
    try:
        scopes = normalize_scopes(body.get("scopes"))
        revoked = store.revoke_scopes(principal, scopes, db_path=_database_path())
        return {
            "status": "ok",
            "revoked": revoked,
            "scopes": store.list_scopes(principal, db_path=_database_path()),
        }
    except ValueError as exc:
        return _json_error("invalid_consent", 400, str(exc))
    except Exception:
        logger.exception("Automation Fabric could not revoke consent")
        return _json_error("consent_storage_unavailable", 503)


def _plan(headers: Mapping[str, str], body: dict[str, Any]):
    principal, error = _principal(headers)
    if error:
        return error
    entitlement_error = _automation_entitlement(headers)
    if entitlement_error is not None:
        return entitlement_error
    try:
        result = create_plan(
            principal,
            body.get("steps"),
            _workspace_for_user(principal),
            db_path=_database_path(),
            local_mode=LOCAL_MODE,
        )
        return JSONResponse({"status": "planned", "plan": result}, status_code=201)
    except AutomationError as exc:
        return _json_error(exc.code, exc.status_code, exc.message)
    except ValueError as exc:
        return _json_error("invalid_plan", 400, str(exc))
    except Exception:
        logger.exception("Automation Fabric failed to create a plan")
        return _json_error("planning_unavailable", 503)


def _plan_status(headers: Mapping[str, str], plan_id: str):
    principal, error = _principal(headers)
    if error:
        return error
    record = store.get_plan(principal, plan_id, db_path=_database_path())
    if record is None:
        return _json_error("plan_not_found", 404)
    return {"status": "ok", "record": record}


def _execute(headers: Mapping[str, str], body: dict[str, Any]):
    principal, error = _principal(headers)
    if error:
        return error
    entitlement_error = _automation_entitlement(headers)
    if entitlement_error is not None:
        return entitlement_error
    plan_id = body.get("plan_id")
    plan_hash = body.get("plan_hash")
    if not isinstance(plan_id, str) or not isinstance(plan_hash, str):
        return _json_error(
            "invalid_execution_request",
            400,
            "plan_id and plan_hash are required",
        )
    try:
        result = execute_plan(
            principal,
            plan_id,
            plan_hash,
            approved=body.get("approved") is True,
            workspace=_workspace_for_user(principal),
            db_path=_database_path(),
            local_mode=LOCAL_MODE,
        )
        return {"status": "ok", "execution": result}
    except AutomationError as exc:
        return _json_error(exc.code, exc.status_code, exc.message)
    except Exception:
        logger.exception("Automation Fabric execution stopped unexpectedly")
        return _json_error(
            "execution_unavailable",
            503,
            "Execution stopped safely. Check the audit log and plan status.",
        )


def _audit(headers: Mapping[str, str], limit: str):
    principal, error = _principal(headers)
    if error:
        return error
    try:
        if not str(limit).isdigit():
            raise ValueError("limit must be an integer")
        entries = store.read_audit(principal, int(limit), db_path=_database_path())
        return {"status": "ok", "entries": entries, "hash_chained": True}
    except ValueError as exc:
        return _json_error("invalid_limit", 400, str(exc))
    except Exception:
        logger.exception("Automation Fabric audit log unavailable")
        return _json_error("audit_unavailable", 503)


@router.get("/health")
async def health():
    return _health()


@router.get("/tools")
async def tools_api(request: Request):
    return await run_in_threadpool(_tools, dict(request.headers))


@router.get("/consent")
async def get_consent(request: Request):
    return await run_in_threadpool(_get_consent, dict(request.headers))


@router.post("/consent")
async def grant_consent(request: Request):
    body, body_error = await _payload(request)
    if body_error:
        return body_error
    return await run_in_threadpool(_grant_consent, dict(request.headers), body)


@router.post("/consent/revoke")
async def revoke_consent(request: Request):
    body, body_error = await _payload(request)
    if body_error:
        return body_error
    return await run_in_threadpool(_revoke_consent, dict(request.headers), body)


@router.post("/plan")
async def plan(request: Request):
    body, body_error = await _payload(request)
    if body_error:
        return body_error
    return await run_in_threadpool(_plan, dict(request.headers), body)


@router.get("/plans/{plan_id}")
async def plan_status(plan_id: str, request: Request):
    return await run_in_threadpool(_plan_status, dict(request.headers), plan_id)


@router.post("/execute")
async def execute(request: Request):
    body, body_error = await _payload(request)
    if body_error:
        return body_error
    return await run_in_threadpool(_execute, dict(request.headers), body)


@router.get("/audit")
async def audit(request: Request, limit: str = "50"):
    return await run_in_threadpool(_audit, dict(request.headers), limit)
