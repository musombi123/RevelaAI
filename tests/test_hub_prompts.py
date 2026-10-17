import unittest
from ai.hub_prompts import HUB_PROMPTS, detect_hub, get_identity_answer, is_identity_question, normalize_hub, resolve_hub
from ai.global_brain_adapter import build_global_context


class HubPromptTests(unittest.TestCase):
    def test_six_hub_prompts_exist(self):
        self.assertEqual(set(HUB_PROMPTS), {"auto","mkulima","biashara","elimu","mahubiri","general"})
        self.assertTrue(all(HUB_PROMPTS.values()))

    def test_invalid_hub_defaults_to_auto(self):
        self.assertEqual(normalize_hub(None), "auto")
        self.assertEqual(normalize_hub("not-a-hub"), "auto")

    def test_auto_routes_swahili_maize_request_to_mkulima(self):
        self.assertEqual(resolve_hub("Nipandie mahindi", "auto"), ("mkulima", "auto"))

    def test_auto_routes_john_316_to_mahubiri(self):
        self.assertEqual(detect_hub("Explain John 3:16"), "mahubiri")
        self.assertEqual(resolve_hub("Explain John 3:16", "auto"), ("mahubiri", "auto"))

    def test_explicit_hub_wins(self):
        self.assertEqual(resolve_hub("Explain John 3:16", "biashara"), ("biashara", "biashara"))

    def test_identity_answers_are_hub_specific(self):
        self.assertTrue(is_identity_question("Who are you?"))
        expected = {
          "mkulima":"I'm RevelaAI - Mkulima Hub.",
          "biashara":"I'm RevelaAI - Biashara Hub.",
          "elimu":"I'm RevelaAI - Elimu Hub.",
          "mahubiri":"I'm RevelaAI - Mahubiri Hub.",
          "general":"I'm RevelaAI, your partner built by RevelaCode",
          "auto":"I'm RevelaAI - Auto Hub.",
        }
        for hub, opening in expected.items():
            self.assertIn(opening, get_identity_answer("Who are you?", hub))

    def test_auto_identity_uses_auto_prompt(self):
        context, meta = build_global_context("Who are you?", "auto")
        self.assertEqual(meta["hub"], "auto")
        self.assertIn("Auto Hub Intelligence", context["content"])

    def test_auto_routing_injects_specialist_and_tag(self):
        context, meta = build_global_context("Nipandie mahindi", "auto")
        self.assertEqual(meta["hub"], "mkulima")
        self.assertIn("Mkulima Hub Intelligence", context["content"])
        self.assertIn("[Auto → Mkulima]", context["content"])

    def test_bible_reference_gets_mahubiri_prompt(self):
        context, meta = build_global_context("Explain John 3:16", "auto")
        self.assertEqual(meta["hub"], "mahubiri")
        self.assertIn("Mahubiri Hub Intelligence", context["content"])
        self.assertIn("distinguish text from interpretation", context["content"])


if __name__ == "__main__":
    unittest.main()
