"""Tests for enforcing long-memory billing without coupling to production backend."""
from fastapi.responses import JSONResponse

from fastapi_routes import memory as memory_routes


def test_dedicated_memory_api_rejects_expired_entitlement(monkeypatch):
    monkeypatch.setattr(
        memory_routes,
        "authenticate_identity",
        lambda *args, **kwargs: ("memory-id", "verified-user", None),
    )
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(
        memory_routes,
        "check_entitlement",
        lambda *args, **kwargs: (None, denied),
    )

    _identity, _user_id, error = memory_routes._authenticate(
        {"authorization": "Bearer signed-test-token"}
    )

    assert error is denied
    assert error.status_code == 402
