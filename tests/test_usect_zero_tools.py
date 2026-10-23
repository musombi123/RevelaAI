"""Regression tests for the USECT-ZERO scoped brain credential contract."""
import os
import unittest
from unittest.mock import patch

import ai.usect_zero_tools as zero_tools
from services.usect_zero_client import CoreReply


class USECTZeroCredentialTests(unittest.TestCase):
    @patch("ai.usect_zero_tools.is_enabled", return_value=True)
    @patch("ai.usect_zero_tools.request_core")
    def test_render_blueprint_api_key_name_is_supported(self, request_core, _enabled):
        request_core.return_value = CoreReply(
            status_code=200,
            payload={"status": "ok", "write_ready": True},
        )
        with patch.dict(
            os.environ,
            {"USECT_ZERO_BRAIN_API_KEY": "test-scoped-key"},
            clear=True,
        ):
            result = zero_tools.execute_tool("diagnostics", {})

        self.assertEqual(result["status"], "success")
        self.assertEqual(request_core.call_args.kwargs["api_key"], "test-scoped-key")
        self.assertFalse(request_core.call_args.kwargs["admin"])

    @patch("ai.usect_zero_tools.is_enabled", return_value=True)
    @patch("ai.usect_zero_tools.request_core")
    def test_legacy_brain_token_alias_remains_supported(self, request_core, _enabled):
        request_core.return_value = CoreReply(
            status_code=200,
            payload={"status": "ok"},
        )
        with patch.dict(
            os.environ,
            {"USECT_ZERO_BRAIN_TOKEN": "legacy-scoped-key"},
            clear=True,
        ):
            result = zero_tools.execute_tool("diagnostics", {})

        self.assertEqual(result["status"], "success")
        self.assertEqual(request_core.call_args.kwargs["api_key"], "legacy-scoped-key")
        self.assertFalse(request_core.call_args.kwargs["admin"])

    @patch("ai.usect_zero_tools.is_enabled", return_value=True)
    @patch("ai.usect_zero_tools.request_core")
    def test_missing_scoped_key_fails_closed(self, request_core, _enabled):
        with patch.dict(os.environ, {}, clear=True):
            result = zero_tools.execute_tool("diagnostics", {})

        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["executed"])
        self.assertEqual(result["error_code"], "usect_zero_brain_token_missing")
        request_core.assert_not_called()


if __name__ == "__main__":
    unittest.main()
