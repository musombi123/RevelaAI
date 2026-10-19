"""Regression tests for native FastAPI Sci-Core controls and safe service logic."""
import unittest
from unittest.mock import patch

from fastapi.responses import JSONResponse
from werkzeug.exceptions import Forbidden

from asgi import app
from fastapi.testclient import TestClient
from fastapi_routes import sci_core as sci_routes
from revelai.sci_core.research_engine import is_offensive_query, _summarize
from revelai.sci_core.hardware_lab import build_prototype
from revelai.sci_core.disaster_manager import simulate


client = TestClient(app)


class SciCoreSafetyTests(unittest.TestCase):
    def test_offensive_query_is_blocked(self):
        with self.assertRaises(Forbidden):
            is_offensive_query("how to hack into a server")

    def test_civilian_research_query_allowed(self):
        self.assertFalse(is_offensive_query("ESP32 water pump automation"))

    def test_local_summary_is_bounded_and_nonempty(self):
        value = _summarize(
            "ESP32 sensors measure soil moisture. Soil moisture sensors support "
            "irrigation decisions. A controller can send readings over Wi-Fi."
        )
        self.assertTrue(value)
        self.assertLessEqual(len(value), 3500)

    def test_hardware_prototype_is_never_executed(self):
        fake_collection = type(
            "Collection",
            (),
            {"insert_one": lambda self, doc: None},
        )()
        with patch("revelai.sci_core.storage.collection", return_value=fake_collection):
            result = build_prototype(
                "electronics", "Build a soil moisture sensor for irrigation"
            )
        self.assertFalse(result["executed"])
        self.assertIn("firmware.cpp", result["artifacts"])
        self.assertIn("safety.md", result["artifacts"])

    def test_browser_cors_preflight_needs_no_bearer_token(self):
        with patch.object(sci_routes, "require_platform_admin") as admin_check:
            response = client.options(
                "/api/sci/shield/status",
                headers={
                    "Origin": "https://revelacode-frontend.onrender.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://revelacode-frontend.onrender.com",
        )
        self.assertIn(
            "authorization",
            (response.headers.get("Access-Control-Allow-Headers") or "").lower(),
        )
        admin_check.assert_not_called()

    def test_actual_sci_core_request_remains_admin_protected(self):
        with patch.object(
            sci_routes,
            "require_platform_admin",
            return_value=(
                None,
                JSONResponse(
                    {"status": "error", "code": "admin_required"},
                    status_code=403,
                ),
            ),
        ) as admin_check:
            response = client.get("/api/sci/shield/status")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "admin_required")
        admin_check.assert_called_once()

    def test_native_sci_core_routes_are_registered(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/api/sci/shield/status", paths)
        self.assertIn("/api/sci/shield/scan", paths)
        self.assertIn("/api/sci/research", paths)
        self.assertIn("/api/sci/disaster/simulate", paths)
        self.assertIn("/api/sci/lab/prototype", paths)

    def test_disaster_type_is_validated(self):
        with self.assertRaises(ValueError):
            simulate("disable_security")


if __name__ == "__main__":
    unittest.main()
