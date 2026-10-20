"""Native FastAPI router factory for cloud and loopback-local Automation Fabric."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from . import store
from .engine import AutomationError, create_plan, execute_plan
from .policy import (
    DEFAULT_CONSENT_TTL_SECONDS,
    MAX_CONSENT_TTL_SECONDS,
    normalize_scopes,
)
from .registry import tool_catalog

logger = logging.getLogger("revelaai.automation_fabric")

AuthResolver = Callable[[Request], tuple[str | None, Response | None]]
WorkspaceResolver = Callable[[str], str | Path]
DatabaseResolver = Callable[[], str | None]
MAX_REQUEST_BYTES = 1024 * 1024


def _error(code: str, status_code: int, message: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"status": "error", "code": code}
    if message:
        body["message"] = message
    return JSONResponse(body, status_code=status_code)


async def _principal(request: Request, auth_resolver: AuthResolver):
    try:
        principal, error = auth_resolver(request)
    except Exception:
        logger.exception("Automation Fabric authentication resolver failed")
        return None, _error("authentication_unavailable", 503)
    if error is not None:
        if isinstance(error, Response):
            return None, error
        return None, _error("authentication_unavailable", 503)
    if not isinstance(principal, str) or not principal:
        return None, _error("authentication_required", 401)
    return principal, None


async def _body(request: Request) -> tuple[dict[str, Any], Response | None]:
    """Read a bounded JSON object; malformed bodies retain the empty-object contract."""
    content_length = request.headers.get("content-length", "").strip()
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return {}, _error("request_too_large", 413, "Request body exceeds the 1 MiB limit.")
        except ValueError:
            return {}, _error("invalid_content_length", 400, "Content-Length must be an integer.")
    try:
        raw = await request.body()
    except Exception:
        return {}, None
    if len(raw) > MAX_REQUEST_BYTES:
        return {}, _error("request_too_large", 413, "Request body exceeds the 1 MiB limit.")
    if not raw:
        return {}, None
    try:
        import json
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}, None
    return (value if isinstance(value, dict) else {}), None


def create_automation_router(
    name: str,
    *,
    auth_resolver: AuthResolver,
    workspace_resolver: WorkspaceResolver,
    database_resolver: DatabaseResolver,
    local_mode: bool,
) -> APIRouter:
    """Create an isolated native APIRouter without Flask application/request globals."""
    router = APIRouter(tags=["Automation Fabric"])

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

    @router.get("/health", name=f"{name}_health")
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

    @router.get("/tools", name=f"{name}_tools")
    async def tools(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        consent = await run_in_threadpool(store.list_scopes, principal, db_path=_db())
        return {
            "status": "ok",
            "tools": tool_catalog(),
            "consent": consent,
            "runtime": "local-device" if local_mode else "hosted-workspace",
            "note": "A hosted workspace is isolated from the user's personal device. Device-only tools require the separately installed local agent.",
        }

    @router.get("/consent", name=f"{name}_get_consent")
    async def get_consent(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        scopes = await run_in_threadpool(store.list_scopes, principal, db_path=_db())
        return {"status": "ok", "scopes": scopes}

    @router.post("/consent", name=f"{name}_grant_consent")
    async def grant_consent(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        body, body_error = await _body(request)
        if body_error:
            return body_error
        if body.get("accepted") is not True:
            return _error(
                "explicit_consent_required", 400,
                "Set accepted=true only after reviewing the requested permission scopes.",
            )
        try:
            scopes = normalize_scopes(body.get("scopes"))
            ttl = body.get("ttl_seconds", DEFAULT_CONSENT_TTL_SECONDS)
            if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 60 or ttl > MAX_CONSENT_TTL_SECONDS:
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

    @router.post("/consent/revoke", name=f"{name}_revoke_consent")
    async def revoke_consent(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        body, body_error = await _body(request)
        if body_error:
            return body_error
        try:
            scopes = normalize_scopes(body.get("scopes"))
            revoked = await run_in_threadpool(store.revoke_scopes, principal, scopes, db_path=_db())
            current = await run_in_threadpool(store.list_scopes, principal, db_path=_db())
            return {"status": "ok", "revoked": revoked, "scopes": current}
        except ValueError as exc:
            return _error("invalid_consent", 400, str(exc))
        except Exception:
            logger.exception("Automation Fabric could not revoke consent")
            return _error("consent_storage_unavailable", 503)

    @router.post("/plan", name=f"{name}_plan")
    async def plan(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        body, body_error = await _body(request)
        if body_error:
            return body_error
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

    @router.get("/plans/{plan_id}", name=f"{name}_plan_status")
    async def plan_status(plan_id: str, request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        record = await run_in_threadpool(store.get_plan, principal, plan_id, db_path=_db())
        if record is None:
            return _error("plan_not_found", 404)
        return {"status": "ok", "record": record}

    @router.post("/execute", name=f"{name}_execute")
    async def execute(request: Request):
        principal, error = await _principal(request, auth_resolver)
        if error:
            return error
        body, body_error = await _body(request)
        if body_error:
            return body_error
        plan_id = body.get("plan_id")
        plan_hash = body.get("plan_hash")
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

    @router.get("/audit", name=f"{name}_audit")
    async def audit(request: Request, limit: str = "50"):
        principal, error = await _principal(request, auth_resolver)
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


# The legacy symbol name is retained for imports only; it now returns an APIRouter.
create_automation_blueprint = create_automation_router

__all__ = ["create_automation_router", "create_automation_blueprint"]
