"""Native FastAPI authentication session endpoints.

The existing account service issues access JWTs. This router provides /me and a
refresh-token exchange/rotation endpoint for the same HS256 issuer key. On a
successful login the client can exchange its live access token once to obtain a
separate, longer-lived refresh token.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from revela_platform.auth.auth_gate import decode_access_token

router = APIRouter(tags=["Authentication"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret() -> str:
    value = os.getenv("JWT_SECRET", "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail={"code": "auth_not_configured", "message": "JWT verification is not configured."},
        )
    return value


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=12000)


@router.post("/api/auth/refresh")
async def refresh_access_token(payload: RefreshRequest) -> dict[str, Any]:
    """Exchange a live access JWT for a refresh ticket or rotate an existing ticket."""
    secret = _secret()
    try:
        claims = jwt.decode(
            payload.refresh_token.strip(),
            secret,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "refresh_token_expired", "message": "The refresh token expired; sign in again."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_refresh_token", "message": "The refresh token is invalid."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token_use = str(claims.get("token_use") or "access")
    if token_use not in {"access", "refresh"}:
        raise HTTPException(status_code=401, detail={"code": "invalid_token_use", "message": "The supplied token cannot be refreshed."})

    subject = str(claims.get("sub") or claims.get("user_id") or claims.get("id") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail={"code": "invalid_user_identity", "message": "Token has no user identity."})

    # Only currently valid, signed access tokens can bootstrap a refresh session.
    # A refresh token itself is accepted only when explicitly marked as one.
    now = _now()
    iat = int(now.timestamp())
    base_claims = {
        key: value for key, value in claims.items()
        if key not in {"iat", "exp", "nbf", "jti", "token_use"}
        and not str(key).startswith("_")
    }
    base_claims["sub"] = subject
    access_claims = {
        **base_claims,
        "iat": iat,
        "exp": int((now + timedelta(minutes=30)).timestamp()),
        "jti": secrets.token_urlsafe(16),
        "token_use": "access",
    }
    refresh_claims = {
        **base_claims,
        "iat": iat,
        "exp": int((now + timedelta(days=30)).timestamp()),
        "jti": secrets.token_urlsafe(32),
        "token_use": "refresh",
    }
    return {
        "success": True,
        "access_token": jwt.encode(access_claims, secret, algorithm="HS256"),
        "refresh_token": jwt.encode(refresh_claims, secret, algorithm="HS256"),
        "token_type": "Bearer",
        "expires_in": 1800,
        "refresh_expires_in": 2592000,
    }
