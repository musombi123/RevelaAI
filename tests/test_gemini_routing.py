"""Regression checks for Gemini-first text generation and configured model fallback."""
import unittest
from unittest.mock import patch

from ai import ai_client


class GeminiRoutingTests(unittest.TestCase):
    def test_gemini_primary_then_gemini_fallback_model(self):
        fallback_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Fallback response"}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 12},
        }
        temporary_failure = ai_client.AIClientError(
            "temporary provider failure",
            provider="gemini",
            status_code=503,
            error_code="gemini_service_unavailable",
        )

        with (
            patch.object(ai_client, "GEMINI_ENABLED", True),
            patch.object(ai_client, "GEMINI_API_KEY", "test-only-key"),
            patch.object(ai_client, "GEMINI_MODEL", "gemini-primary-test"),
            patch.object(ai_client, "GEMINI_FALLBACK_MODEL", "gemini-fallback-test"),
            patch.object(
                ai_client,
                "_request_gemini",
                side_effect=[temporary_failure, fallback_response],
            ) as request,
        ):
            result = ai_client._ask_gemini_text(
                text="Help me plan my project",
                system_prompt="Be helpful",
                session_id="test-session",
                context=[],
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["provider"], "gemini")
        self.assertEqual(result["model"], "gemini-fallback-test")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(
            [call.kwargs["model"] for call in request.call_args_list],
            ["gemini-primary-test", "gemini-fallback-test"],
        )

    def test_gemini_is_first_configured_text_provider_by_default(self):
        # This CI test runs without production environment variables.
        self.assertEqual(ai_client.TEXT_PROVIDER_ORDER[0], "gemini")

    def test_known_mvi_rule_engine_answer_is_rejected(self):
        fallback = (
            "This is a transparent on-device rule engine rather than "
            "a generative language model, so I won't invent detailed facts."
        )
        self.assertTrue(ai_client._is_non_generative_fallback(fallback))
        self.assertFalse(ai_client._is_non_generative_fallback(
            "I can help assess your security controls and incident response plan."
        ))

    def test_configured_gemini_precedes_mvi_even_if_env_lists_mvi_first(self):
        with (
            patch.object(ai_client, "TEXT_PROVIDER_ORDER", ["mvi", "gemini"]),
            patch.object(ai_client, "_provider_enabled", side_effect=lambda name: name == "gemini"),
            patch.object(
                ai_client,
                "_ask_gemini_text",
                return_value={"success": True, "response": "Generative answer", "provider": "gemini", "model": "test"},
            ) as ask_gemini,
            patch.object(ai_client, "_request_mvi") as ask_mvi,
        ):
            result = ai_client.ask_hf("What are your capabilities?")

        self.assertEqual(result["provider"], "gemini")
        ask_gemini.assert_called_once()
        ask_mvi.assert_not_called()


if __name__ == "__main__":
    unittest.main()
