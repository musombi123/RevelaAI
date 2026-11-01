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
    assert result["fallback_model"] is None
    assert client.GEMINI_MODEL == "gemini-3.1-flash-lite"
    assert client.GEMINI_FALLBACK_MODEL == ""


def test_provider_status_exposes_hf_and_mvi_model_identity(monkeypatch):
    monkeypatch.setattr(client, "HF_TOKEN", "test-hf-token")
    monkeypatch.setattr(client, "HF_MODEL", "test-hf-model")
    monkeypatch.setattr(client, "HF_FALLBACK_MODEL", "test-hf-fallback")
    monkeypatch.setattr(client, "MVI_ENABLED", True)
    monkeypatch.setattr(client, "MVI_API_URL", "https://mvi.example/ask")
    monkeypatch.setattr(client, "MVI_API_KEY", "")

    status = client.get_text_provider_status()

    assert status["providers"]["huggingface"]["enabled"] is True
    assert status["providers"]["huggingface"]["primary_model"] == "test-hf-model"
    assert status["providers"]["mvi"]["enabled"] is True
    assert status["providers"]["mvi"]["model"] == "mvi-ai-engine"


def test_mvi_is_used_after_gemini_and_hf_fail(monkeypatch):
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["gemini", "hf", "mvi"])
    monkeypatch.setattr(
        client, "_provider_enabled",
        lambda name: name in {"gemini", "huggingface", "mvi"},
    )
    monkeypatch.setattr(
        client, "_ask_gemini_text",
        lambda **kwargs: (_ for _ in ()).throw(client.AIClientError(
            "Gemini test failure", provider="gemini", status_code=503,
            error_code="gemini_service_unavailable",
        )),
    )
    monkeypatch.setattr(
        client, "_ask_hf_text",
        lambda **kwargs: (_ for _ in ()).throw(client.AIClientError(
            "HF test failure", provider="huggingface", status_code=503,
            error_code="hf_service_unavailable",
        )),
    )
    monkeypatch.setattr(
        client, "_request_mvi",
        lambda **kwargs: {
            "success": True, "response": "MVI fallback answer",
            "provider": "mvi", "model": "mvi-ai-engine",
        },
    )

    result = client.ask_hf("Explain the fallback route.")

    assert result["success"] is True
    assert result["provider"] == "mvi"
    assert result["response"] == "MVI fallback answer"


def test_active_provider_prefers_gemini_to_legacy_order(monkeypatch):
    from services import runtime_config

    monkeypatch.setattr(runtime_config, "get_revelaai_text_status", lambda: {
        "provider_order": ["mvi", "hf", "gemini"],
        "providers": {
            "gemini": {"enabled": True, "primary_model": "gemini-test"},
            "huggingface": {"enabled": True, "primary_model": "hf-test"},
            "mvi": {"enabled": True, "model": "mvi-ai-engine"},
        },
    })

    assert runtime_config.get_active_text_provider() == "gemini"
    assert runtime_config.get_active_text_model() == "gemini-test"


def test_active_provider_resolves_hf_alias_to_canonical_status_key(monkeypatch):
    from services import runtime_config

    monkeypatch.setattr(runtime_config, "get_revelaai_text_status", lambda: {
        "provider_order": ["hf", "mvi"],
        "providers": {
            "huggingface": {"enabled": True, "primary_model": "hf-test"},
            "mvi": {"enabled": True, "model": "mvi-ai-engine"},
        },
    })

    assert runtime_config.get_active_text_provider() == "huggingface"
    assert runtime_config.get_active_text_model() == "hf-test"
