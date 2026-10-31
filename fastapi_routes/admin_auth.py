"""Authoritative administrator verification for FastAPI-native routes.

RevelaCode is the identity provider and system of record. RevelaAI forwards the
existing bearer session to RevelaCode's protected verification endpoint, which
validates the signature, current account identity, and current administrator
role. RevelaAI must not require a second copy of the platform JWT secret.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any

import requests
from fastapi.responses import JSONResponse

logger = logging.getLogger("revelaai.fastapi.admin_auth")
_DEFAULT_BACKEND_URL = "https://revelacode-backend.onrender.com"
BACKEND_URL = (
    os.getenv("REVELACODE_BACKEND_URL", _DEFAULT_BACKEND_URL).strip().rstrip("/")
    or _DEFAULT_BACKEND_URL
)
PLATFORM_ADMIN_ROLES = frozenset(
    {"admin", "platform_admin", "super_admin", "revelacode_admin"}
)


def _admin_timeout() -> float:
    try:
        value = float(os.getenv("REVELACODE_ADMIN_VERIFY_TIMEOUT_SECONDS", "15"))
    except (TypeError, ValueError):
        return 15.0
    if not math.isfinite(value) or value < 5 or value > 30:
        return 15.0
    return value


ADMIN_TIMEOUT = _admin_timeout()


def _error(code: str, status_code: int, message: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"status": "error", "code": code}
    if message:
        payload["message"] = message
    return JSONResponse(payload, status_code=status_code)


def require_platform_admin(authorization: str) -> tuple[str | None, JSONResponse | None]:
    """Return the platform-verified operator ID or a fail-closed HTTP error.

    The browser's existing RevelaCode bearer token is forwarded unchanged in
    meaning (normalized to the standard Bearer scheme). RevelaCode's backend
    verifies the JWT and resolves the current database role. No local AI-side
    JWT secret, admin password, or second login is required.
    """
    header = (authorization or "").strip()
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1].strip():
        return None, _error("authentication_required", 401)

    forwarded_header = "Bearer " + parts[1].strip()
    try:
        response = requests.get(
            BACKEND_URL + "/api/auth/verify-admin",
            headers={"Authorization": forwarded_header},
            timeout=(3.05, ADMIN_TIMEOUT),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning(
            "RevelaCode administrator verification request failed (%s).",
            type(exc).__name__,
        )
        return None, _error(
            "admin_verification_unavailable",
            503,
            "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 401:
        code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else "authentication_required"
        )
        if code not in {
            "authentication_required",
            "token_expired",
            "invalid_token",
            "invalid_user_identity",
        }:
            code = "authentication_required"
        return None, _error(code, 401)

    if response.status_code == 403:
        upstream_code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else ""
        )
        code = upstream_code if upstream_code in {
            "admin_required", "user_identity_mismatch"
        } else "admin_required"
        return None, _error(code, 403)

    if response.status_code == 404:
        if isinstance(body, dict) and body.get("code") == "user_not_found":
            return None, _error("user_not_found", 403)
        logger.warning(
            "RevelaCode administrator-verification endpoint returned an unexpected HTTP 404."
        )
        return None, _error(
            "admin_verification_unavailable",
            503,
            "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        )

    if response.status_code != 200:
        upstream_code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else "unstructured_response"
        )
        logger.warning(
            "RevelaCode administrator verification returned HTTP %s (code=%s).",
            response.status_code,
            upstream_code[:80],
        )
        return None, _error(
            "admin_verification_unavailable",
            503,
            "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        )

    if not isinstance(body, dict):
        logger.warning(
            "RevelaCode administrator verification returned HTTP 200 with non-object JSON."
        )
        return None, _error(
            "admin_verification_unavailable",
            503,
            "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        )

    canonical_id = str(body.get("userId") or body.get("user_id") or body.get("id") or "").strip()
    role = str(body.get("role") or "").strip().lower()
    authorized = body.get("authorized")

    if not canonical_id or not role or not isinstance(authorized, bool):
        logger.warning(
            "RevelaCode administrator-verification returned an incomplete success payload."
        )
        return None, _error(
            "admin_verification_unavailable",
            503,
            "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        )

    # Do not trust cached/browser role labels. Only the authoritative response
    # from RevelaCode can authorize access to Meta-Engineer and its API routes.
    if authorized is not True or role not in PLATFORM_ADMIN_ROLES:
        return None, _error("admin_required", 403)

    return canonical_id, None
