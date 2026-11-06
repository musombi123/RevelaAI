"""API tests for explicit Gemini-only selected-passage generation."""
import json

from fastapi.testclient import TestClient

from asgi import app
from fastapi.responses import JSONResponse
from fastapi_routes import humanizer as humanizer_routes

client = TestClient(app)


def _authenticate_user(_authorization):
    return "humanizer-test-user", None


def test_generate_uses_gemini_and_sends_only_selected_passage(monkeypatch):
    from ai import ai_client

    monkeypatch.setattr(humanizer_routes, "resolve_revelacode_user", _authenticate_user)
    captured = {}

    def fake_gemini(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "response": "A clearer version of the selected sentence.",
            "provider": "gemini",
            "model": "gemini-test",
            "fallback_used": False,
        }

    monkeypatch.setattr(ai_client, "ask_gemini", fake_gemini)
    selected = "This is the exact passage I want to improve."
    response = client.post(
        "/api/humanizer/generate",
        headers={"Authorization": "Bearer test-token"},
        json={"selected_text": selected, "style": "clear"},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-test"
    assert body["humanized_text"] == "A clearer version of the selected sentence."
    assert body["applied"] is False
    prompt_payload = json.loads(captured["text"])
    assert prompt_payload["selected_text"] == selected
    assert set(prompt_payload) == {"task", "style", "style_guidance", "selected_text"}
    assert "rewrite only the selected passage" in captured["system_prompt"].lower()


def test_generate_rejects_empty_selection_before_gemini(monkeypatch):
    from ai import ai_client

    monkeypatch.setattr(humanizer_routes, "resolve_revelacode_user", _authenticate_user)
    monkeypatch.setattr(
        ai_client,
        "ask_gemini",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini must not be called")),
    )
    response = client.post(
        "/api/humanizer/generate",
        headers={"Authorization": "Bearer test-token"},
        json={"selected_text": "   "},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SELECTION"


def test_generate_does_not_fall_back_when_gemini_is_unavailable(monkeypatch):
    from ai import ai_client

    monkeypatch.setattr(humanizer_routes, "resolve_revelacode_user", _authenticate_user)
    monkeypatch.setattr(
        ai_client,
        "ask_gemini",
        lambda **_kwargs: {
            "success": False,
            "provider": "gemini",
            "error_code": "gemini_api_key_missing",
        },
    )
    response = client.post(
        "/api/humanizer/generate",
        headers={"Authorization": "Bearer test-token"},
        json={"selected_text": "Only this sentence.", "style": "natural"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GEMINI_UNAVAILABLE"
    assert "No alternate model was used" in response.json()["error"]["message"]


def test_generate_requires_authentication():
    response = client.post(
        "/api/humanizer/generate",
        json={"selected_text": "Only this sentence."},
    )
    assert response.status_code == 401
