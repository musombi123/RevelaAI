"""Dependency-free smoke tests for RevelaAI's local global brain."""
import unittest

from ai.living_brain import describe_vision, respond_local, route_hub


class LivingBrainTests(unittest.TestCase):
    def test_auto_routes_farming_to_mkulima(self):
        hub, reason = route_hub("My maize crop has yellow leaves after little rainfall")
        self.assertEqual(hub, "mkulima")
        self.assertTrue(reason)

    def test_explicit_hub_overrides_keyword_routing(self):
        hub, _ = route_hub("Help me negotiate a price for maize", "elimu")
        self.assertEqual(hub, "elimu")

    def test_business_request_routes_to_biashara(self):
        result = respond_local("How do I calculate profit margin for my business?")
        self.assertEqual(result["hub"], "biashara")
        self.assertFalse(result["networkUsed"])
        self.assertIn("contribution", result["reply"].lower())

    def test_unrecognized_domain_falls_back_to_general(self):
        result = respond_local("How do I improve this unknown workflow?")
        self.assertEqual(result["hub"], "general")
        self.assertIn("goal", result["reply"].lower())

    def test_vision_failure_returns_safe_chat_answer(self):
        result = describe_vision({}, "What is in this image?")
        self.assertTrue(result["fallback"])
        self.assertIn("chat is still available", result["reply"].lower())
        self.assertFalse(result["networkUsed"])

    def test_vision_measurements_are_reported_without_claiming_object_identity(self):
        result = describe_vision({"brightness": 120, "contrast": 80, "edgeActivity": 22})
        self.assertIn("120/255", result["reply"])
        self.assertIn("cannot identify objects", result["reply"].lower())


if __name__ == "__main__":
    unittest.main()
