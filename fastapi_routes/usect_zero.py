"""Native FastAPI health gateway for the private USECT-ZERO core."""
from __future__ import annotations

import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from services.usect_zero_client import (
    USECTZeroAdminTokenMissing,
    USECTZeroConfigurationError,
    USECTZeroDisabled,
    USECTZeroError,
    USECTZeroPayloadTooLarge,
    USECTZeroResponseTooLarge,
    USECTZeroUnavailable,
    is_enabled,
    request_core,
)

router = APIRouter(prefix="/api/usect-zero", tags=["USECT-ZERO"])
logger = logging.getLogger("revelaai.fastapi.usect_zero")


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"status": "error", "code": code, "message": message},
        status_code=status_code,
    )


def _health():
    """Expose safe health fields only; never leak the core's repository path."""
    if not is_enabled():
        return JSONResponse(
            {
                "status": "disabled",
                "module": "usect-zero",
                "enabled": False,
                "model_free": True,
            },
            status_code=503,
        )

    try:
        reply = request_core("GET", "/v1/health")
    except USECTZeroDisabled:
        return _error(
            "usect_zero_disabled",
            "USECT-ZERO is not enabled for this backend deployment.",
            503,
        )
    except USECTZeroAdminTokenMissing:
        return _error(
            "usect_zero_admin_not_configured",
            "Administrative integration is not configured on this backend.",
            503,
        )
    except USECTZeroPayloadTooLarge:
        return _error("payload_too_large", "Request body exceeds the 1 MiB limit.", 413)
    except USECTZeroResponseTooLarge:
        return _error(
            "usect_zero_response_too_large",
            "The core response exceeded the adapter limit.",
            502,
        )
    except USECTZeroConfigurationError:
        logger.error("USECT-ZERO has invalid server-side configuration.")
        return _error(
            "usect_zero_misconfigured",
            "USECT-ZERO is not configured correctly.",
            503,
        )
    except USECTZeroUnavailable:
        logger.warning("USECT-ZERO health check failed or returned invalid data.")
        return _error(
            "usect_zero_unavailable",
            "The USECT-ZERO core service is unavailable.",
            503,
        )
    except USECTZeroError:
        logger.warning("USECT-ZERO health request was blocked by the integration boundary.")
        return _error(
            "usect_zero_request_blocked",
            "The USECT-ZERO request could not be processed.",
            503,
        )

    if reply.status_code >= 400:
        return JSONResponse(reply.payload, status_code=reply.status_code)

    core = reply.payload
    safe = {
        "status": str(core.get("status") or "unknown"),
        "module": "usect-zero",
        "enabled": True,
        "model_free": bool(core.get("model_free", True)),
        "offline_mode": bool(core.get("offline_mode", True)),
        "execution_policy": str(core.get("execution_policy") or "human-gated"),
        "hardware_actuation": bool(core.get("hardware_actuation", False)),
    }
    return JSONResponse(safe, status_code=reply.status_code)


@router.get("/health")
async def usect_zero_health():
    return await run_in_threadpool(_health)
