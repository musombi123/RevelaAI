import unittest

from ai.global_brain_adapter import (
    build_global_context,
    detect_capabilities,
    infer_interaction_tone,
    normalize_hub,
)


class GlobalBrainAdapterTests(unittest.TestCase):
    def test_hub_aliases_are_canonical(self):
        self.assertEqual(normalize_hub("Shamba"), "mkulima")
        self.assertEqual(normalize_hub("Teacher"), "elimu")
        self.assertEqual(normalize_hub("Bible"), "mahubiri")
        self.assertEqual(normalize_hub("unknown"), "auto")
        self.assertEqual(normalize_hub("Auto"), "auto")

    def test_tone_adapts_without_claiming_emotion_detection(self):
        self.assertEqual(infer_interaction_tone("This is broken again"), "frustrated")
        self.assertEqual(infer_interaction_tone("I feel overwhelmed"), "distressed")
        self.assertEqual(infer_interaction_tone("Why does this happen?"), "curious")

    def test_vision_context_reaches_existing_text_adapter(self):
        context, meta = build_global_context(
            "What do you see?",
            "general",
            {"visionDescription": {"objects": ["book"], "text": "ROMANS 8:28"}},
        )
        self.assertIn("ROMANS 8:28", context["content"])
        self.assertIn("vision_context", meta["capabilities"])

    def test_existing_image_router_is_signalled_not_replaced(self):
        capabilities = detect_capabilities("Create an image of a coastal farm")
        self.assertIn("existing_image_router", capabilities)


if __name__ == "__main__":
    unittest.main()
