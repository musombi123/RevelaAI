from __future__ import annotations

import ai.ai_client as client


def test_gemini_auth_failure_falls_through_to_groq(monkeypatch):
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["gemini", "groq"])
    monkeypatch.setattr(client, "_provider_enabled", lambda name: name in {"gemini", "groq"})

    def fail_gemini(**kwargs):
        raise client.AIClientError(
            "Gemini key rejected",
            provider="gemini",
            status_code=401,
            error_code="UNAUTHENTICATED",
        )

    monkeypatch.setattr(client, "_ask_gemini_text", fail_gemini)
    monkeypatch.setattr(
        client,
        "_ask_groq_text",
        lambda **kwargs: {
            "success": True,
            "response": "fallback-ok",
            "provider": "groq",
            "model": "test-model",
        },
    )

    result = client.ask_hf("hello")

    assert result["success"] is True
    assert result["response"] == "fallback-ok"
    assert result["provider"] == "groq"


def test_groq_http_auth_error_preserves_provider_code(monkeypatch):
    class FakeResponse:
        ok = False
        status_code = 401

        def json(self):
            return {"error": {"message": "invalid credential", "code": "invalid_api_key"}}

    monkeypatch.setattr(client, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(client.requests, "post", lambda *args, **kwargs: FakeResponse())

    try:
        client._request_groq(model="test-model", messages=[{"role": "user", "content": "hello"}])
    except client.AIClientError as exc:
        assert exc.status_code == 401
        assert exc.error_code == "invalid_api_key"
    else:
        raise AssertionError("Expected Groq authentication error")


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
