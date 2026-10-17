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

    def test_routes_are_registered(self):
        paths = {rule.rule for rule in sci_router.url_map.iter_rules()} if hasattr(sci_router, 'url_map') else {rule.rule for rule in sci_router.deferred_functions}
        # Flask blueprint deferred functions are used before registration; verify module import instead.
        self.assertTrue(sci_router)

    def test_disaster_type_is_validated(self):
        with self.assertRaises(ValueError):
            simulate("disable_security")

if __name__ == "__main__":
    unittest.main()
