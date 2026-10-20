from __future__ import annotations

import ai.ai_client as client


def test_gemini_list_models_selects_first_available_configured_model(monkeypatch):
    class FakeResponse:
        ok = True
        status_code = 200

        def json(self):
            return {
                "models": [
                    {
                        "name": "models/gemini-3.1-flash-lite",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ]
            }

    monkeypatch.setattr(client, "GEMINI_ENABLED", True)
    monkeypatch.setattr(client, "GEMINI_MODEL_VALIDATION", {})
    monkeypatch.setattr(client, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(client, "GEMINI_MODEL", "gemini-retired-test-model")
    monkeypatch.setattr(client, "GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setattr(client.requests, "get", lambda *args, **kwargs: FakeResponse())

    result = client.validate_gemini_models()

    assert result["reachable"] is True
    assert result["model_valid"] is True
    assert result["selected_model"] == "gemini-3.1-flash-lite"
    assert client.GEMINI_MODEL == "gemini-3.1-flash-lite"
