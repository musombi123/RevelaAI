"""Regression tests for the native FastAPI administrator verification boundary."""
from __future__ import annotations

import json
import logging
import time

import jwt
import pytest
import requests

from fastapi_routes import admin_auth


TEST_SECRET = "admin-verification-test-secret"
USER_ID = "507f1f77bcf86cd799439011"


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def token_for_user(user_id=USER_ID):
    return jwt.encode(
        {"sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + 300},
        TEST_SECRET,
        algorithm="HS256",
    )


def call_verifier(monkeypatch, response=None, *, exception=None, authorization=None):
    """Call the native verifier with a real test JWT and fake upstream transport."""
    monkeypatch.setattr(admin_auth, "JWT_SECRET", TEST_SECRET)
    authorization = authorization or f"Bearer {token_for_user()}"
    observed = {}

    def fake_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        if exception is not None:
            raise exception
        return response

    monkeypatch.setattr(admin_auth.requests, "get", fake_get)
    actor, error = admin_auth.require_platform_admin(authorization)
    return (actor, error), observed


def error_payload(response):
    return json.loads(response.body.decode("utf-8"))


def test_admin_verification_uses_authoritative_backend_and_bounded_timeout(monkeypatch):
    upstream = FakeResponse(
        200,
        {
            "success": True,
            "authenticated": True,
            "authorized": True,
            "userId": USER_ID,
            "role": "platform_admin",
        },
    )

    (actor, error), observed = call_verifier(monkeypatch, upstream)

    assert actor == USER_ID
    assert error is None
    assert observed["url"] == admin_auth.BACKEND_URL + "/api/auth/verify-admin"
    assert observed["headers"] == {"Authorization": f"Bearer {token_for_user()}"}
    assert observed["allow_redirects"] is False
    assert observed["timeout"] == (3.05, admin_auth.ADMIN_TIMEOUT)
    assert 5 <= admin_auth.ADMIN_TIMEOUT <= 30


def test_admin_verification_fails_closed_and_logs_upstream_reason(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    upstream = FakeResponse(
        503,
        {"success": False, "authorized": False, "code": "role_lookup_unavailable"},
    )

    (actor, error), _ = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert error_payload(error)["code"] == "admin_verification_unavailable"
    assert "role_lookup_unavailable" in caplog.text
    assert token_for_user() not in caplog.text


def test_admin_verification_timeout_fails_closed_without_logging_token(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)

    (actor, error), observed = call_verifier(
        monkeypatch,
        exception=requests.Timeout("upstream timed out"),
    )

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert error_payload(error)["code"] == "admin_verification_unavailable"
    assert "Timeout" in caplog.text
    assert token_for_user() not in caplog.text
    assert observed["timeout"] == (3.05, admin_auth.ADMIN_TIMEOUT)
    assert observed["headers"]["Authorization"].startswith("Bearer ")


def test_non_admin_remains_forbidden_not_unavailable(monkeypatch):
    upstream = FakeResponse(
        403,
        {"success": False, "authorized": False, "code": "admin_required"},
    )

    (actor, error), _ = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 403
    assert error_payload(error)["code"] == "admin_required"


def test_unstructured_upstream_404_is_not_misreported_as_missing_user(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    upstream = FakeResponse(404, ValueError("not JSON"))

    (actor, error), _ = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert error_payload(error)["code"] == "admin_verification_unavailable"
    assert "unexpected HTTP 404" in caplog.text


def test_authoritative_user_not_found_remains_forbidden(monkeypatch):
    upstream = FakeResponse(
        404,
        {"success": False, "authorized": False, "code": "user_not_found"},
    )

    (actor, error), _ = call_verifier(monkeypatch, upstream)

    assert actor is None
    assert error is not None
    assert error.status_code == 403
    assert error_payload(error)["code"] == "user_not_found"


def test_malformed_success_payload_fails_closed(monkeypatch):
    (actor, error), _ = call_verifier(monkeypatch, FakeResponse(200, {"success": True}))

    assert actor is None
    assert error is not None
    assert error.status_code == 503
    assert error_payload(error)["code"] == "admin_verification_unavailable"


def test_invalid_bearer_is_rejected_before_upstream_request(monkeypatch):
    monkeypatch.setattr(admin_auth, "JWT_SECRET", TEST_SECRET)

    def unexpected_get(*args, **kwargs):
        pytest.fail("invalid bearer must be rejected before an upstream call")

    monkeypatch.setattr(admin_auth.requests, "get", unexpected_get)
    actor, error = admin_auth.require_platform_admin("Basic not-a-bearer")

    assert actor is None
    assert error is not None
    assert error.status_code == 401
    assert error_payload(error)["code"] == "authentication_required"
