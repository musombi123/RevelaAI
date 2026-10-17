from __future__ import annotations

import base64
import io

import pytest
from flask import Flask, jsonify
from PIL import Image

from routes import vision_routes


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(vision_routes.vision_bp, url_prefix="/api/vision")
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def valid_image_payload():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color=(24, 120, 88)).save(stream, format="JPEG")
    return {
        "image": base64.b64encode(stream.getvalue()).decode("ascii"),
        "mimeType": "image/jpeg",
        "prompt": "Describe this scene.",
    }


def test_vision_requires_authenticated_identity(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(
        vision_routes,
        "_require_identity",
        lambda: (None, None, (jsonify(status="error", code="unauthorized"), 401)),
    )
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 401


def test_vision_rejects_invalid_image_before_provider_call(client, monkeypatch):
    monkeypatch.setattr(vision_routes, "_require_identity", lambda: (None, "user-1", None))
    response = client.post("/api/vision/analyze", json={
        "image": "not-base64",
        "mimeType": "image/jpeg",
        "prompt": "Describe this scene.",
    })
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_image"


def test_vision_rejects_user_identity_mismatch(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "_require_identity", lambda: (None, "verified-user", None))
    valid_image_payload["userId"] = "different-user"
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 403
    assert response.get_json()["code"] == "user_identity_mismatch"


def test_vision_sends_ephemeral_frame_to_gemini(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "_require_identity", lambda: (None, "verified-user", None))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})

    class MockResponse:
        ok = True
        status_code = 200

        def json(self):
            return {"candidates": [{
                "content": {"parts": [{"text": "A small scene with visible objects."}]}
            }]}

    def mock_post(url, **kwargs):
        assert url.endswith("/test-vision-model:generateContent")
        assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "Describe this scene."
        assert kwargs["json"]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
        assert kwargs["timeout"] == (10, 40)
        return MockResponse()

    monkeypatch.setattr(vision_routes.requests, "post", mock_post)
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["reply"] == "A small scene with visible objects."
    assert payload["visionUsed"] is True
    assert payload["mediaRetained"] is False


def test_vision_reports_missing_provider_configuration(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "_require_identity", lambda: (None, "verified-user", None))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 503
    assert response.get_json()["code"] == "vision_provider_not_configured"
