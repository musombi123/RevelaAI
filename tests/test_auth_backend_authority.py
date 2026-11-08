"""The primary RevelaCode backend is the sole authority for AI session identity."""
from __future__ import annotations

from bson import ObjectId
from fastapi.responses import JSONResponse

from fastapi_routes import auth as auth_module


def test_authenticate_identity_delegates_to_revelacode_session_me(monkeypatch):
    user_id = "65f18a2a7f7f7f7f7f7f7f7f"
    calls = []

    def resolve(authorization):
        calls.append(authorization)
        return user_id, None

    monkeypatch.setattr(auth_module, "resolve_revelacode_user", resolve)

    identity, resolved_id, error = auth_module.authenticate_identity(
        "Bearer opaque-platform-session",
        {"authorization": "Bearer opaque-platform-session"},
        {"userId": user_id},
    )

    assert error is None
    assert identity == ObjectId(user_id)
    assert resolved_id == user_id
    assert calls == ["Bearer opaque-platform-session"]


def test_authenticate_identity_rejects_client_identity_mismatch(monkeypatch):
    user_id = "65f18a2a7f7f7f7f7f7f7f7f"
    monkeypatch.setattr(
        auth_module,
        "resolve_revelacode_user",
        lambda authorization: (user_id, None),
    )

    identity, resolved_id, error = auth_module.authenticate_identity(
        "Bearer opaque-platform-session",
        {"authorization": "Bearer opaque-platform-session"},
        {"userId": "65f18a2a7f7f7f7f7f7f7f70"},
    )

    assert identity is None
    assert resolved_id is None
    assert isinstance(error, JSONResponse)
    assert error.status_code == 403


def test_authenticate_identity_propagates_primary_backend_unavailability(monkeypatch):
    backend_error = JSONResponse(
        {"status": "error", "error": {"code": "revelacode_auth_unavailable"}},
        status_code=503,
    )
    monkeypatch.setattr(
        auth_module,
        "resolve_revelacode_user",
        lambda authorization: (None, backend_error),
    )

    identity, resolved_id, error = auth_module.authenticate_identity(
        "Bearer opaque-platform-session",
        {"authorization": "Bearer opaque-platform-session"},
    )

    assert identity is None
    assert resolved_id is None
    assert error is backend_error


def test_ai_auth_module_contains_no_local_jwt_secret_or_decoder():
    source = open(auth_module.__file__, encoding="utf-8").read()
    assert "JWT_SECRET" not in source
    assert "jwt.decode" not in source
    assert "resolve_revelacode_user(header)" in source
