from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from revela_platform.auth.auth_gate import enforce_auth


def issue_token(secret: str, *, subject: str = "learner-1", lifetime: int = 3600, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=lifetime)).timestamp()),
        "contact": "learner@example.test",
        "full_name": "Test Learner",
        "role": "user",
        "roles": ["user", "learner"],
        **(extra or {}),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def protected_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/elimu/hubs")
    async def hubs(claims: dict = Depends(enforce_auth)):
        return {"success": True, "sub": claims["sub"]}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://revelacode.co.ke"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Revela-License"],
    )
    return app


@pytest.fixture
def auth_client(monkeypatch):
    secret = "unit-test-jwt-secret-not-for-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    return TestClient(protected_test_app()), secret


def test_no_token_returns_json_401_with_cors(auth_client):
    client, _ = auth_client
    response = client.get("/api/elimu/hubs", headers={"Origin": "https://revelacode.co.ke"})
    assert response.status_code == 401
    assert "application/json" in response.headers["content-type"]
    assert response.headers.get("access-control-allow-origin") == "https://revelacode.co.ke"
    assert response.json()["detail"]["code"] == "authentication_required"


def test_valid_hs256_token_allows_protected_route(auth_client):
    client, secret = auth_client
    response = client.get(
        "/api/elimu/hubs",
        headers={"Authorization": f"Bearer {issue_token(secret)}"},
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "sub": "learner-1"}


def test_expired_or_invalid_jwt_is_401_json(auth_client):
    client, secret = auth_client
    expired = issue_token(secret, lifetime=-10)
    for token in (expired, "not-a-jwt"):
        response = client.get("/api/elimu/hubs", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "application/json" in response.headers["content-type"]


def test_refresh_endpoint_rotates_access_and_refresh_tokens(monkeypatch):
    from fastapi_routes.auth_endpoints import router as refresh_router

    secret = "refresh-test-secret-not-for-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    app = FastAPI()
    app.include_router(refresh_router)
    client = TestClient(app)
    response = client.post("/api/auth/refresh", json={"refresh_token": issue_token(secret)})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["token_type"] == "Bearer"
    assert jwt.decode(body["access_token"], secret, algorithms=["HS256"])["sub"] == "learner-1"
    claims = jwt.decode(body["refresh_token"], secret, algorithms=["HS256"])
    assert claims["sub"] == "learner-1"
    assert claims["token_use"] == "refresh"
