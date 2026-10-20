"""Regression tests for the USECT-ZERO backend adapter."""
from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import usect_zero as routes
from services import usect_zero_client as client


@pytest.fixture
def test_client():
    return TestClient(app)


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
    assert response.json()["secret_issued"] is False
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/keys/request"
    assert observed["admin"] is False
    assert observed["api_key"] is None


def test_admin_key_list_fails_closed_before_calling_core(monkeypatch, test_client):
    called = False

    def deny_admin():
        nonlocal called
        return None, JSONResponse({"status": "error", "code": "admin_required"}, status_code=403)

    def fake_core(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("core must not be called before admin authentication")

    monkeypatch.setattr(routes, "require_platform_admin", deny_admin)
    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get("/api/usect-zero/keys/requests")

    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"
    assert called is False


def test_admin_approval_uses_internal_admin_channel(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(routes, "require_platform_admin", lambda _authorization: ("admin-user-42", None))
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

        def iter_content(self, chunk_size=65536):
            yield self.content

        @staticmethod
        def json():
            return {"read_only": True}

        @staticmethod
        def close():
            return None

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
    assert response.json()["code"] == "json_required"


def test_invalid_admin_resource_identifier_is_rejected(monkeypatch, test_client):
    monkeypatch.setattr(routes, "require_platform_admin", lambda _authorization: ("admin-user", None))
    monkeypatch.setattr(
        routes,
        "request_core",
        lambda *args, **kwargs: pytest.fail("invalid identifiers must not reach core"),
    )
    response = test_client.post("/api/usect-zero/keys/requests/%2e%2e%2fsecret/approve", json={})
    assert response.status_code in {400, 404}



def test_core_response_stream_is_capped(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")

    class OversizedHTTPResponse:
        status_code = 200

        def iter_content(self, chunk_size=65536):
            yield b"x" * (client.MAX_RESPONSE_BYTES + 1)

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(
        client.requests,
        "request",
        lambda *args, **kwargs: OversizedHTTPResponse(),
    )

    with pytest.raises(client.USECTZeroResponseTooLarge):
        client.request_core("GET", "/v1/health")


def test_health_response_does_not_expose_repository_path(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(
        routes,
        "request_core",
        lambda *args, **kwargs: client.CoreReply(
            200,
            {
                "status": "ok",
                "service": "USECT-ZERO",
                "model_free": True,
                "offline_mode": True,
                "repository_root": "/srv/private/repository",
                "execution_policy": "human-gated",
                "hardware_actuation": False,
            },
        ),
    )

    response = test_client.get("/api/usect-zero/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_free"] is True
    assert payload["offline_mode"] is True
    assert "repository_root" not in payload
    assert "/srv/private/repository" not in response.text


def test_health_when_disabled_does_not_call_core(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "false")
    monkeypatch.setattr(
        routes,
        "request_core",
        lambda *args, **kwargs: pytest.fail("disabled health must not call the core"),
    )

    response = test_client.get("/api/usect-zero/health")

    assert response.status_code == 503
    assert response.json()["status"] == "disabled"


def test_client_uses_server_side_admin_token_without_forwarding_authorization(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setenv("USECT_ZERO_ADMIN_TOKEN", "server-side-admin-secret")
    monkeypatch.setenv("USECT_ZERO_URL", "http://127.0.0.1:8780")
    observed = {}

    class FakeHTTPResponse:
        status_code = 200

        def iter_content(self, chunk_size=65536):
            yield b'{"status":"baseline_recorded"}'

        @staticmethod
        def close():
            return None

    def fake_http(method, url, **kwargs):
        observed.update(method=method, url=url, **kwargs)
        return FakeHTTPResponse()

    monkeypatch.setattr(client.requests, "request", fake_http)
    reply = client.request_core("POST", "/v1/heal/baseline", admin=True)

    assert reply.status_code == 200
    assert observed["headers"]["X-Admin-Token"] == "server-side-admin-secret"
    assert "Authorization" not in observed["headers"]
    assert "X-API-Key" not in observed["headers"]
    assert observed["allow_redirects"] is False
    assert observed["stream"] is True

def test_admin_issued_key_list_uses_admin_channel_without_exposing_hash(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setattr(routes, "require_platform_admin", lambda _authorization: ("admin-user-42", None))
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(
            200,
            {
                "status": "ok",
                "keys": [
                    {
                        "id": "key_123",
                        "request_id": "request_456",
                        "scopes": ["scan:read"],
                        "status": "active",
                    }
                ],
                "count": 1,
            },
        )

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get("/api/usect-zero/keys/issued?status=active")

    assert response.status_code == 200
    assert response.json()["keys"][0]["id"] == "key_123"
    assert "key_hash" not in response.text.lower()
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/keys/issued"
    assert observed["query"] == {"status": "active"}
    assert observed["admin"] is True
    assert observed["api_key"] is None


def test_diagnostics_route_uses_scoped_developer_key_channel(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(
            200,
            {
                "schema_version": "usect-zero.diagnostics.v1",
                "status": "ready",
                "baseline": {
                    "status": "compared",
                    "added_count": 0,
                    "modified_count": 0,
                    "missing_count": 0,
                },
            },
        )

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get(
        "/api/usect-zero/diagnostics",
        headers={"X-API-Key": "scoped-developer-key"},
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "usect-zero.diagnostics.v1"
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/diagnostics"
    assert observed["admin"] is False
    assert observed["api_key"] == "scoped-developer-key"


def test_assembly_template_catalog_uses_scoped_read_channel(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(
            200,
            {
                "status": "ok",
                "schema_version": "usect-zero.assembly-catalog.v1",
                "templates": [
                    {
                        "id": "esp32-sensor",
                        "target": "esp32-sensor",
                        "version": "1.0.0",
                        "validation_status": "valid_curated_template",
                    }
                ],
                "count": 1,
                "human_review_required": True,
            },
        )

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get(
        "/api/usect-zero/assemble/templates",
        headers={"X-API-Key": "scoped-read-key"},
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "usect-zero.assembly-catalog.v1"
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/assemble/templates"
    assert observed["admin"] is False
    assert observed["api_key"] == "scoped-read-key"


def test_assembly_board_profiles_proxy_through_scoped_gateway(monkeypatch, test_client):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(200, {
            "status": "ok",
            "schema_version": "usect-zero.board-profiles.v1",
            "boards": [{"id": "esp32-s3-generic", "hardware_verified": False}],
            "count": 1,
            "hardware_verified": False,
            "human_review_required": True,
        })

    monkeypatch.setattr(routes, "request_core", fake_core)
    response = test_client.get(
        "/api/usect-zero/assemble/boards",
        headers={"X-API-Key": "scoped-read-key"},
    )

    assert response.status_code == 200
    assert response.json()["hardware_verified"] is False
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/assemble/boards"
    assert observed["api_key"] == "scoped-read-key"
    assert observed["admin"] is False


def test_client_accepts_render_private_service_hostport(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_URL", "usect-zero-core-host:10000")
    assert client._base_url() == "http://usect-zero-core-host:10000"


@pytest.mark.parametrize(
    "value",
    [
        "usect-zero-core-host",
        "usect-zero-core-host:not-a-port",
        "usect-zero-core-host:10000/path",
        "user:pass@usect-zero-core-host:10000",
        "ftp://usect-zero-core-host:10000",
    ],
)
def test_client_rejects_malformed_render_service_reference(monkeypatch, value):
    monkeypatch.setenv("USECT_ZERO_URL", value)
    with pytest.raises(client.USECTZeroConfigurationError):
        client._base_url()
