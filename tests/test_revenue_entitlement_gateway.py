from __future__ import annotations

from unittest.mock import Mock

import requests
from fastapi.responses import JSONResponse

from services import revenue_entitlements as entitlements


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_revenue_entitlement_rejects_missing_bearer_without_network(monkeypatch):
    network = Mock()
    monkeypatch.setattr(entitlements.requests, "get", network)

    data, error = entitlements.check_entitlement("", hub="smart_ai", feature="image_generation")

    assert data is None
    assert isinstance(error, JSONResponse)
    assert error.status_code == 401
    network.assert_not_called()


def test_revenue_entitlement_allows_provider_feature_only_after_backend_approval(monkeypatch):
    monkeypatch.setattr(entitlements, "REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")
    monkeypatch.setattr(entitlements.requests, "get", lambda *args, **kwargs: FakeResponse(200, {
        "success": True,
        "allowed": True,
        "tier": "trial",
        "premium_access": True,
    }))

    data, error = entitlements.check_entitlement(
        "Bearer signed-test-token",
        hub="smart_ai",
        feature="image_generation",
    )

    assert error is None
    assert data["allowed"] is True
    assert data["tier"] == "trial"


def test_revenue_entitlement_denial_is_not_treated_as_provider_success(monkeypatch):
    monkeypatch.setattr(entitlements, "REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")
    monkeypatch.setattr(entitlements.requests, "get", lambda *args, **kwargs: FakeResponse(200, {
        "success": True,
        "allowed": False,
        "tier": "free",
        "trial_status": "expired",
        "premium_access": False,
    }))

    data, error = entitlements.check_entitlement(
        "Bearer signed-test-token",
        hub="smart_ai",
        feature="document_analysis",
    )

    assert data is None
    assert isinstance(error, JSONResponse)
    assert error.status_code == 402
    assert error.body is not None
    assert b"premium_entitlement_required" in error.body


def test_revenue_entitlement_fails_closed_when_backend_is_unreachable(monkeypatch):
    monkeypatch.setattr(entitlements, "REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")

    def raise_network_error(*args, **kwargs):
        raise requests.ConnectionError("test-only unavailable")

    monkeypatch.setattr(entitlements.requests, "get", raise_network_error)
    data, error = entitlements.check_entitlement(
        "Bearer signed-test-token",
        hub="smart_ai",
        feature="image_generation",
    )

    assert data is None
    assert isinstance(error, JSONResponse)
    assert error.status_code == 503


def test_revenue_entitlement_rejects_redirects_and_malformed_payloads(monkeypatch):
    monkeypatch.setattr(entitlements, "REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com")
    monkeypatch.setattr(entitlements.requests, "get", lambda *args, **kwargs: FakeResponse(302, {}))
    _, redirect_error = entitlements.check_entitlement(
        "Bearer signed-test-token", hub="smart_ai", feature="image_generation"
    )
    assert isinstance(redirect_error, JSONResponse)
    assert redirect_error.status_code == 503

    monkeypatch.setattr(entitlements.requests, "get", lambda *args, **kwargs: FakeResponse(200, {"success": False}))
    _, malformed_error = entitlements.check_entitlement(
        "Bearer signed-test-token", hub="smart_ai", feature="image_generation"
    )
    assert isinstance(malformed_error, JSONResponse)
    assert malformed_error.status_code == 503
