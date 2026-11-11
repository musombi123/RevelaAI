"""Native FastAPI Live Vision validation and provider-contract tests."""
import base64
import io
import json

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from asgi import app
from fastapi_routes import vision as vision_routes


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def vision_trial_access(monkeypatch):
    # Provider-contract tests are isolated from the shared production billing API.
    monkeypatch.setattr(
        vision_routes,
        "check_entitlement",
        lambda *args, **kwargs: ({"success": True, "allowed": True, "tier": "trial"}, None),
    )


@pytest.fixture
def valid_image_payload():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color=(24, 120, 88)).save(stream, format="JPEG")
    return {
        "image": base64.b64encode(stream.getvalue()).decode("ascii"),
        "mimeType": "image/jpeg",
        "prompt": "Describe this scene.",
    }


def _authenticate_as(user_id="verified-user"):
    return lambda *args, **kwargs: (None, user_id, None)


def test_vision_requires_authenticated_identity(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(
        vision_routes,
        "authenticate_identity",
        lambda *args, **kwargs: (
            None,
            None,
            JSONResponse({"status": "error", "code": "unauthorized"}, status_code=401),
        ),
    )
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_vision_rejects_invalid_image_before_provider_call(client, monkeypatch):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("user-1"))
    response = client.post(
        "/api/vision/analyze",
        json={
            "image": "not-base64",
            "mimeType": "image/jpeg",
            "prompt": "Describe this scene.",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


def test_vision_rejects_user_identity_mismatch(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    valid_image_payload["userId"] = "different-user"
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 403
    assert response.json()["code"] == "user_identity_mismatch"


def test_vision_sends_ephemeral_frame_to_gemini(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})

    class MockResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{
                "content": {"parts": [{"text": "A small scene with visible objects."}]}
            }]}

    def mock_post(url, **kwargs):
        assert url.endswith("/test-vision-model:generateContent")
        assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "Describe this scene."
        assert kwargs["json"]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
        assert "temperature" not in kwargs["json"]["generationConfig"]
        assert "topP" not in kwargs["json"]["generationConfig"]
        assert "topK" not in kwargs["json"]["generationConfig"]
        assert kwargs["json"]["generationConfig"]["maxOutputTokens"] == 768
        assert kwargs["timeout"] == (10, 40)
        return MockResponse()

    monkeypatch.setattr(vision_routes.requests, "post", mock_post)
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["reply"] == "A small scene with visible objects."
    assert payload["visionUsed"] is True
    assert payload["mediaRetained"] is False



def test_shamba_vision_uses_shamba_advanced_analytics_entitlement(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    requested = {}
    def check_shamba_entitlement(*args, **kwargs):
        requested.update(kwargs)
        return {"success": True, "allowed": True, "tier": "trial"}, None

    monkeypatch.setattr(vision_routes, "check_entitlement", check_shamba_entitlement)
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", False)
    valid_image_payload["hub"] = "shamba"

    response = client.post("/api/vision/analyze", json=valid_image_payload)

    assert requested == {"hub": "shamba", "feature": "advanced_analytics"}
    assert response.status_code == 503
    assert response.json()["code"] == "vision_provider_not_configured"


def test_vision_rejects_unsupported_hub_before_entitlement(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(
        vision_routes,
        "check_entitlement",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Unsupported hubs must not reach entitlement checks")
        ),
    )
    valid_image_payload["hub"] = "biashara"

    response = client.post("/api/vision/analyze", json=valid_image_payload)

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_vision_hub"


def test_vision_reports_missing_provider_configuration(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 503
    assert response.json()["code"] == "vision_provider_not_configured"


def test_vision_maps_gemini_request_errors_to_actionable_message(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})

    class MockResponse:
        ok = False
        status_code = 400

        @staticmethod
        def json():
            return {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}

    monkeypatch.setattr(vision_routes.requests, "post", lambda *args, **kwargs: MockResponse())
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "vision_provider_request_rejected"
    assert body["providerStatus"] == 400
    assert "Gemini rejected" in body["message"]


def test_vision_reports_provider_quota_errors(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})

    class MockResponse:
        ok = False
        status_code = 429

        @staticmethod
        def json():
            return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}

    monkeypatch.setattr(vision_routes.requests, "post", lambda *args, **kwargs: MockResponse())
    response = client.post("/api/vision/analyze", json=valid_image_payload)
    assert response.status_code == 503
    assert response.json()["code"] == "vision_rate_limited"


def test_vision_rejects_without_entitlement_before_gemini_call(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(
        vision_routes,
        "check_entitlement",
        lambda *args, **kwargs: (
            None,
            JSONResponse(
                {"status": "error", "code": "premium_entitlement_required"},
                status_code=402,
            ),
        ),
    )
    monkeypatch.setattr(
        vision_routes.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Gemini must not be called when entitlement is denied")
        ),
    )

    response = client.post("/api/vision/analyze", json=valid_image_payload)

    assert response.status_code == 402
    assert response.json()["code"] == "premium_entitlement_required"


def test_shamba_leaf_returns_structured_differential_assessment(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})
    analysis = {
        "diagnostic_type": "leaf",
        "summary": "The image shows leaf lesions requiring differential checks.",
        "observations": ["Several pale spots are visible."],
        "likely_causes": [{
            "name": "Fungal leaf spot",
            "likelihood": "possible",
            "visual_evidence": ["Discrete pale lesions"],
            "differential": ["Spray injury", "Nutrient stress"],
            "verification": ["Inspect lesion margins and both leaf surfaces"],
        }],
        "severity": {"level": "moderate", "basis": "Limited visible affected area"},
        "confidence": {"level": "medium", "rationale": "Image is clear but lacks a scale"},
        "integrated_pest_management": ["Remove heavily affected fallen leaves and monitor spread"],
        "field_checks": ["Inspect nearby plants and the leaf underside"],
        "escalation": ["Submit a sample if lesions spread rapidly"],
        "limitations": ["A photograph cannot confirm a pathogen"],
    }

    class MockResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{
                "content": {"parts": [{"text": json.dumps(analysis)}]}
            }]}

    captured = {}

    def mock_post(url, **kwargs):
        captured.update(kwargs["json"])
        return MockResponse()

    monkeypatch.setattr(vision_routes.requests, "post", mock_post)
    valid_image_payload.update({
        "hub": "shamba",
        "analysisType": "leaf",
        "analysisContext": {"farm_name": "Namarambi", "crop_name": "Tomato"},
        "prompt": "Assess visible leaf health and likely causes.",
    })

    response = client.post("/api/vision/analyze", json=valid_image_payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["analysisType"] == "leaf"
    assert data["analysis"]["likely_causes"][0]["name"] == "Fungal leaf spot"
    assert "leaf" in captured["systemInstruction"]["parts"][0]["text"].lower()
    assert captured["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["generationConfig"]["maxOutputTokens"] >= 1500
    assert "Namarambi" in captured["contents"][0]["parts"][0]["text"]
    assert data["mediaRetained"] is False
    assert data["visionChatHandoff"] is False


def test_shamba_soil_never_turns_bare_soil_colour_into_ph(client, monkeypatch, valid_image_payload):
    monkeypatch.setattr(vision_routes, "authenticate_identity", _authenticate_as("verified-user"))
    monkeypatch.setattr(vision_routes, "GEMINI_ENABLED", True)
    monkeypatch.setattr(vision_routes, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(vision_routes, "GEMINI_MODEL", "test-vision-model")
    monkeypatch.setattr(vision_routes, "get_gemini_headers", lambda: {"x-goog-api-key": "test-key"})
    analysis = {
        "diagnostic_type": "soil",
        "summary": "Visible surface features can be described, but chemical properties are not measurable from this image.",
        "observations": ["Loose soil aggregates are visible."],
        "physical_assessment": {"surface_structure": "Loose aggregates", "texture_cues": "Not reliably assessable"},
        "pH_test": {"status": "not_assessable", "chart_match": "No test strip or chart visible", "estimated_ph": None, "estimated_range": None, "confidence": "not_applicable", "basis": "Bare-soil colour cannot measure pH"},
        "nutrient_assessment": {"status": "laboratory_test_required", "reason": "Nutrients cannot be inferred visually"},
        "confidence": {"level": "low", "rationale": "Single image"},
        "recommended_field_tests": ["Use a representative composite sample for laboratory testing"],
        "management_actions": ["Avoid lime or fertilizer changes until tests are available"],
        "limitations": ["pH and nutrient status cannot be measured from bare soil colour"],
    }

    class MockResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{
                "content": {"parts": [{"text": json.dumps(analysis)}]}
            }]}

    captured = {}

    def mock_post(url, **kwargs):
        captured.update(kwargs["json"])
        return MockResponse()

    monkeypatch.setattr(vision_routes.requests, "post", mock_post)
    valid_image_payload.update({
        "hub": "shamba",
        "analysisType": "soil",
        "analysisContext": {"farm_name": "Namarambi", "sample_depth_cm": 15},
        "prompt": "Assess bare soil and determine whether pH evidence is present.",
    })

    response = client.post("/api/vision/analyze", json=valid_image_payload)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["analysis"]["pH_test"]["status"] == "not_assessable"
    assert data["analysis"]["pH_test"]["estimated_ph"] is None
    assert data["analysis"]["nutrient_assessment"]["status"] == "laboratory_test_required"
    system = captured["systemInstruction"]["parts"][0]["text"]
    assert "Never infer soil pH" in system
    assert captured["generationConfig"]["responseMimeType"] == "application/json"
    assert data["mediaRetained"] is False
