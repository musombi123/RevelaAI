"""Regression tests for authoritative, single-session FastAPI admin verification."""
from __future__ import annotations

import json
import logging

import pytest
import requests

from fastapi_routes import admin_auth

ADMIN_ID = "admin-user-42"


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def call_verifier(monkeypatch, response=None, *, exception=None, authorization=None):
    """Exercise the active ASGI admin verifier with a stubbed RevelaCode call."""
    monkeypatch.setattr(admin_auth, "BACKEND_URL", "https://backend.example.test")
    observed = {}

    def fake_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        if exception is not None:
            raise exception
        return response

    monkeypatch.setattr(admin_auth.requests, "get", fake_get)
    bearer = authorization if authorization is not None else "Bearer session-issued-by-revelacode"
    result = admin_auth.require_platform_admin(bearer)
    return result, observed


def _error_body(response):
    return json.loads(response.body.decode("utf-8"))


def test_admin_verification_forwards_existing_revelacode_session_and_uses_bounded_timeout(monkeypatch):
    upstream = FakeResponse(
        200,
        {
            "success": True,
            "authenticated": True,
            "authorized": True,
            "userId": ADMIN_ID,
            "role": "platform_admin",
        },
    )
    token = "Bearer session-issued-by-revelacode"
    result, observed = call_verifier(monkeypatch, upstream, authorization=token)

    actor, error = result
    assert actor == ADMIN_ID
    assert error is None
    assert observed["url"] == "https://backend.example.test/api/auth/verify-admin"
    assert observed["headers"] == {"Authorization": token}
    assert observed["allow_redirects"] is False
    assert observed["timeout"] == (3.05, admin_auth.ADMIN_TIMEOUT)
    assert 5 <= admin_auth.ADMIN_TIMEOUT <= 30
    assert not hasattr(admin_auth, "JWT_SECRET")


def test_admin_verification_fails_closed_and_logs_upstream_reason(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    upstream = FakeResponse(
        503,
        {"success": False, "authorized": False, "code": "role_lookup_unavailable"},
    )

    (_actor, error), _observed = call_verifier(monkeypatch, upstream)

    assert error is not None
    assert error.status_code == 503
    assert _error_body(error)["code"] == "admin_verification_unavailable"
    assert "role_lookup_unavailable" in caplog.text


def test_admin_verification_timeout_fails_closed_without_logging_token(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    token = "Bearer private-session-value"
    (actor, error), observed = call_verifier(
        monkeypatch,
        exception=requests.Timeout("upstream timed out"),
        authorization=token,
    )

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert _error_body(error)["code"] == "admin_verification_unavailable"
    assert "Timeout" in caplog.text
    assert token not in caplog.text
    assert observed["timeout"] == (3.05, admin_auth.ADMIN_TIMEOUT)
    assert observed["headers"]["Authorization"] == token


def test_non_admin_remains_forbidden_not_unavailable(monkeypatch):
    upstream = FakeResponse(
        403,
        {"success": False, "authorized": False, "code": "admin_required"},
    )

    (actor, error), _observed = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 403
    assert _error_body(error)["code"] == "admin_required"


def test_unstructured_upstream_404_is_not_misreported_as_missing_user(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    upstream = FakeResponse(404, ValueError("not JSON"))

    (actor, error), _observed = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert _error_body(error)["code"] == "admin_verification_unavailable"
    assert "unexpected HTTP 404" in caplog.text


def test_authoritative_user_not_found_remains_forbidden(monkeypatch):
    upstream = FakeResponse(
        404,
        {"success": False, "authorized": False, "code": "user_not_found"},
    )

    (actor, error), _observed = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 403
    assert _error_body(error)["code"] == "user_not_found"


def test_malformed_success_payload_fails_closed(monkeypatch):
    (actor, error), _ = call_verifier(monkeypatch, FakeResponse(200, {"success": True}))

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert _error_body(error)["code"] == "admin_verification_unavailable"


def test_missing_bearer_is_rejected_without_an_upstream_request(monkeypatch):
    def unexpected_get(*args, **kwargs):
        pytest.fail("a missing bearer must be rejected before an upstream call")

    monkeypatch.setattr(admin_auth.requests, "get", unexpected_get)
    actor, error = admin_auth.require_platform_admin("")

    assert actor is None
    assert error is not None
    assert error.status_code == 401
    assert _error_body(error)["code"] == "authentication_required"


def test_non_bearer_authorization_scheme_is_rejected_without_an_upstream_request(monkeypatch):
    def unexpected_get(*args, **kwargs):
        pytest.fail("a non-bearer scheme must be rejected before an upstream call")

    monkeypatch.setattr(admin_auth.requests, "get", unexpected_get)
    actor, error = admin_auth.require_platform_admin("Basic not-a-bearer")

    assert actor is None
    assert error is not None
    assert error.status_code == 401
    assert _error_body(error)["code"] == "authentication_required"
