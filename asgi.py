"""FastAPI ASGI entry point for the staged RevelaAI gateway migration.

Routes already ported to FastAPI are registered before the WSGI compatibility
mount. The mount is temporary and must be removed only after route parity tests
cover the remaining Flask endpoints and their security/error semantics.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
import uuid

import app as legacy_app_module
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.wsgi import WSGIMiddleware

from fastapi_routes.hub import router as fastapi_hub_router

legacy_flask_app = legacy_app_module.app
logger = logging.getLogger("revelaai.asgi")

app = FastAPI(
    title="RevelaAI API",
    description=(
        "RevelaAI API gateway. Migration is staged; endpoints not yet ported "
        "are served by the legacy WSGI compatibility adapter."
    ),
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.middleware("http")
async def asgi_security_and_legacy_throttle(request: Request, call_next):
    """Keep baseline headers and the existing reversible SCI throttle for migrated routes."""
    path = request.url.path

    # Flask's before_request guard still covers requests forwarded through the
    # compatibility adapter. Apply the same guard here only to FastAPI-native
    # Hub routes, otherwise bridge requests would be counted twice.
    if path.startswith("/api/revelaai/hubs"):
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
            else:
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
    response.headers.setdefault(
        "X-Request-ID",
        request.headers.get("X-Request-ID", "").strip()[:100] or uuid.uuid4().hex,
    )
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


# Hub endpoints now use FastAPI directly. All other paths continue through the
# temporary bridge until their APIRouter ports and parity tests are complete.
app.include_router(fastapi_hub_router)
app.mount("/", WSGIMiddleware(legacy_flask_app), name="legacy-flask")
