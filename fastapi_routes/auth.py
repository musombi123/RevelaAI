"""Authentication bridge for native FastAPI routes.

RevelaCode Backend is the authority for JWT signature, expiry, account status,
and canonical identity. RevelaAI forwards the bearer token to the protected
current-user endpoint and uses only the canonical ID returned by that service.
Identity hints are consistency checks only and never establish identity.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping

import jwt
import requests
from bson import ObjectId
from bson.errors import InvalidId
from fastapi.responses import JSONResponse

logger = logging.getLogger("revelaai.fastapi.auth")
# Retained for compatibility with the main AI/chat memory identity adapter.
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
# Retained for the existing Meta-Engineer identity/verification contracts.
REVELAAI_SERVICE_KEY = (
    os.getenv("REVELAAI_SERVICE_KEY", "").strip()
    or os.getenv("REVELACODE_VERIFY_KEY", "").strip()
)
REVELACODE_BACKEND_URL = (
    os.getenv("REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")
    .strip()
    .rstrip("/")
)
try:
    VERIFY_TIMEOUT_SECONDS = max(1.0, min(15.0, float(os.getenv("REVELACODE_VERIFY_TIMEOUT_SECONDS", "4"))))
except (TypeError, ValueError):
    VERIFY_TIMEOUT_SECONDS = 4.0


def _header_value(headers: Mapping[str, str], name: str) -> str:
    """Read headers case-insensitively, including after a Starlette Headers -> dict conversion."""
    wanted = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == wanted:
            return str(value or "")
    return ""


def resolve_revelacode_user(
    authorization: str,
) -> tuple[str | None, JSONResponse | None]:
    """Validate a bearer token at RevelaCode's authoritative session endpoint.

    RevelaAI deliberately does not maintain a second JWT signing-secret copy
    for account authentication. The primary backend validates the signature,
    expiry, account status, and canonical identity.
    """
    parts = str(authorization or "").strip().split(None, 1)
    if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1].strip():
        return None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "authentication_required",
                    "message": "A valid RevelaCode Bearer session is required.",
                },
            },
            status_code=401,
        )

    bearer = "Bearer " + parts[1].strip()
    try:
        response = requests.get(
            f"{REVELACODE_BACKEND_URL}/api/auth/me",
            headers={"Authorization": bearer, "Accept": "application/json"},
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        logger.warning("RevelaCode authoritative session verification is unavailable")
        return None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "revelacode_auth_unavailable",
                    "message": "RevelaCode authentication could not be reached. The session was not accepted.",
                },
            },
            status_code=503,
        )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code != 200:
        supplied_code = str(data.get("code") or "").strip() if isinstance(data, dict) else ""
        supplied_message = str(data.get("message") or "").strip() if isinstance(data, dict) else ""
        if response.status_code == 401:
            status_code = 401
            code = supplied_code or "invalid_platform_session"
            message = supplied_message or "RevelaCode rejected this session. Sign in again to obtain a current token."
        elif response.status_code == 403:
            status_code = 403
            code = supplied_code or "platform_account_forbidden"
            message = supplied_message or "This RevelaCode account is not permitted to access the platform."
        elif response.status_code == 404:
            status_code = 401
            code = supplied_code or "platform_user_not_found"
            message = supplied_message or "The account for this session could not be found."
        else:
            status_code = 503
            code = "revelacode_auth_unavailable"
            message = "RevelaCode authentication is temporarily unavailable. Try again shortly."
        return None, JSONResponse(
            {
                "status": "error",
                "error": {"code": code, "message": message},
            },
            status_code=status_code,
        )

    if not isinstance(data, dict) or data.get("success") is not True or data.get("authenticated") is not True:
        return None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "invalid_revelacode_auth_response",
                    "message": "RevelaCode did not confirm an authenticated account.",
                },
            },
            status_code=503,
        )

    user_data = data.get("user") if isinstance(data.get("user"), dict) else {}
    user_id = str(
        data.get("userId")
        or data.get("id")
        or user_data.get("id")
        or user_data.get("user_id")
        or ""
    ).strip()
    if not user_id or len(user_id) > 128:
        return None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "invalid_revelacode_identity",
                    "message": "RevelaCode did not return a valid canonical account ID.",
                },
            },
            status_code=401,
        )

    return user_id, None


def authenticate_platform_identity(
    authorization: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
    path_user_id: str = "",
) -> tuple[ObjectId | None, str | None, JSONResponse | None]:
    """Return the authoritative RevelaCode identity for Academy progress."""
    header = authorization or _header_value(headers, "authorization")
    user_id, error = resolve_revelacode_user(header)
    if error:
        return None, None, error

    assert user_id is not None
    try:
        user_oid = ObjectId(user_id)
    except (InvalidId, TypeError, ValueError):
        return None, None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "invalid_user_identity",
                    "message": "This account ID cannot be used by the Security Academy progress store.",
                },
            },
            status_code=401,
        )

    hints = [
        str(value).strip()
        for value in (
            _header_value(headers, "userId"),
            _header_value(headers, "X-User-ID"),
            path_user_id,
            (payload or {}).get("userId", ""),
        )
        if value is not None and str(value).strip()
    ]
    if any(value != user_id for value in hints):
        return None, None, JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "user_identity_mismatch",
                    "message": "The supplied account ID does not match the authenticated RevelaCode session.",
                },
            },
            status_code=403,
        )

    return user_oid, user_id, None


def authenticate_identity(
    authorization: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
    path_user_id: str = "",
) -> tuple[ObjectId | None, str | None, JSONResponse | None]:
    """Keep the legacy protected-user-verification contract for memory routes."""
    if not JWT_SECRET:
        return None, None, JSONResponse(
            {"status": "error", "code": "auth_not_configured"}, status_code=503
        )
    header = (authorization or _header_value(headers, "authorization")).strip()
    if not header.startswith("Bearer ") or not header[7:].strip():
        return None, None, JSONResponse(
            {"status": "error", "code": "authentication_required"}, status_code=401
        )
    try:
        claims = jwt.decode(
            header[7:].strip(),
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["iat", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        return None, None, JSONResponse(
            {"status": "error", "code": "token_expired"}, status_code=401
        )
    except jwt.InvalidTokenError:
        return None, None, JSONResponse(
            {"status": "error", "code": "invalid_token"}, status_code=401
        )

    raw_user_id = str(claims.get("sub") or claims.get("user_id") or "").strip()
    try:
        user_oid = ObjectId(raw_user_id)
    except (InvalidId, TypeError, ValueError):
        return None, None, JSONResponse(
            {"status": "error", "code": "invalid_user_identity"}, status_code=401
        )
    user_id = str(user_oid)

    hints = [
        str(value).strip()
        for value in (
            _header_value(headers, "userId"),
            _header_value(headers, "X-User-ID"),
            path_user_id,
            (payload or {}).get("userId", ""),
        )
        if value is not None and str(value).strip()
    ]
    if any(value != user_id for value in hints):
        return None, None, JSONResponse(
            {"status": "error", "code": "user_identity_mismatch"}, status_code=403
        )

    if not REVELAAI_SERVICE_KEY:
        return None, None, JSONResponse(
            {"status": "error", "code": "user_verification_not_configured"}, status_code=503
        )
    try:
        response = requests.get(
            f"{REVELACODE_BACKEND_URL}/api/auth/verify/{user_id}",
            headers={"X-REVELAAI-SERVICE-KEY": REVELAAI_SERVICE_KEY},
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                data = {}
            valid = (
                bool(data.get("exists") and str(data.get("userId")) == user_id)
                if isinstance(data, dict) else False
            )
            if valid:
                return user_oid, user_id, None
            return None, None, JSONResponse(
                {"status": "error", "code": "user_verification_failed"}, status_code=403
            )
        if response.status_code == 404:
            return None, None, JSONResponse(
                {"status": "error", "code": "user_not_found"}, status_code=404
            )
        if response.status_code in (401, 403):
            return None, None, JSONResponse(
                {"status": "error", "code": "user_verification_forbidden"}, status_code=403
            )
    except requests.RequestException:
        logger.warning("RevelaCode user verification service unavailable")
    return None, None, JSONResponse(
        {"status": "error", "code": "user_verification_unavailable"}, status_code=503
    )
