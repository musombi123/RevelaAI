"""Pure FastAPI JWT dependency for protected RevelaCode API routes.

Access tokens use the HS256 format issued by the current RevelaCode login
service. Do not silently switch these tokens to RS256: the issuer and verifier
must use the same signing algorithm/key. Certificates use a separate RSA key.
"""
from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


def decode_access_token(raw_token: str) -> dict[str, Any]:
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={"code": "auth_not_configured", "message": "JWT verification is not configured."},
        )
    try:
        claims = jwt.decode(
            raw_token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "token_expired", "message": "Authentication token expired."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_token", "message": "Invalid authentication token."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = str(claims.get("sub") or claims.get("user_id") or claims.get("id") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_user_identity", "message": "Token has no user identity."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims["sub"] = subject
    return claims


async def enforce_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """FastAPI dependency: verify Bearer scheme, JWT signature and expiration."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "A Bearer JWT is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(credentials.credentials)
    # Internal-only request context; route serializers must not expose this field.
    claims["_access_token"] = credentials.credentials
    return claims


def require_roles(*allowed_roles: str):
    """Build a FastAPI dependency that checks signed JWT role claims."""
    allowed = {str(role).strip().casefold() for role in allowed_roles if str(role).strip()}

    async def dependency(claims: dict[str, Any] = Depends(enforce_auth)) -> dict[str, Any]:
        raw_roles = claims.get("roles")
        if isinstance(raw_roles, str):
            roles = {raw_roles.casefold()}
        elif isinstance(raw_roles, list):
            roles = {str(role).casefold() for role in raw_roles}
        else:
            roles = set()
        role = str(claims.get("role") or "").casefold()
        if role:
            roles.add(role)
        if not roles.intersection(allowed):
            raise HTTPException(
                status_code=403,
                detail={"code": "role_required", "message": "This account does not have the required role."},
            )
        return claims

    return dependency
