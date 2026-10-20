"""Native FastAPI gateway for the private USECT-ZERO Go core.

Client bearer credentials are never forwarded to the core. Administrator calls
require authoritative RevelaCode role verification and a separate server-side
USECT_ZERO_ADMIN_TOKEN; developer X-API-Key values are forwarded only for
scoped core operations that explicitly allow them.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.admin_auth import require_platform_admin
from services.usect_zero_client import (
    MAX_REQUEST_BYTES,
    CoreReply,
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
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ALLOWED_KEY_STATUSES = frozenset({"pending_approval", "approved", "rejected"})
_ALLOWED_ISSUED_KEY_STATUSES = frozenset({"active", "revoked", "expired"})


def _error(code: str, message: str, status: int):
    return JSONResponse(
        {"status": "error", "code": code, "message": message},
        status_code=status,
    )


async def _validate_post_body(request: Request):
    """Return bounded raw JSON bytes, or a client error before core forwarding."""
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_REQUEST_BYTES:
                return None, _error(
                    "payload_too_large",
                    "Request body exceeds the 1 MiB limit.",
                    413,
                )
        except ValueError:
            return None, _error("invalid_content_length", "Invalid Content-Length header.", 400)

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            return None, _error(
                "payload_too_large",
                "Request body exceeds the 1 MiB limit.",
                413,
            )
        chunks.append(chunk)
    body = b"".join(chunks)

    if body:
        mimetype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mimetype != "application/json":
            return None, _error(
                "json_required",
                "POST bodies must use application/json.",
                415,
            )
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return None, _error(
                "invalid_json",
                "Request body must contain valid JSON.",
                400,
            )
        if not isinstance(parsed, dict):
            return None, _error(
                "invalid_json",
                "Request body must be one JSON object.",
                400,
            )
    return body, None


def _proxy(
    method: str,
    upstream_path: str,
    *,
    request: Request,
    admin: bool = False,
    query: dict[str, str] | None = None,
    forward_api_key: bool = True,
    forward_device_token: bool = False,
    body: bytes | None = None,
):
    # Only X-API-Key may be passed through for scoped developer operations.
    # An end-user Authorization bearer token is never sent to the private core.
    api_key = None if admin or not forward_api_key else request.headers.get("X-API-Key")
    try:
        reply: CoreReply = request_core(
            method,
            upstream_path,
            body=body,
            query=query,
            api_key=api_key,
            admin=admin,
            device_token=request.headers.get("X-Device-Token") if forward_device_token else None,
        )
        return JSONResponse(reply.payload, status_code=reply.status_code)
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
        logger.warning("USECT-ZERO core request failed or returned invalid data.")
        return _error(
            "usect_zero_unavailable",
            "The USECT-ZERO core service is unavailable.",
            503,
        )
    except USECTZeroError:
        logger.warning("USECT-ZERO request was blocked by the integration boundary.")
        return _error(
            "usect_zero_request_blocked",
            "The USECT-ZERO request could not be processed.",
            503,
        )


def _admin_proxy(
    request: Request,
    method: str,
    upstream_path: str,
    *,
    query: dict[str, str] | None = None,
    body: bytes | None = None,
):
    _actor, error = require_platform_admin(request.headers.get("Authorization", ""))
    if error:
        return error
    return _proxy(
        method,
        upstream_path,
        request=request,
        admin=True,
        query=query,
        body=body,
    )


def _valid_resource_id(value: str) -> bool:
    return bool(_RESOURCE_ID.fullmatch(value or ""))


def _health_sync():
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
    # Health is intentionally public and the response omits absolute paths.
    class EmptyRequest:
        headers = {}
    return _health_proxy(EmptyRequest())


def _health_proxy(request_like):
    try:
        reply: CoreReply = request_core("GET", "/v1/health")
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
        return _error("usect_zero_misconfigured", "USECT-ZERO is not configured correctly.", 503)
    except USECTZeroUnavailable:
        logger.warning("USECT-ZERO health request failed or returned invalid data.")
        return _error("usect_zero_unavailable", "The USECT-ZERO core service is unavailable.", 503)
    except USECTZeroError:
        logger.warning("USECT-ZERO health request was blocked by the integration boundary.")
        return _error("usect_zero_request_blocked", "The USECT-ZERO request could not be processed.", 503)

    if reply.status_code >= 400:
        return JSONResponse(reply.payload, status_code=reply.status_code)

    core = reply.payload
    return JSONResponse(
        {
            "status": str(core.get("status") or "unknown"),
            "module": "usect-zero",
            "enabled": True,
            "model_free": bool(core.get("model_free", True)),
            "offline_mode": bool(core.get("offline_mode", True)),
            "execution_policy": str(core.get("execution_policy") or "human-gated"),
            "hardware_actuation": bool(core.get("hardware_actuation", False)),
        },
        status_code=reply.status_code,
    )


@router.get("/health")
async def usect_zero_health():
    return await run_in_threadpool(_health_sync)


@router.get("/activity")
async def usect_zero_activity(request: Request):
    _actor, error = require_platform_admin(request.headers.get("Authorization", ""))
    if error:
        return error
    from ai.usect_zero_tools import recent_activity
    return {
        "module": "usect-zero",
        "items": recent_activity(25),
        "persistent": False,
        "retention": "bounded in-memory; resets on process restart",
    }


@router.post("/keys/request")
async def request_developer_key(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy,
        "POST",
        "/v1/keys/request",
        request=request,
        forward_api_key=False,
        body=body,
    )


@router.get("/keys/requests")
async def list_key_requests(request: Request, status: str = ""):
    status = (status or "").strip()
    if status and status not in _ALLOWED_KEY_STATUSES:
        return _error("invalid_status_filter", "Unsupported key-request status filter.", 400)
    query = {"status": status} if status else None
    return await run_in_threadpool(
        _admin_proxy, request, "GET", "/v1/keys/requests", query=query
    )


@router.get("/keys/issued")
async def list_issued_keys(request: Request, status: str = ""):
    status = (status or "").strip()
    if status and status not in _ALLOWED_ISSUED_KEY_STATUSES:
        return _error("invalid_status_filter", "Unsupported issued-key status filter.", 400)
    query = {"status": status} if status else None
    return await run_in_threadpool(
        _admin_proxy, request, "GET", "/v1/keys/issued", query=query
    )


@router.post("/keys/requests/{request_id}/approve")
async def approve_key_request(request_id: str, request: Request):
    if not _valid_resource_id(request_id):
        return _error("invalid_request_id", "Invalid key-request identifier.", 400)
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy,
        request,
        "POST",
        f"/v1/keys/requests/{request_id}/approve",
        body=body,
    )


@router.post("/keys/issued/{key_id}/revoke")
async def revoke_developer_key(key_id: str, request: Request):
    if not _valid_resource_id(key_id):
        return _error("invalid_key_id", "Invalid issued-key identifier.", 400)
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy,
        request,
        "POST",
        f"/v1/keys/issued/{key_id}/revoke",
        body=body,
    )


@router.get("/supervisor/status")
async def usect_zero_supervisor_status(request: Request):
    return await run_in_threadpool(
        _admin_proxy, request, "GET", "/v1/supervisor/status"
    )


@router.post("/supervisor/kill-switch")
async def usect_zero_global_kill_switch(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy, request, "POST", "/v1/supervisor/kill-switch", body=body
    )


@router.get("/devices")
async def list_enrolled_devices(request: Request):
    return await run_in_threadpool(
        _admin_proxy, request, "GET", "/v1/devices"
    )


@router.post("/devices/enroll")
async def enroll_esp32_device(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy, request, "POST", "/v1/devices/enroll", body=body
    )


@router.post("/devices/{device_id}/revoke")
async def revoke_enrolled_device(device_id: str, request: Request):
    if not _valid_resource_id(device_id):
        return _error("invalid_device_id", "Invalid device identifier.", 400)
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy, request, "POST", f"/v1/devices/{device_id}/revoke", body=body
    )


@router.get("/devices/{device_id}/read")
async def read_enrolled_device(device_id: str, request: Request):
    if not _valid_resource_id(device_id):
        return _error("invalid_device_id", "Invalid device identifier.", 400)
    return await run_in_threadpool(
        _proxy, "GET", f"/v1/devices/{device_id}/read",
        request=request, forward_api_key=False, forward_device_token=True,
    )


@router.post("/devices/{device_id}/act")
async def act_on_enrolled_device(device_id: str, request: Request):
    if not _valid_resource_id(device_id):
        return _error("invalid_device_id", "Invalid device identifier.", 400)
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy, "POST", f"/v1/devices/{device_id}/act",
        request=request, forward_api_key=False, forward_device_token=True, body=body,
    )


@router.get("/diagnostics")
async def core_diagnostics(request: Request):
    return await run_in_threadpool(
        _proxy,
        "GET",
        "/v1/diagnostics",
        request=request,
    )


@router.get("/scan")
async def scan_repository(request: Request):
    return await run_in_threadpool(
        _proxy,
        "GET",
        "/v1/scan",
        request=request,
    )


@router.post("/heal/baseline")
async def record_healing_baseline(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy,
        request,
        "POST",
        "/v1/heal/baseline",
        body=body,
    )


@router.post("/heal/proposals")
async def propose_healing(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy,
        "POST",
        "/v1/heal/proposals",
        request=request,
        body=body,
    )


@router.post("/heal/proposals/{proposal_id}/approve")
async def approve_healing(proposal_id: str, request: Request):
    if not _valid_resource_id(proposal_id):
        return _error("invalid_proposal_id", "Invalid healing-proposal identifier.", 400)
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _admin_proxy,
        request,
        "POST",
        f"/v1/heal/proposals/{proposal_id}/approve",
        body=body,
    )


@router.get("/assemble/boards")
async def list_assembly_board_profiles(request: Request):
    return await run_in_threadpool(
        _proxy, "GET", "/v1/assemble/boards", request=request
    )


@router.get("/assemble/templates")
async def list_assembly_templates(request: Request):
    return await run_in_threadpool(
        _proxy, "GET", "/v1/assemble/templates", request=request
    )


@router.post("/assemble")
async def assemble_proposal(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy, "POST", "/v1/assemble", request=request, body=body
    )


@router.post("/radar/compare")
async def compare_radar_evidence(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy, "POST", "/v1/radar/compare", request=request, body=body
    )


@router.post("/bridge/plan")
async def propose_bridge_plan(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy, "POST", "/v1/bridge/plan", request=request, body=body
    )


@router.post("/mind/compile")
async def compile_rv_plan(request: Request):
    body, error = await _validate_post_body(request)
    if error:
        return error
    return await run_in_threadpool(
        _proxy, "POST", "/v1/mind/compile", request=request, body=body
    )
