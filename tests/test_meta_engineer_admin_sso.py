"""SSO contract tests for the Meta-Engineer admin gateway.

RevelaCode owns JWT verification and the live administrator role lookup.
RevelaAI must forward the current bearer session rather than demanding a
second JWT secret or a second login.
"""
import requests

from fastapi_routes import admin_auth


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def test_existing_revelacode_admin_session_is_forwarded_without_ai_jwt_secret(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            {
                "success": True,
                "authenticated": True,
                "authorized": True,
                "userId": "admin-42",
                "role": "admin",
            },
        )

    monkeypatch.setattr(admin_auth.requests, "get", fake_get)

    actor, error = admin_auth.require_platform_admin("Bearer shared-platform-session")

    assert actor == "admin-42"
    assert error is None
    assert len(calls) == 1
    url, options = calls[0]
    assert url == admin_auth.BACKEND_URL + "/api/auth/verify-admin"
    assert options["headers"]["Authorization"] == "Bearer shared-platform-session"
    assert options["allow_redirects"] is False
    assert options["timeout"][0] == 3.05
    assert not hasattr(admin_auth, "JWT_SECRET")


def test_missing_bearer_is_rejected_without_backend_call(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("The identity provider must not be called without a bearer token.")

    monkeypatch.setattr(admin_auth.requests, "get", unexpected_call)

    actor, error = admin_auth.require_platform_admin("")

    assert actor is None
    assert error.status_code == 401


def test_revelacode_denies_non_admin_role(monkeypatch):
    monkeypatch.setattr(
        admin_auth.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            403,
            {"success": False, "authorized": False, "code": "admin_required", "role": "user"},
        ),
    )

    actor, error = admin_auth.require_platform_admin("Bearer valid-member-session")

    assert actor is None
    assert error.status_code == 403
    assert b"admin_required" in error.body


def test_revelacode_service_failure_is_fail_closed(monkeypatch):
    def unavailable(*args, **kwargs):
        raise requests.Timeout("backend timed out")

    monkeypatch.setattr(admin_auth.requests, "get", unavailable)

    actor, error = admin_auth.require_platform_admin("Bearer valid-platform-session")

    assert actor is None
    assert error.status_code == 503
    assert b"admin_verification_unavailable" in error.body


def test_incomplete_identity_provider_response_is_fail_closed(monkeypatch):
    monkeypatch.setattr(
        admin_auth.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            200,
            {"success": True, "authorized": True, "role": "admin"},
        ),
    )

    actor, error = admin_auth.require_platform_admin("Bearer valid-platform-session")

    assert actor is None
    assert error.status_code == 503
    assert b"admin_verification_unavailable" in error.body
