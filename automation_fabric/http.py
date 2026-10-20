"""Framework-neutral FastAPI router factory for Automation Fabric runtimes."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import store
from .engine import AutomationError, create_plan, execute_plan
from .policy import (
    DEFAULT_CONSENT_TTL_SECONDS,
    MAX_CONSENT_TTL_SECONDS,
    normalize_scopes,
)
from .registry import tool_catalog

logger = logging.getLogger("revelaai.automation_fabric")
MAX_BODY_BYTES = 1024 * 1024
AuthResolver = Callable[[Request], tuple[str | None, JSONResponse | None]]
WorkspaceResolver = Callable[[str], str | Path]
DatabaseResolver = Callable[[], str | None]


def _error(code: str, status: int, message: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"status": "error", "code": code}
    if message:
        payload["message"] = message
    return JSONResponse(payload, status_code=status)


def create_automation_router(
    name: str = "automation_fabric",
    *,
    auth_resolver: AuthResolver,
    workspace_resolver: WorkspaceResolver,
    database_resolver: DatabaseResolver,
    local_mode: bool = False,
    prefix: str = "",
) -> APIRouter:
    """Create an ASGI router with explicit auth, workspace, and database boundaries."""
    router = APIRouter(prefix=prefix, tags=["Automation Fabric"])

    def _principal(request: Request):
        try:
            principal, error = auth_resolver(request)
        except Exception:
            logger.exception("Automation Fabric authentication resolver failed")
            return None, _error("authentication_unavailable", 503)
        if error is not None:
            return None, error
        if not isinstance(principal, str) or not principal:
            return None, _error("authentication_required", 401)
        return principal, None

    def _db() -> str | None:
        return database_resolver()

    def _workspace(principal: str) -> Path:
        root = Path(workspace_resolver(principal)).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            root.chmod(0o700)
        except OSError:
            pass
        return root

    async def _payload(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return None, _error("request_too_large", 413, "Request body exceeds the 1 MiB limit.")
        if not raw:
            return {}, None
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return None, _error("json_required", 415, "Request body must use application/json.")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None, _error("invalid_json", 400, "Request body must contain valid JSON.")
        if not isinstance(body, dict):
            return None, _error("invalid_json", 400, "Request body must be one JSON object.")
        return body, None

    @router.get("/health")
    async def health():
        return {
            "status": "ok",
            "module": "revelaai-automation-fabric",
            "version": "1.0.0",
            "mode": "local-device" if local_mode else "hosted-workspace",
            "execution": "deterministic",
            "models_required": False,
            "shell_execution": False,
            "generated_code_autorun": False,
            "hardware_actuation": False,
        }

    @router.get("/tools")
    async def list_tools(request: Request):
        principal, error = _principal(request)
        if error:
            return error
        return await run_in_threadpool(
            lambda: {
                "status": "ok",
                "tools": tool_catalog(),
                "consent": store.list_scopes(principal, db_path=_db()),
                "runtime": "local-device" if local_mode else "hosted-workspace",
                "note": (
                    "This local agent runs on the installed device."
                    if local_mode else
                    "A hosted workspace is isolated from the user's personal device; "
                    "device-only tools require the separately installed local agent."
                ),
            }
        )

    @router.get("/consent")
    async def get_consent(request: Request):
        principal, error = _principal(request)
        if error:
            return error
        return await run_in_threadpool(
            lambda: {"status": "ok", "scopes": store.list_scopes(principal, db_path=_db())}
        )

    @router.post("/consent")
    async def grant_consent(request: Request):
        body, error = await _payload(request)
        if error:
            return error
        principal, error = _principal(request)
        if error:
            return error
        if body.get("accepted") is not True:
            return _error(
                "explicit_consent_required", 400,
                "Set accepted=true only after reviewing the requested permission scopes.",
            )
        try:
            scopes = normalize_scopes(body.get("scopes"))
            ttl = body.get("ttl_seconds", DEFAULT_CONSENT_TTL_SECONDS)
            if isinstance(ttl, bool) or not isinstance(ttl, int) or not 60 <= ttl <= MAX_CONSENT_TTL_SECONDS:
                raise ValueError("ttl_seconds must be an integer from 60 to 86400")
            reason = body.get("reason", "")
            if not isinstance(reason, str) or len(reason) > 240:
                raise ValueError("reason must be a string of at most 240 characters")
            grants = await run_in_threadpool(
                store.grant_scopes, principal, scopes,
                reason=reason.strip(), ttl_seconds=ttl, db_path=_db(),
            )
            return JSONResponse(
                {"status": "ok", "granted": scopes, "scopes": grants, "expires_in_seconds": ttl},
                status_code=201,
            )
        except ValueError as exc:
            return _error("invalid_consent", 400, str(exc))
        except Exception:
            logger.exception("Automation Fabric could not persist consent")
            return _error("consent_storage_unavailable", 503)

    @router.post("/consent/revoke")
    async def revoke_consent(request: Request):
        body, error = await _payload(request)
        if error:
            return error
        principal, error = _principal(request)
        if error:
            return error
        try:
            scopes = normalize_scopes(body.get("scopes"))
            revoked = await run_in_threadpool(
                store.revoke_scopes, principal, scopes, db_path=_db()
            )
            remaining = await run_in_threadpool(store.list_scopes, principal, db_path=_db())
            return {"status": "ok", "revoked": revoked, "scopes": remaining}
        except ValueError as exc:
            return _error("invalid_consent", 400, str(exc))
        except Exception:
            logger.exception("Automation Fabric could not revoke consent")
            return _error("consent_storage_unavailable", 503)

    @router.post("/plan")
    async def plan(request: Request):
        body, error = await _payload(request)
        if error:
            return error
        principal, error = _principal(request)
        if error:
            return error
        try:
            result = await run_in_threadpool(
                create_plan, principal, body.get("steps"), _workspace(principal),
                db_path=_db(), local_mode=local_mode,
            )
            return JSONResponse({"status": "planned", "plan": result}, status_code=201)
        except AutomationError as exc:
            return _error(exc.code, exc.status_code, exc.message)
        except ValueError as exc:
            return _error("invalid_plan", 400, str(exc))
        except Exception:
            logger.exception("Automation Fabric failed to create a plan")
            return _error("planning_unavailable", 503)

    @router.get("/plans/{plan_id}")
    async def plan_status(plan_id: str, request: Request):
        principal, error = _principal(request)
        if error:
            return error
        record = await run_in_threadpool(store.get_plan, principal, plan_id, db_path=_db())
        if record is None:
            return _error("plan_not_found", 404)
        return {"status": "ok", "record": record}

    @router.post("/execute")
    async def execute(request: Request):
        body, error = await _payload(request)
        if error:
            return error
        principal, error = _principal(request)
        if error:
            return error
        plan_id, plan_hash = body.get("plan_id"), body.get("plan_hash")
        if not isinstance(plan_id, str) or not isinstance(plan_hash, str):
            return _error("invalid_execution_request", 400, "plan_id and plan_hash are required")
        try:
            result = await run_in_threadpool(
                execute_plan, principal, plan_id, plan_hash,
                approved=body.get("approved") is True,
                workspace=_workspace(principal), db_path=_db(), local_mode=local_mode,
            )
            return {"status": "ok", "execution": result}
        except AutomationError as exc:
            return _error(exc.code, exc.status_code, exc.message)
        except Exception:
            logger.exception("Automation Fabric execution stopped unexpectedly")
            return _error(
                "execution_unavailable", 503,
                "Execution stopped safely. Check the audit log and plan status.",
            )

    @router.get("/audit")
    async def audit(request: Request, limit: str = "50"):
        principal, error = _principal(request)
        if error:
            return error
        try:
            if not str(limit).isdigit():
                raise ValueError("limit must be an integer")
            entries = await run_in_threadpool(store.read_audit, principal, int(limit), db_path=_db())
            return {"status": "ok", "entries": entries, "hash_chained": True}
        except ValueError as exc:
            return _error("invalid_limit", 400, str(exc))
        except Exception:
            logger.exception("Automation Fabric audit log unavailable")
            return _error("audit_unavailable", 503)

    return router


# The old factory name is deliberately retained as a Python-level alias only.
# It now returns a FastAPI APIRouter and never constructs Flask/WSGI objects.
create_automation_blueprint = create_automation_router
