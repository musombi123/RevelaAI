"""Fail-closed bridge to RevelaCode's authoritative revenue entitlements.

RevelaAI does not connect to the RevelaCode database or create subscription
records. It forwards the caller's existing bearer token to the backend gateway.
Essential text chat remains free; paid/trial checks are made only for premium
capabilities such as image generation.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests
from fastapi.responses import JSONResponse

from fastapi_routes.auth import REVELACODE_BACKEND_URL

logger = logging.getLogger("revelaai.revenue_entitlements")
_TIMEOUT_SECONDS = 4.0


def check_entitlement(
    authorization: str,
    *,
    hub: str,
    feature: str,
    timeout_seconds: float = _TIMEOUT_SECONDS,
) -> tuple[dict | None, JSONResponse | None]:
    """Return a verified central entitlement or a safe HTTP error response."""
    token = str(authorization or "").strip()
    if not token.startswith("Bearer ") or not token[7:].strip():
        return None, JSONResponse(
            {
                "status": "error",
                "code": "premium_login_required",
                "message": "Sign in and start the free month for this capability.",
                "entitlement": {"hub": hub, "feature": feature, "allowed": False},
            },
            status_code=401,
        )

    base = str(REVELACODE_BACKEND_URL or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"})
    ):
        logger.error("Revenue entitlement gateway URL is invalid")
        return None, JSONResponse(
            {
                "status": "error",
                "code": "revenue_gateway_not_configured",
                "message": "Premium access cannot be verified right now. Basic chat remains available.",
            },
            status_code=503,
        )

    try:
        response = requests.get(
            f"{base}/api/revenue/entitlements",
            params={"hub": hub, "feature": feature},
            headers={"Authorization": token, "Accept": "application/json"},
            timeout=max(0.25, min(15.0, float(timeout_seconds))),
            allow_redirects=False,
            proxies={"http": "", "https": ""},
        )
    except requests.RequestException:
        logger.warning("Central revenue entitlement service is unreachable")
        return None, JSONResponse(
            {
                "status": "error",
                "code": "revenue_entitlement_unavailable",
                "message": "Premium access could not be verified. Basic text chat remains available.",
            },
            status_code=503,
        )

    if 300 <= response.status_code < 400:
        return None, JSONResponse(
            {
                "status": "error",
                "code": "revenue_redirect_rejected",
                "message": "Premium access could not be verified. Basic text chat remains available.",
            },
            status_code=503,
        )
    if response.status_code in {401, 403}:
        return None, JSONResponse(
            {
                "status": "error",
                "code": "premium_authentication_required",
                "message": "Your account could not be authenticated for this premium capability.",
            },
            status_code=response.status_code,
        )
    if response.status_code != 200:
        logger.warning("Revenue entitlement gateway returned HTTP %s", response.status_code)
        return None, JSONResponse(
            {
                "status": "error",
                "code": "revenue_entitlement_unavailable",
                "message": "Premium access could not be verified. Basic text chat remains available.",
            },
            status_code=503,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        logger.warning("Revenue entitlement gateway returned an invalid response")
        return None, JSONResponse(
            {
                "status": "error",
                "code": "invalid_revenue_entitlement_response",
                "message": "Premium access could not be verified. Basic text chat remains available.",
            },
            status_code=503,
        )
    if payload.get("allowed") is not True:
        feature_labels = {
            "image_generation": "image generation",
            "document_analysis": "document analysis",
            "voice_generation": "voice generation",
            "long_memory": "persistent memory",
            "vision_analysis": "Live Vision analysis",
            "automation": "advanced AI tools",
        }
        hub_label = "RevelaAI" if hub == "smart_ai" else hub.replace("_", " ").title()
        feature_label = feature_labels.get(feature, "this premium capability")
        return None, JSONResponse(
            {
                "status": "error",
                "code": "premium_entitlement_required",
                "message": f"Start your one-time 30-day {hub_label} trial or subscribe to enable {feature_label}.",
                "entitlement": {
                    "hub": hub,
                    "feature": feature,
                    "allowed": False,
                    "tier": payload.get("tier", "free"),
                    "trial_status": payload.get("trial_status", "not_started"),
                    "premium_access": payload.get("premium_access", False),
                },
            },
            status_code=402,
        )
    return payload, None
