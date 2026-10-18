"""Regression tests for the USECT-ZERO backend adapter."""
from __future__ import annotations

import json

import pytest
from flask import Flask, jsonify

from routes import usect_zero_routes as routes
from services import usect_zero_client as client


@pytest.fixture
def test_client():
    app = Flask(__name__)
    app.register_blueprint(routes.usect_zero_bp, url_prefix="/api/usect-zero")
    app.config.update(TESTING=True, MAX_CONTENT_LENGTH=25 * 1024 * 1024)
    return app.test_client()


def test_public_key_request_stays_pending_and_needs_no_platform_admin(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(
            202,
            {"status": "pending_approval", "secret_issued": False},
        )

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.post(
        "/api/usect-zero/keys/request",
        json={
            "name": "Sample developer",
            "email": "developer@example.invalid",
            "reason": "Need a read-only repository scan",
            "scopes": ["scan:read"],
        },
    )

    assert response.status_code == 202
    assert response.get_json()["secret_issued"] is False
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/keys/request"
    assert observed["admin"] is False
    assert observed["api_key"] is None


def test_admin_key_list_fails_closed_before_calling_core(monkeypatch, test_client):
    called = False

    def deny_admin():
        nonlocal called
        return None, (jsonify({"status": "error", "code": "admin_required"}), 403)

    def fake_core(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("core must not be called before admin authentication")

    monkeypatch.setattr(routes, "_require_platform_admin", deny_admin)
    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get("/api/usect-zero/keys/requests")

    assert response.status_code == 403
    assert response.get_json()["code"] == "admin_required"
    assert called is False


def test_admin_approval_uses_internal_admin_channel(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(routes, "_require_platform_admin", lambda: ("admin-user-42", None))
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(200, {"status": "approved", "shown_once": True})

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.post(
        "/api/usect-zero/keys/requests/req_123/approve",
        json={"confirmation": "ISSUE_KEY", "ttl_days": 30},
        headers={"Authorization": "Bearer caller-jwt"},
    )

    assert response.status_code == 200
    assert observed["path"] == "/v1/keys/requests/req_123/approve"
    assert observed["admin"] is True
    assert observed["api_key"] is None
    assert json.loads(observed["body"])["confirmation"] == "ISSUE_KEY"


def test_scoped_api_key_is_forwarded_but_bearer_token_is_not(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(routes, "request_core", lambda *args, **kwargs: client.CoreReply(200, {"read_only": True}))
    observed = {}
    original = client.request_core

    def capture_request(method, path, **kwargs):
        observed.update(kwargs)
        return original(method, path, **kwargs)

    # Exercise the real client boundary with a fake HTTP transport.
    monkeypatch.setenv("USECT_ZERO_URL", "http://127.0.0.1:8780")
    class FakeHTTPResponse:
        status_code = 200
        content = b'{"read_only": true}'

        @staticmethod
        def json():
            return {"read_only": True}

    def fake_http(method, url, **kwargs):
        observed["http_headers"] = kwargs["headers"]
        return FakeHTTPResponse()

    monkeypatch.setattr(client.requests, "request", fake_http)
    monkeypatch.setattr(routes, "request_core", client.request_core)
    response = test_client.get(
        "/api/usect-zero/scan",
        headers={
            "X-API-Key": "usect_scoped_key",
            "Authorization": "Bearer caller-jwt-must-not-be-forwarded",
        },
    )

    assert response.status_code == 200
    assert observed["http_headers"]["X-API-Key"] == "usect_scoped_key"
    assert "Authorization" not in observed["http_headers"]
    assert "X-Admin-Token" not in observed["http_headers"]


def test_disabled_core_does_not_make_network_call(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "false")

    def unexpected_http(*args, **kwargs):
        raise AssertionError("disabled integration must not call the network")

    monkeypatch.setattr(client.requests, "request", unexpected_http)
    with pytest.raises(client.USECTZeroDisabled):
        client.request_core("GET", "/v1/health")


def test_admin_actions_require_separate_server_side_token(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.delenv("USECT_ZERO_ADMIN_TOKEN", raising=False)
    with pytest.raises(client.USECTZeroAdminTokenMissing):
        client.request_core("POST", "/v1/heal/baseline", admin=True)


def test_forwarded_path_cannot_escape_versioned_api(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    with pytest.raises(client.USECTZeroConfigurationError):
        client.request_core("GET", "/v1/../keys/requests")


def test_post_body_is_bounded_and_must_be_json(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(
        routes,
        "request_core",
        lambda *args, **kwargs: pytest.fail("invalid request must not reach core"),
    )

    response = test_client.post(
        "/api/usect-zero/keys/request",
        data="not-json",
        content_type="text/plain",
    )
    assert response.status_code == 415
    assert response.get_json()["code"] == "json_required"


def test_invalid_admin_resource_identifier_is_rejected(monkeypatch, test_client):
    monkeypatch.setattr(routes, "_require_platform_admin", lambda: ("admin-user", None))
    monkeypatch.setattr(
        routes,
        "request_core",
        lambda *args, **kwargs: pytest.fail("invalid identifiers must not reach core"),
    )
    response = test_client.post("/api/usect-zero/keys/requests/%2e%2e%2fsecret/approve", json={})
    assert response.status_code in {400, 404}
