"""Identity-header consistency tests for the native FastAPI Smart Memory router."""
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import auth as auth_module

USER_ID = "507f1f77bcf86cd799439011"
OTHER_ID = "507f1f77bcf86cd799439099"
TEST_SECRET = "native-fastapi-test-secret"


def _install_verified_test_identity(monkeypatch):
    token = "opaque-test-platform-session"
    monkeypatch.setattr(
        auth_module,
        "resolve_revelacode_user",
        lambda authorization: (USER_ID, None)
        if authorization == "Bearer " + token
        else (None, None),
    )
    return token


def test_header_must_match_authoritative_platform_identity(monkeypatch):
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


def test_body_cannot_conflict_with_authoritative_platform_identity(monkeypatch):
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
