"""Regression tests for the SSE image-generation entitlement gate."""
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import stream as stream_routes


def test_stream_direct_image_requires_entitlement_before_provider_call(monkeypatch):
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(stream_routes, "detect_capability", lambda *args, **kwargs: "image_generation")
    monkeypatch.setattr(stream_routes, "check_entitlement", lambda *args, **kwargs: (None, denied))
    monkeypatch.setattr(
        stream_routes,
        "generate_image_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("image generation must not run after entitlement denial")
        ),
    )

    client = TestClient(app)
    response = client.post("/ai/stream", json={"message": "generate a picture of a cat"})

    assert response.status_code == 402
    assert response.json()["code"] == "premium_entitlement_required"


def test_stream_model_image_action_requires_entitlement_before_generation(monkeypatch):
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(stream_routes, "detect_capability", lambda *args, **kwargs: "text")
    monkeypatch.setattr(stream_routes, "process_message", lambda **kwargs: {
        "action_required": True,
        "action": {"type": "image_generation"},
    })
    monkeypatch.setattr(stream_routes, "check_entitlement", lambda *args, **kwargs: (None, denied))
    monkeypatch.setattr(
        stream_routes,
        "generate_image_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("model-triggered image generation must not run after entitlement denial")
        ),
    )

    client = TestClient(app)
    response = client.post("/ai/stream", json={"message": "please do something creative"})

    assert response.status_code == 200
    assert "premium_entitlement_required" in response.text
    assert "event: error" in response.text
