"""FastAPI ASGI entry point for the staged RevelaAI gateway migration.

Routes ported to FastAPI are registered natively. The root-mounted WSGI
compatibility adapter remains temporary for legacy routes not yet migrated;
remove it only after complete route and security-contract parity is proven.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
import uuid

import app as legacy_app_module
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.wsgi import WSGIMiddleware

from fastapi_routes.chat import router as chat_router
from fastapi_routes.core_mesh import router as core_mesh_router
from fastapi_routes.explain import router as explain_router
from fastapi_routes.hub import router as fastapi_hub_router
from fastapi_routes.living_brain import router as living_brain_router
from fastapi_routes.vision import router as vision_router
from fastapi_routes.system import router as system_router
from fastapi_routes.whatsapp import router as whatsapp_router

legacy_flask_app = legacy_app_module.app
logger = logging.getLogger("revelaai.asgi")

app = FastAPI(
    title="RevelaAI API",
    description=(
        "RevelaAI API gateway. The migration is staged; routes not yet ported "
        "are served by the temporary WSGI compatibility adapter."
    ),
    version="2.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Native FastAPI endpoints must enforce the same trusted-origin CORS policy as
# the legacy Flask gateway. Keep credentials enabled only for explicit origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(legacy_app_module.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "userId",
        "X-User-ID",
        "X-Session-ID",
        "X-Request-ID",
    ],
)


@app.middleware("http")
async def asgi_security_and_legacy_throttle(request: Request, call_next):
    """Maintain baseline response headers and SCI throttle for native routes."""
    path = request.url.path
    request_id = request.headers.get("X-Request-ID", "").strip()[:100] or uuid.uuid4().hex
    request.state.request_id = request_id

    # Count native ASGI requests in the same reversible SCI throttle as the
    # legacy application. The mounted WSGI app retains its own before_request
    # hook, so only ASGI-native requests pass through this middleware logic.
    now = time.time()
    request_times = legacy_app_module._SCI_REQUEST_TIMES
    rate_lock = legacy_app_module._SCI_RATE_LOCK
    throttle = legacy_app_module.SCI_THROTTLE

    with rate_lock:
        while request_times and now - request_times[0] > 1:
            request_times.popleft()
        request_times.append(now)
        measured_rps = len(request_times)

    if measured_rps > 200 and not throttle.get("enabled"):
        throttle.update({
            "enabled": True,
            "reason": "observed_rps_over_200",
            "since": datetime.now(timezone.utc).isoformat(),
        })

    if throttle.get("enabled"):
        since = throttle.get("since")
        try:
            started = datetime.fromisoformat(str(since)).timestamp()
        except Exception:
            started = now

        if now - started > 60:
            throttle.update({"enabled": False, "reason": None, "since": None})
        elif path not in {
            "/health",
            "/ready",
            "/api/sci/shield/status",
            "/api/sci/shield/dashboard",
            "/api/sci/disaster/simulate",
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
            request_id = (
                request.headers.get("X-Request-ID", "").strip()[:100]
                or uuid.uuid4().hex
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            return response

    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.get("/_fastapi/health", tags=["Operations"])
async def fastapi_gateway_health() -> dict[str, str]:
    """Check the ASGI process only; provider readiness is reported by /ready."""
    return {
        "status": "ok",
        "service": "revelaai",
        "runtime": "fastapi",
        "migration": "compatibility-phase",
    }


# Native FastAPI routes precede the catch-all WSGI mount so these endpoints no
# longer execute through Flask.
app.include_router(system_router)
app.include_router(core_mesh_router)
app.include_router(chat_router)
app.include_router(explain_router)
app.include_router(fastapi_hub_router)
app.include_router(living_brain_router)
app.include_router(vision_router)
app.include_router(whatsapp_router)

# Temporary bridge: remaining Flask endpoints retain their established contract.
app.mount("/", WSGIMiddleware(legacy_flask_app), name="legacy-flask")
