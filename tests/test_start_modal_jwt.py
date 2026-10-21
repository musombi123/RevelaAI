from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastapi_routes.auth_endpoints import router as auth_router
from revela_platform.auth.auth_gate import enforce_auth


def signed_token(secret, *, lifetime_seconds=600):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "64b0000000000000000000aa",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=lifetime_seconds)).timestamp()),
            "role": "learner",
            "roles": ["learner", "builder"],
            "full_name": "Test Learner",
            "contact": "learner@example.test",
        },
        secret,
        algorithm="HS256",
    )


def make_client():
    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/protected")
    async def protected(claims=Depends(enforce_auth)):
        return {"sub": claims["sub"], "token_use": claims.get("token_use", "access")}

    return TestClient(app)


def test_start_modal_can_exchange_a_valid_access_jwt_for_persistent_refresh_ticket(monkeypatch):
    secret = "test-refresh-secret-not-for-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    client = make_client()

    response = client.post("/api/auth/refresh", json={"refresh_token": signed_token(secret)})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] == 1800
    assert payload["refresh_expires_in"] == 2592000

    access = jwt.decode(payload["access_token"], secret, algorithms=["HS256"])
    refresh = jwt.decode(payload["refresh_token"], secret, algorithms=["HS256"])
    assert access["sub"] == refresh["sub"]
    assert access["token_use"] == "access"
    assert refresh["token_use"] == "refresh"
    assert refresh["exp"] > access["exp"]
    assert set(refresh["roles"]) == {"learner", "builder"}


def test_refresh_token_cannot_be_reused_as_a_bearer_access_token(monkeypatch):
    secret = "test-refresh-secret-not-for-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    client = make_client()

    exchange = client.post("/api/auth/refresh", json={"refresh_token": signed_token(secret)})
    refresh = exchange.json()["refresh_token"]
    rejected = client.get("/protected", headers={"Authorization": f"Bearer {refresh}"})
    assert rejected.status_code == 401
    assert rejected.headers["content-type"].startswith("application/json")
    assert rejected.json()["detail"]["code"] == "refresh_token_not_allowed"


def test_expired_jwt_cannot_be_used_to_bootstrap_a_refresh_session(monkeypatch):
    secret = "test-refresh-secret-not-for-production"
    monkeypatch.setenv("JWT_SECRET", secret)
    client = make_client()

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": signed_token(secret, lifetime_seconds=-5)},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "refresh_token_expired"
