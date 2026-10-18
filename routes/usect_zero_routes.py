"""Flask gateway for USECT-ZERO.

Mount this blueprint at /api/usect-zero. The route layer authenticates platform
administrators; the Go core independently validates developer key scopes. No
caller-supplied Authorization token is forwarded to the core service.
"""
from __future__ import annotations

import json
import re

from flask import Blueprint, current_app, jsonify, request

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

usect_zero_bp = Blueprint("usect_zero_bp", __name__)
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ALLOWED_KEY_STATUSES = frozenset({"pending_approval", "approved", "rejected"})
_ALLOWED_ISSUED_KEY_STATUSES = frozenset({"active", "revoked", "expired"})


def _require_platform_admin():
    """Reuse the existing current-role check; JWT role claims are not trusted."""
    from routes.meta_engineer_routes import _authenticated_admin

    return _authenticated_admin()


def _error(code: str, message: str, status: int):
    return jsonify({"status": "error", "code": code, "message": message}), status


def _validate_post_body():
    """Return raw JSON bytes or a small Flask response tuple when invalid."""
    if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
        return None, _error("payload_too_large", "Request body exceeds the 1 MiB limit.", 413)

    body = request.stream.read(MAX_REQUEST_BYTES + 1) or b""
    if len(body) > MAX_REQUEST_BYTES:
        return None, _error("payload_too_large", "Request body exceeds the 1 MiB limit.", 413)

    if body:
        if request.mimetype != "application/json":
            return None, _error("json_required", "POST bodies must use application/json.", 415)
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return None, _error("invalid_json", "Request body must contain valid JSON.", 400)
        if not isinstance(parsed, dict):
            return None, _error("invalid_json", "Request body must be one JSON object.", 400)
    return body, None


def _proxy(
    method: str,
    upstream_path: str,
    *,
    admin: bool = False,
    query: dict[str, str] | None = None,
    forward_api_key: bool = True,
):
    body = None
    if method.upper() == "POST":
        body, error = _validate_post_body()
        if error:
            return error

    # Only X-API-Key is passed for developer operations. The client's
    # Authorization bearer token is deliberately never passed to the core.
    api_key = None if admin or not forward_api_key else request.headers.get("X-API-Key")
    try:
        reply: CoreReply = request_core(
            method,
            upstream_path,
            body=body,
            query=query,
            api_key=api_key,
            admin=admin,
        )
        return jsonify(reply.payload), reply.status_code
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
        return _error("usect_zero_response_too_large", "The core response exceeded the adapter limit.", 502)
    except USECTZeroConfigurationError:
        current_app.logger.error("USECT-ZERO has invalid server-side configuration.")
        return _error("usect_zero_misconfigured", "USECT-ZERO is not configured correctly.", 503)
    except USECTZeroUnavailable:
        current_app.logger.warning("USECT-ZERO core request failed or returned invalid data.")
        return _error("usect_zero_unavailable", "The USECT-ZERO core service is unavailable.", 503)
    except USECTZeroError:
        current_app.logger.warning("USECT-ZERO request was blocked by the integration boundary.")
        return _error("usect_zero_request_blocked", "The USECT-ZERO request could not be processed.", 503)


def _admin_proxy(method: str, upstream_path: str, *, query: dict[str, str] | None = None):
    _actor, error = _require_platform_admin()
    if error:
        return error
    return _proxy(method, upstream_path, admin=True, query=query)


def _valid_resource_id(value: str) -> bool:
    return bool(_RESOURCE_ID.fullmatch(value or ""))


@usect_zero_bp.get("/health")
def usect_zero_health():
    """Health response intentionally omits the core's absolute repository path."""
    if not is_enabled():
        return jsonify({
            "status": "disabled",
            "module": "usect-zero",
            "enabled": False,
            "model_free": True,
        }), 503

    response, status_code = _proxy("GET", "/v1/health")
    if status_code >= 400:
        return response

    core = response.get_json(silent=True) or {}
    safe = {
        "status": str(core.get("status") or "unknown"),
        "module": "usect-zero",
        "enabled": True,
        "model_free": bool(core.get("model_free", True)),
        "offline_mode": bool(core.get("offline_mode", True)),
        "execution_policy": str(core.get("execution_policy") or "human-gated"),
        "hardware_actuation": bool(core.get("hardware_actuation", False)),
    }
    return jsonify(safe), status_code


@usect_zero_bp.get("/activity")
def usect_zero_activity():
    """Return recent in-process tool outcomes to verified platform admins only."""
    _actor, error = _require_platform_admin()
    if error:
        return error
    from ai.usect_zero_tools import recent_activity

    return jsonify({
        "module": "usect-zero",
        "items": recent_activity(25),
        "persistent": False,
        "retention": "bounded in-memory; resets on process restart",
    }), 200


@usect_zero_bp.post("/keys/request")
def request_developer_key():
    """Public intake only: the Go core creates a pending request, never a key."""
    return _proxy("POST", "/v1/keys/request", forward_api_key=False)


@usect_zero_bp.get("/keys/requests")
def list_key_requests():
    status = (request.args.get("status") or "").strip()
    if status and status not in _ALLOWED_KEY_STATUSES:
        return _error("invalid_status_filter", "Unsupported key-request status filter.", 400)
    query = {"status": status} if status else None
    return _admin_proxy("GET", "/v1/keys/requests", query=query)


@usect_zero_bp.get("/keys/issued")
def list_issued_keys():
    status = (request.args.get("status") or "").strip()
    if status and status not in _ALLOWED_ISSUED_KEY_STATUSES:
        return _error("invalid_status_filter", "Unsupported issued-key status filter.", 400)
    query = {"status": status} if status else None
    return _admin_proxy("GET", "/v1/keys/issued", query=query)


@usect_zero_bp.post("/keys/requests/<request_id>/approve")
def approve_key_request(request_id: str):
    if not _valid_resource_id(request_id):
        return _error("invalid_request_id", "Invalid key-request identifier.", 400)
    return _admin_proxy("POST", f"/v1/keys/requests/{request_id}/approve")


@usect_zero_bp.post("/keys/issued/<key_id>/revoke")
def revoke_developer_key(key_id: str):
    if not _valid_resource_id(key_id):
        return _error("invalid_key_id", "Invalid issued-key identifier.", 400)
    return _admin_proxy("POST", f"/v1/keys/issued/{key_id}/revoke")


@usect_zero_bp.get("/diagnostics")
def core_diagnostics():
    """Return operational and baseline-drift diagnostics using scan:read scope."""
    return _proxy("GET", "/v1/diagnostics")


@usect_zero_bp.get("/scan")
def scan_repository():
    return _proxy("GET", "/v1/scan")


@usect_zero_bp.post("/heal/baseline")
def record_healing_baseline():
    return _admin_proxy("POST", "/v1/heal/baseline")


@usect_zero_bp.post("/heal/proposals")
def propose_healing():
    return _proxy("POST", "/v1/heal/proposals")


@usect_zero_bp.post("/heal/proposals/<proposal_id>/approve")
def approve_healing(proposal_id: str):
    if not _valid_resource_id(proposal_id):
        return _error("invalid_proposal_id", "Invalid healing-proposal identifier.", 400)
    return _admin_proxy("POST", f"/v1/heal/proposals/{proposal_id}/approve")


@usect_zero_bp.get("/assemble/templates")
def list_assembly_templates():
    """List versioned, validated assembly templates using the read-only scan scope."""
    return _proxy("GET", "/v1/assemble/templates")


@usect_zero_bp.post("/assemble")
def assemble_proposal():
    return _proxy("POST", "/v1/assemble")


@usect_zero_bp.post("/radar/compare")
def compare_radar_evidence():
    return _proxy("POST", "/v1/radar/compare")


@usect_zero_bp.post("/bridge/plan")
def propose_bridge_plan():
    return _proxy("POST", "/v1/bridge/plan")


@usect_zero_bp.post("/mind/compile")
def compile_rv_plan():
    return _proxy("POST", "/v1/mind/compile")
