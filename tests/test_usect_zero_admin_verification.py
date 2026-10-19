"""Regression tests for USECT-ZERO's authoritative admin-verification boundary."""
from __future__ import annotations

import logging
import sys
import types

import pytest
import requests
from flask import Flask

from routes import meta_engineer_routes as admin_routes


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def call_verifier(monkeypatch, response=None, *, exception=None, authorization="Bearer test-jwt"):
    """Call the verifier with a fake identity resolver and upstream transport."""
    fake_app = types.ModuleType("app")
    fake_app.resolve_revelacode_user_id = lambda: "admin-user-42"
    monkeypatch.setitem(sys.modules, "app", fake_app)

    observed = {}

    def fake_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        if exception is not None:
            raise exception
        return response

    monkeypatch.setattr(admin_routes.requests, "get", fake_get)

    flask_app = Flask("admin-verification-test")
    with flask_app.test_request_context(
        "/api/usect-zero/keys/requests",
        headers={"Authorization": authorization},
    ):
        result = admin_routes._authenticated_admin()

    return result, observed


def test_admin_verification_uses_authoritative_backend_and_bounded_timeout(monkeypatch):
    upstream = FakeResponse(
        200,
        {
            "success": True,
            "authenticated": True,
            "authorized": True,
            "userId": "admin-user-42",
            "role": "platform_admin",
        },
    )

    result, observed = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor == "admin-user-42"
    assert error is None
    assert observed["url"] == (
        admin_routes.BACKEND_URL + "/api/auth/verify-admin"
    )
    assert observed["headers"] == {"Authorization": "Bearer test-jwt"}
    assert observed["allow_redirects"] is False
    assert observed["timeout"] == (3.05, admin_routes.ADMIN_TIMEOUT)
    assert 5 <= admin_routes.ADMIN_TIMEOUT <= 30


def test_admin_verification_fails_closed_and_logs_upstream_reason(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)
    upstream = FakeResponse(
        503,
        {
            "success": False,
            "authorized": False,
            "code": "role_lookup_unavailable",
        },
    )

    result, _ = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 503
    assert response.get_json()["code"] == "admin_verification_unavailable"
    assert "role_lookup_unavailable" in caplog.text
    assert "test-jwt" not in caplog.text


def test_admin_verification_timeout_fails_closed_without_logging_token(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)

    result, observed = call_verifier(
        monkeypatch,
        exception=requests.Timeout("upstream timed out"),
    )

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 503
    assert response.get_json()["code"] == "admin_verification_unavailable"
    assert "Timeout" in caplog.text
    assert "test-jwt" not in caplog.text
    assert observed["timeout"] == (3.05, admin_routes.ADMIN_TIMEOUT)
    assert observed["headers"]["Authorization"] == "Bearer test-jwt"


def test_non_admin_remains_forbidden_not_unavailable(monkeypatch):
    upstream = FakeResponse(
        403,
        {
            "success": False,
            "authorized": False,
            "code": "admin_required",
        },
    )

    result, _ = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 403
    assert response.get_json()["code"] == "admin_required"


def test_unstructured_upstream_404_is_not_misreported_as_missing_user(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)

    # A proxy-generated HTML 404 means the configured endpoint may be wrong;
    # it is not evidence that the authenticated user is missing.
    upstream = FakeResponse(404, ValueError("not JSON"))

    result, _ = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 503
    assert response.get_json()["code"] == "admin_verification_unavailable"
    assert "unexpected HTTP 404" in caplog.text


def test_authoritative_user_not_found_remains_forbidden(monkeypatch):
    upstream = FakeResponse(
        404,
        {
            "success": False,
            "authorized": False,
            "code": "user_not_found",
        },
    )

    result, _ = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 403
    assert response.get_json()["code"] == "user_not_found"


def test_malformed_success_payload_fails_closed(monkeypatch):
    upstream = FakeResponse(200, {"success": True})

    result, _ = call_verifier(monkeypatch, upstream)

    actor, error = result
    assert actor is None
    assert error is not None
    response, status = error
    assert status == 503
    assert response.get_json()["code"] == "admin_verification_unavailable"


def test_invalid_bearer_is_rejected_before_upstream_request(monkeypatch):
    def unexpected_get(*args, **kwargs):
        pytest.fail("invalid bearer must be rejected before an upstream call")

    monkeypatch.setattr(admin_routes.requests, "get", unexpected_get)

    fake_app = types.ModuleType("app")
    fake_app.resolve_revelacode_user_id = lambda: "admin-user-42"
    monkeypatch.setitem(sys.modules, "app", fake_app)

    flask_app = Flask("admin-verification-test")
    with flask_app.test_request_context(
        "/api/usect-zero/keys/requests",
        headers={"Authorization": "Basic not-a-bearer"},
    ):
        actor, error = admin_routes._authenticated_admin()

    assert actor is None
    assert error is not None
    response, status = error
    assert status == 401
    assert response.get_json()["code"] == "authentication_required"
