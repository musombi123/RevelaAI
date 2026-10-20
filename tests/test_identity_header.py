"""Identity-header consistency tests for the native FastAPI Smart Memory router."""
import time

import jwt
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import auth as auth_module

USER_ID = "507f1f77bcf86cd799439011"
OTHER_ID = "507f1f77bcf86cd799439099"
TEST_SECRET = "native-fastapi-test-secret"


def _install_verified_test_identity(monkeypatch):
    monkeypatch.setattr(auth_module, "JWT_SECRET", TEST_SECRET)
    monkeypatch.setattr(auth_module, "REVELAAI_SERVICE_KEY", "test-service-key")

    class VerifiedUserResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"exists": True, "userId": USER_ID}

    monkeypatch.setattr(
        auth_module.requests,
        "get",
        lambda *args, **kwargs: VerifiedUserResponse(),
    )

    token = jwt.encode(
        {
            "sub": USER_ID,
            "user_id": USER_ID,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    return token


def test_header_must_match_signed_token(monkeypatch):
    token = _install_verified_test_identity(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/memory/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "userId": OTHER_ID,
        },
        json={"userMessage": "My farm grows maize"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "user_identity_mismatch"


def test_body_cannot_conflict_with_valid_identity_header(monkeypatch):
    token = _install_verified_test_identity(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/memory/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "userId": USER_ID,
        },
        json={"userId": OTHER_ID, "userMessage": "My farm grows maize"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "user_identity_mismatch"
