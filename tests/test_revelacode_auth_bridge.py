"""Tests for the server-to-server RevelaCode session-validation bridge."""

from bson import ObjectId
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import auth as auth_routes
from fastapi_routes import core_mesh as core_mesh_routes
from fastapi_routes import security_academy as academy_routes


client = TestClient(app)


class StubResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_authoritative_identity_check_forwards_bearer_to_revelacode(monkeypatch):
    user_id = "507f1f77" + "bcf86cd7" + "99439011"
    captured = {}

    def fake_get(url, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return StubResponse(
            200,
            {
                "success": True,
                "authenticated": True,
                "userId": user_id,
                "user": {"id": user_id, "role": "user"},
            },
        )

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)
    resolved_id, error = auth_routes.resolve_revelacode_user("bearer test-signed-token")

    assert error is None
    assert resolved_id == user_id
    assert captured["url"].endswith("/api/auth/me")
    assert captured["headers"]["Authorization"] == "Bearer test-signed-token"
    assert captured["timeout"] > 0


def test_authoritative_identity_check_returns_backend_token_error(monkeypatch):
    monkeypatch.setattr(
        auth_routes.requests,
        "get",
        lambda *args, **kwargs: StubResponse(
            401,
            {"success": False, "code": "token_expired", "message": "Session expired."},
        ),
    )

    user_id, error = auth_routes.resolve_revelacode_user("Bearer old-token")

    assert user_id is None
    assert error is not None
    assert error.status_code == 401
    assert error.body
    assert b"token_expired" in error.body


def test_authoritative_identity_check_fails_closed_when_backend_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise auth_routes.requests.RequestException("backend unavailable")

    monkeypatch.setattr(auth_routes.requests, "get", unavailable)
    user_id, error = auth_routes.resolve_revelacode_user("Bearer test-token")

    assert user_id is None
    assert error is not None
    assert error.status_code == 503


def test_security_academy_courses_uses_revelacode_verified_identity(monkeypatch):
    user_id = "507f1f77" + "bcf86cd7" + "99439011"
    received = {}

    def fake_get(url, headers, timeout):
        assert url.endswith("/api/auth/me")
        assert headers["Authorization"] == "Bearer valid-token"
        return StubResponse(
            200,
            {
                "success": True,
                "authenticated": True,
                "userId": user_id,
                "user": {"id": user_id, "role": "user"},
            },
        )

    def fake_list_courses(user_oid):
        received["user_oid"] = user_oid
        return []

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)
    monkeypatch.setattr(academy_routes, "list_courses", fake_list_courses)

    response = client.get(
        "/api/security-academy/courses",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["courses"] == []
    assert received["user_oid"] == ObjectId(user_id)


def test_security_academy_surfaces_authoritative_invalid_token_code(monkeypatch):
    monkeypatch.setattr(
        auth_routes.requests,
        "get",
        lambda *args, **kwargs: StubResponse(
            401,
            {"success": False, "code": "invalid_token", "message": "RevelaCode rejected this token."},
        ),
    )

    response = client.get(
        "/api/security-academy/courses",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_core_mesh_dashboard_uses_authoritative_identity_not_local_jwt_secret(monkeypatch):
    user_id = "507f1f77" + "bcf86cd7" + "99439011"
    monkeypatch.setattr(
        core_mesh_routes,
        "resolve_revelacode_user",
        lambda authorization: (user_id, None)
        if authorization == "Bearer verified-token"
        else (None, None),
    )
    monkeypatch.setattr(
        core_mesh_routes,
        "get_core_mesh_dashboard",
        lambda force_refresh=False: {"cores": {"zero": {"reachable": True}}},
    )

    response = client.get(
        "/api/core-mesh/dashboard",
        headers={"Authorization": "Bearer verified-token"},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "success"
