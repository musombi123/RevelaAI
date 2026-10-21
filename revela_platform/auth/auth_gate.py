"""Pure FastAPI JWT dependency for protected RevelaCode learning/API routes.

The authentication token format deliberately matches the existing RevelaCode
issuer (HS256 JWT_SECRET). Identity is also checked against the upstream
RevelaCode account-verification service; a valid signature alone does not
establish that the account still exists.
"""
from __future__ import annotations

import json
import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


def _decode_access_token(raw_token: str) -> dict[str, Any]:
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
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_token", "message": "Invalid authentication token."},
        ) from exc

    subject = str(claims.get("sub") or claims.get("user_id") or claims.get("id") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_user_identity", "message": "Token has no user identity."},
        )
    claims["sub"] = subject
    return claims


async def enforce_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """Validate the Bearer JWT and re-check account existence upstream."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "A Bearer JWT is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_access_token(credentials.credentials)
    try:
        # The helper performs the existing account-service introspection and
        # enforces token/header identity consistency; no Flask decorator is used.
        from fastapi_routes.auth import authenticate_identity

        identity, canonical_id, error = authenticate_identity(
            f"Bearer {credentials.credentials}",
            dict(request.headers),
            claims,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "identity_verification_unavailable", "message": "Account verification is unavailable."},
        ) from exc

    if error is not None:
        try:
            payload = json.loads(error.body.decode("utf-8"))
        except Exception:
            payload = {}
        code = str(payload.get("code") or payload.get("error") or "authentication_failed")
        status_code = int(error.status_code or 401)
        if status_code >= 500:
            code = "identity_verification_unavailable"
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": "The account could not be verified."},
            headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
        )

    claims["sub"] = str(canonical_id or claims["sub"])
    claims["_identity_id"] = str(identity) if identity is not None else claims["sub"]
    return claims


def require_roles(*allowed_roles: str):
    """Build a FastAPI dependency that checks JWT role claims."""
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
