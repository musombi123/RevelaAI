"""Native FastAPI application and ASGI entry point for RevelaAI.

All active HTTP routes are implemented by FastAPI routers. This module does not
mount a WSGI application or import Flask. Keep sector-specific business logic
inside its existing services; expose HTTP handlers through fastapi_routes/.
"""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from fastapi_routes.agi import router as agi_router
from fastapi_routes.ai import router as ai_router
from fastapi_routes.automation_fabric import router as automation_fabric_router
from fastapi_routes.chat import router as chat_router
from fastapi_routes.core_mesh import router as core_mesh_router
from fastapi_routes.explain import router as explain_router
from fastapi_routes.evolve_migrate import router as evolve_migrate_router
from fastapi_routes.uncopyable import router as uncopyable_router
from fastapi_routes.hub import router as fastapi_hub_router
from fastapi_routes.living_brain import router as living_brain_router
from fastapi_routes.memory import router as memory_router
from fastapi_routes.meta_engineer import router as meta_engineer_router
from fastapi_routes.research import router as research_router
from fastapi_routes.security_academy import router as security_academy_router
from fastapi_routes.sci_core import router as sci_core_router
from fastapi_routes.stream import router as stream_router
from fastapi_routes.system import router as system_router
from fastapi_routes.usect_zero import router as usect_zero_router
from fastapi_routes.usect_contracts import router as usect_contracts_router
from fastapi_routes.platform_hubs import router as platform_hubs_router
from fastapi_routes.users import router as users_router
from fastapi_routes.vision import router as vision_router
from fastapi_routes.voice import router as voice_router
from fastapi_routes.whatsapp import router as whatsapp_router

from services.http_config import CORS_ORIGINS
from services.runtime_config import APP_NAME, ENVIRONMENT, MAX_CONTENT_LENGTH, REVELAAI_BUILD_ID
from services.security_state import SCI_RATE_LOCK, SCI_REQUEST_TIMES, SCI_THROTTLE

logger = logging.getLogger("revelaai.asgi")

app = FastAPI(
    title="RevelaAI API",
    description=(
        "RevelaAI native FastAPI gateway. All active HTTP endpoints run through "
        "the ASGI application; no Flask/WSGI compatibility mount is used."
    ),
    version="2.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Revela-License",
        "userId",
        "X-User-ID",
        "X-Session-ID",
        "X-Request-ID",
    ],
)


@app.middleware("http")
async def asgi_security_and_throttle(request: Request, call_next):
    """Apply request IDs, size guards, baseline headers and the reversible SCI cooldown."""
    path = request.url.path
    request_id = request.headers.get("X-Request-ID", "").strip()[:100] or uuid.uuid4().hex
    request.state.request_id = request_id

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            request_size = int(content_length)
            if request_size < 0:
                raise ValueError("negative content length")
        except ValueError:
            response = JSONResponse(
                {
                    "status": "error",
                    "error": {
                        "code": "INVALID_CONTENT_LENGTH",
                        "message": "Invalid Content-Length header.",
                    },
                    "request_id": request_id,
                },
                status_code=400,
            )
            return _secure_response(response, request_id)
        if request_size > MAX_CONTENT_LENGTH:
            response = JSONResponse(
                {
                    "status": "error",
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "The request exceeds the allowed size.",
                    },
                    "request_id": request_id,
                },
                status_code=413,
            )
            return _secure_response(response, request_id)

    now = time.time()
    with SCI_RATE_LOCK:
        while SCI_REQUEST_TIMES and now - SCI_REQUEST_TIMES[0] > 1:
            SCI_REQUEST_TIMES.popleft()
        SCI_REQUEST_TIMES.append(now)
        measured_rps = len(SCI_REQUEST_TIMES)

    if measured_rps > 200 and not SCI_THROTTLE.get("enabled"):
        SCI_THROTTLE.update({
            "enabled": True,
            "reason": "observed_rps_over_200",
            "since": datetime.now(timezone.utc).isoformat(),
        })

    if SCI_THROTTLE.get("enabled"):
        since = SCI_THROTTLE.get("since")
        try:
            started = datetime.fromisoformat(str(since)).timestamp()
        except (TypeError, ValueError):
            started = now

        if now - started > 60:
            SCI_THROTTLE.update({"enabled": False, "reason": None, "since": None})
        elif path not in {
            "/health",
            "/ready",
            "/api/sci/shield/status",
            "/api/sci/shield/dashboard",
            "/api/sci/disaster/simulate",
            "/_fastapi/health",
        }:
            response = JSONResponse(
                {
                    "status": "error",
                    "code": "SCI_SHIELD_COOLDOWN",
                    "message": "RevelaAI Shield Active - Cooling Down",
                    "retry_after_seconds": max(1, int(60 - (now - started))),
                },
                status_code=429,
            )
            return _secure_response(response, request_id)

    response = await call_next(request)
    # Normalize JSON error responses from route handlers so every failed request
    # has a stable envelope and correlation ID, not only an X-Request-ID header.
    if response.status_code >= 400 and "application/json" in response.headers.get("content-type", ""):
        raw_body = b""
        status_code = response.status_code
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        try:
            raw_body = b"".join([chunk async for chunk in response.body_iterator])
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if isinstance(payload, dict):
                existing_error = payload.get("error")
                if not isinstance(existing_error, dict):
                    code = payload.get("code") or payload.get("error_code") or f"HTTP_{status_code}"
                    message = payload.get("message") or payload.get("detail") or "Request could not be completed."
                    payload["error"] = {"code": str(code), "message": str(message)}
                payload.setdefault("status", "error")
                payload.setdefault("request_id", request_id)
                response = JSONResponse(payload, status_code=status_code, headers=headers)
            else:
                response = Response(content=raw_body, status_code=status_code, headers=headers)
        except (ValueError, UnicodeDecodeError, TypeError):
            logger.warning("Could not normalize JSON error response | request_id=%s", request_id)
            response = Response(content=raw_body, status_code=status_code, headers=headers)
    return _secure_response(response, request_id)


def _secure_response(response, request_id: str):
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", None)
    if exc.status_code == 404:
        body = {
            "status": "error",
            "error": {"code": "NOT_FOUND", "message": "Resource not found."},
            "request_id": request_id,
        }
    elif exc.status_code == 405:
        body = {
            "status": "error",
            "error": {"code": "METHOD_NOT_ALLOWED", "message": "HTTP method is not allowed."},
            "request_id": request_id,
        }
    else:
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        body = {
            "status": "error",
            "error": {"code": f"HTTP_{exc.status_code}", "message": detail},
            "request_id": request_id,
        }
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


@app.on_event("startup")
def validate_gemini_models_on_startup() -> None:
    """Log provider model availability without making optional upstream outages fatal."""
    try:
        from ai.ai_client import validate_gemini_models
        validate_gemini_models()
    except Exception as exc:
        logger.warning("Gemini model validation skipped: %s", type(exc).__name__)


@app.on_event("startup")
def enforce_uncopyable_startup() -> None:
    """Enforce owner recipe trust when the deployment explicitly enables strict mode."""
    if __import__("os").getenv("REVELA_UNCOPYABLE_ENFORCE", "").strip().lower() not in {"1", "true", "yes"}:
        return
    from core_uncopyable.hardware_bind import hardware_fingerprint
    from core_uncopyable.recipe_lock import RecipeLockError, verify_recipe
    from core_billing.licensing import LicenseError, load_public_key

    try:
        verify_recipe(strict_path=True)
        # Validate strict-mode secrets without logging or returning their values.
        env = __import__("os").environ
        if not (env.get("REVELA_LICENSE_PUBLIC_KEY", "").strip() or env.get("REVELA_LICENSE_PUBLIC_KEY_PATH", "").strip()):
            raise RuntimeError("REVELA_LICENSE_PUBLIC_KEY or REVELA_LICENSE_PUBLIC_KEY_PATH is required when REVELA_UNCOPYABLE_ENFORCE=true.")
        load_public_key()
        master_key = env.get("REVELA_MASTER_KEY_BASE64", "").strip()
        if not master_key:
            raise RuntimeError("REVELA_MASTER_KEY_BASE64 is required when REVELA_UNCOPYABLE_ENFORCE=true.")
        try:
            decoded_master_key = base64.b64decode(master_key, validate=True)
        except Exception as key_exc:
            raise RuntimeError("REVELA_MASTER_KEY_BASE64 must contain valid base64.") from key_exc
        if len(decoded_master_key) < 32:
            raise RuntimeError("REVELA_MASTER_KEY_BASE64 must decode to at least 32 bytes.")
        jwt_secret = env.get("JWT_SECRET", "")
        if len(jwt_secret.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET must be configured with at least 32 UTF-8 bytes when REVELA_UNCOPYABLE_ENFORCE=true.")
        hardware_fingerprint()
    except (RecipeLockError, LicenseError, RuntimeError) as exc:
        logger.critical("USECT-UNCOPYABLE startup gate rejected runtime: %s", type(exc).__name__)
        raise RuntimeError("Need RevelaCode Brain - Contact founder") from exc


@app.get("/_fastapi/health", tags=["Operations"])
async def fastapi_gateway_health() -> dict[str, str]:
    """Check the ASGI process only; provider readiness is reported by /ready."""
    return {
        "status": "ok",
        "service": "revelaai",
        "runtime": "fastapi",
        "migration": "native-fastapi-only",
        "application": APP_NAME,
        "environment": ENVIRONMENT,
        "build_id": REVELAAI_BUILD_ID,
    }


# All active endpoint families are mounted natively. Keep sector/business logic in
# the existing service modules; do not mount Flask blueprints or WSGI applications.
app.include_router(system_router)
app.include_router(ai_router)
app.include_router(stream_router)
app.include_router(agi_router)
app.include_router(sci_core_router)
app.include_router(usect_zero_router)
app.include_router(usect_contracts_router)
app.include_router(platform_hubs_router)
app.include_router(automation_fabric_router)
app.include_router(core_mesh_router)
app.include_router(memory_router)
app.include_router(meta_engineer_router)
app.include_router(chat_router)
app.include_router(research_router)
app.include_router(security_academy_router)
app.include_router(users_router)
app.include_router(explain_router)
app.include_router(evolve_migrate_router)
app.include_router(uncopyable_router)
app.include_router(fastapi_hub_router)
app.include_router(living_brain_router)
app.include_router(vision_router)
app.include_router(whatsapp_router)
app.include_router(voice_router)
