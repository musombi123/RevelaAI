"""Native FastAPI health endpoint for Meta-Engineer."""
from __future__ import annotations

import importlib.util

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from meta_engineer.integrator import db

router = APIRouter(prefix="/api/meta-engineer", tags=["Meta-Engineer"])


@router.get("/health")
def meta_health():
    pytest_available = importlib.util.find_spec("pytest") is not None
    psutil_available = importlib.util.find_spec("psutil") is not None
    storage = "not_configured"
    if db is not None:
        try:
            db.command("ping")
            storage = "connected"
        except Exception:
            storage = "unreachable"

    checks = {
        "proposal_generator": "ready",
        "sandbox_pytest": "available" if pytest_available else "missing",
        "sandbox_memory_monitor": "available" if psutil_available else "missing",
        "audit_storage": storage,
    }
    ready = pytest_available and psutil_available and storage == "connected"
    return JSONResponse(
        {
            "status": "ok" if ready else "degraded",
            "module": "meta-engineer",
            "mode": "target-aware-proposal-builder",
            "checks": checks,
            "candidate_execution": False,
            "auto_deploy": False,
            "auto_delete": False,
        },
        status_code=200,
    )
