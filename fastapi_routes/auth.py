"""Framework-independent authentication helpers for native FastAPI routes.

The signed JWT establishes identity, while RevelaCode's protected verification
endpoint remains the authority for whether the account exists. Identity hints
are consistency checks only and never establish identity.
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
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
REVELACODE_BACKEND_URL = (
    os.getenv("REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")
    .strip()
    .rstrip("/")
)
REVELAAI_SERVICE_KEY = (
    os.getenv("REVELAAI_SERVICE_KEY", "").strip()
    or os.getenv("REVELACODE_VERIFY_KEY", "").strip()
)
try:
    VERIFY_TIMEOUT_SECONDS = max(1.0, min(15.0, float(os.getenv("REVELACODE_VERIFY_TIMEOUT_SECONDS", "4"))))
except (TypeError, ValueError):
    VERIFY_TIMEOUT_SECONDS = 4.0


def authenticate_identity(
    authorization: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
    path_user_id: str = "",
) -> tuple[ObjectId | None, str | None, JSONResponse | None]:
    """Return (ObjectId, canonical user ID, error response), preserving memory API semantics."""
    if not JWT_SECRET:
        return None, None, JSONResponse(
            {"status": "error", "code": "auth_not_configured"}, status_code=503
        )
    header = (authorization or "").strip()
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
            headers.get("userid", ""),
            headers.get("x-user-id", ""),
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
            valid = bool(data.get("exists") and str(data.get("userId")) == user_id) if isinstance(data, dict) else False
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
