import unittest
from unittest.mock import patch
from werkzeug.exceptions import Forbidden

from revelai.sci_core.research_engine import is_offensive_query, _summarize
from revelai.sci_core.hardware_lab import build_prototype
from revelai.sci_core.disaster_manager import simulate
from revelai.routers.sci_core import sci_router

class SciCoreSafetyTests(unittest.TestCase):
    def test_offensive_query_is_blocked(self):
        with self.assertRaises(Forbidden):
            is_offensive_query("how to hack into a server")

    def test_civilian_research_query_allowed(self):
        self.assertFalse(is_offensive_query("ESP32 water pump automation"))

    def test_local_summary_is_bounded_and_nonempty(self):
        value = _summarize("ESP32 sensors measure soil moisture. Soil moisture sensors support irrigation decisions. A controller can send readings over Wi-Fi.")
        self.assertTrue(value)
        self.assertLessEqual(len(value), 3500)

    def test_hardware_prototype_is_never_executed(self):
        fake_collection = type("Collection", (), {"insert_one": lambda self, doc: None})()
        with patch("revelai.sci_core.hardware_lab.collection", return_value=fake_collection):
            result = build_prototype("electronics", "Build a soil moisture sensor for irrigation")
        self.assertFalse(result["executed"])
        self.assertIn("firmware.cpp", result["artifacts"])
        self.assertIn("safety.md", result["artifacts"])


    def test_browser_cors_preflight_is_allowed_without_bearer_token(self):
        from flask import Flask
        from unittest.mock import patch

        app = Flask("sci-core-preflight-test")
        app.register_blueprint(sci_router, url_prefix="/api/sci")
        client = app.test_client()

        # Browsers do not include Authorization in the OPTIONS preflight itself.
        # The real GET/POST must still be authorized after CORS negotiation.
        with patch("revelai.routers.sci_core._authenticated_admin") as admin_check:
            response = client.options(
                "/api/sci/shield/status",
                headers={
                    "Origin": "https://revelacode-frontend.onrender.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
        self.assertIn(response.status_code, (200, 204))
        admin_check.assert_not_called()

    def test_real_sci_core_request_still_calls_admin_gate(self):
        from flask import Flask, jsonify
        from unittest.mock import patch

        app = Flask("sci-core-auth-test")
        app.register_blueprint(sci_router, url_prefix="/api/sci")
        client = app.test_client()

        denied = (jsonify({"status": "error", "code": "admin_required"}), 403)
        with patch("revelai.routers.sci_core._authenticated_admin", return_value=(None, denied)) as admin_check:
            response = client.get("/api/sci/shield/status")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "admin_required")
        admin_check.assert_called_once()

    def test_routes_are_registered(self):
        self.assertGreater(len(sci_router.deferred_functions), 0)

    def test_disaster_type_is_validated(self):
        with self.assertRaises(ValueError):
            simulate("disable_security")

if __name__ == "__main__":
    unittest.main()
