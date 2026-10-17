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


if __name__ == "__main__":
    unittest.main()
