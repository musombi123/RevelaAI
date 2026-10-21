from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from revela_platform.auth.auth_gate import enforce_auth


def build_client():
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://revelacode.co.ke"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Revela-License"],
    )

    @app.get("/protected")
    async def protected(claims=Depends(enforce_auth)):
        return {"success": True, "sub": claims["sub"], "roles": claims.get("roles", [])}

    return TestClient(app)


def signed_token(secret, *, expiry, sub="64b0000000000000000000aa"):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": sub, "iat": int(now.timestamp()), "exp": int(expiry.timestamp()), "roles": ["learner"]},
        secret,
        algorithm="HS256",
    )


def test_protected_route_rejects_missing_and_invalid_jwt_as_json(monkeypatch):
    secret = "test-authgate-secret-that-is-not-used-in-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    client = build_client()

    missing = client.get("/protected")
    assert missing.status_code == 401
    assert missing.headers["content-type"].startswith("application/json")

    invalid = client.get("/protected", headers={"Authorization": "Bearer definitely-not-a-jwt"})
    assert invalid.status_code == 401
    assert invalid.headers["content-type"].startswith("application/json")


def test_valid_and_expired_access_tokens(monkeypatch):
    secret = "test-authgate-secret-that-is-not-used-in-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    client = build_client()

    valid = signed_token(secret, expiry=datetime.now(timezone.utc) + timedelta(minutes=5))
    allowed = client.get("/protected", headers={"Authorization": f"Bearer {valid}"})
    assert allowed.status_code == 200
    assert allowed.json()["sub"] == "64b0000000000000000000aa"

    expired = signed_token(secret, expiry=datetime.now(timezone.utc) - timedelta(seconds=5))
    denied = client.get("/protected", headers={"Authorization": f"Bearer {expired}"})
    assert denied.status_code == 401
    assert denied.headers["content-type"].startswith("application/json")


def test_cors_preflight_allows_authorization_and_license_headers(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-authgate-secret-that-is-not-used-in-production")
    client = build_client()
    response = client.options(
        "/protected",
        headers={
            "Origin": "https://revelacode.co.ke",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-revela-license",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://revelacode.co.ke"
    assert "x-revela-license" in response.headers["access-control-allow-headers"].lower()
