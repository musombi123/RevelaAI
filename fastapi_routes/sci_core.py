"""Native FastAPI port of the administrator-only Sci-Core dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from fastapi_routes.admin_auth import require_platform_admin
from revelai.sci_core.storage import collection

router = APIRouter(prefix="/api/sci", tags=["Sci-Core"])


def _dashboard(authorization: str):
    _actor, error = require_platform_admin(authorization)
    if error:
        return error
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return {
            "threats_last_24h": collection("threats").count_documents(
                {"timestamp": {"$gte": since.isoformat()}}
            ),
            "shields_active": 1,
            "disasters_handled": collection("disasters").count_documents({}),
            "research_count": collection("research").count_documents({}),
            "defensive_only": True,
        }
    except Exception:
        return {
            "status": "degraded",
            "error": "Sci-Core dashboard unavailable",
        }


@router.get("/shield/dashboard")
async def dashboard(request: Request):
    result = await run_in_threadpool(
        _dashboard, request.headers.get("Authorization", "")
    )
    if isinstance(result, dict) and result.get("status") == "degraded":
        from fastapi.responses import JSONResponse
        return JSONResponse(result, status_code=503)
    return result
