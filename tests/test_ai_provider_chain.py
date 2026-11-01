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



def test_provider_order_normalizes_aliases_and_keeps_configured_gemini_first(monkeypatch):
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["mvi", "hf", "google", "mvi"])
    monkeypatch.setattr(client, "_provider_enabled", lambda provider: provider == "gemini")

    assert client.get_text_provider_order() == ["gemini", "mvi", "huggingface"]


def test_mvi_is_a_real_fallback_after_gemini_and_huggingface_fail(monkeypatch):
    failures = {
        "gemini": client.AIClientError(
            "Gemini temporarily unavailable",
            provider="gemini",
            status_code=503,
            error_code="gemini_service_unavailable",
        ),
        "hf": client.AIClientError(
            "Hugging Face temporarily unavailable",
            provider="huggingface",
            status_code=503,
            error_code="hf_service_unavailable",
        ),
    }
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["gemini", "hf", "mvi"])
    monkeypatch.setattr(client, "_provider_enabled", lambda _provider: True)
    monkeypatch.setattr(
        client,
        "_ask_gemini_text",
        lambda **_kwargs: (_ for _ in ()).throw(failures["gemini"]),
    )
    monkeypatch.setattr(
        client,
        "_ask_hf_text",
        lambda **_kwargs: (_ for _ in ()).throw(failures["hf"]),
    )
    observed = {}

    def fake_mvi(**kwargs):
        observed.update(kwargs)
        return {
            "success": True,
            "response": "MVI generative fallback answer",
            "provider": "mvi",
            "model": "mvi-ai-engine",
        }

    monkeypatch.setattr(client, "_request_mvi", fake_mvi)

    context = [{"role": "user", "content": "Earlier question"}]
    result = client.ask_hf(
        "Continue the task",
        system_prompt="Follow the brain's grounded instructions.",
        session_id="session-123",
        context=context,
    )

    assert result["success"] is True
    assert result["provider"] == "mvi"
    assert result["fallback_used"] is True
    assert result["providers_attempted"] == ["gemini", "huggingface", "mvi"]
    assert observed == {
        "text": "Continue the task",
        "system_prompt": "Follow the brain's grounded instructions.",
        "context": context,
        "session_id": "session-123",
    }


def test_mvi_can_be_primary_only_when_gemini_is_not_configured(monkeypatch):
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["mvi", "hf"])
    monkeypatch.setattr(client, "_provider_enabled", lambda provider: provider == "mvi")
    monkeypatch.setattr(
        client,
        "_request_mvi",
        lambda **_kwargs: {
            "success": True,
            "response": "MVI primary answer",
            "provider": "mvi",
            "model": "mvi-ai-engine",
        },
    )

    result = client.ask_hf("Explain the system")

    assert result["success"] is True
    assert result["provider"] == "mvi"
    assert result["fallback_used"] is False


def test_provider_status_has_model_labels_and_the_actual_dispatch_order(monkeypatch):
    monkeypatch.setattr(client, "TEXT_PROVIDER_ORDER", ["mvi", "hf", "google"])
    monkeypatch.setattr(client, "_provider_enabled", lambda _provider: True)
    monkeypatch.setattr(client, "GEMINI_MODEL", "gemini-primary")
    monkeypatch.setattr(client, "GEMINI_FALLBACK_MODEL", "gemini-secondary")
    monkeypatch.setattr(client, "HF_MODEL", "hf-text-model")
    monkeypatch.setattr(client, "HF_FALLBACK_MODEL", "hf-fallback")
    monkeypatch.setattr(client, "MVI_API_URL", "https://mvi.example.test/ask")

    status = client.get_text_provider_status()

    assert status["provider_order"] == ["gemini", "mvi", "huggingface"]
    assert status["providers"]["gemini"]["primary_model"] == "gemini-primary"
    assert status["providers"]["mvi"]["primary_model"] == "mvi-ai-engine"
    assert status["providers"]["huggingface"]["primary_model"] == "hf-text-model"
