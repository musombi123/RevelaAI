"""FastAPI ASGI entry point for the staged RevelaAI gateway migration.

The legacy Flask application remains mounted as a WSGI compatibility layer so
existing production routes keep their current behavior while they are migrated
to FastAPI routers. Do not remove the adapter until route-parity tests cover all
legacy endpoints and their authentication/error semantics.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

# Import the existing application only as the temporary compatibility gateway.
# Feature/business logic should move into framework-independent services before
# its Flask routes are replaced by FastAPI APIRouter modules.
from app import app as legacy_flask_app

logger = logging.getLogger("revelaai.asgi")

app = FastAPI(
    title="RevelaAI API",
    description=(
        "RevelaAI API gateway. The FastAPI migration is staged; routes not yet "
        "ported are served by the legacy WSGI compatibility adapter."
    ),
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/_fastapi/health", tags=["Operations"])
async def fastapi_gateway_health() -> dict[str, str]:
    """Health check for the ASGI process, not a claim that every AI provider is ready."""
    return {
        "status": "ok",
        "service": "revelaai",
        "runtime": "fastapi",
        "migration": "compatibility-phase",
    }


# Keep this mount last. Starlette evaluates routes in order, so FastAPI's docs
# and native routes above take precedence, and all remaining paths preserve
# their established Flask URL, method, response, and authentication behavior.
app.mount("/", WSGIMiddleware(legacy_flask_app), name="legacy-flask")
