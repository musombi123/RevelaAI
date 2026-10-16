import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import hub_personas


class HubPersonaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory_patch = patch.object(hub_personas, "MEMORY_FILE", Path(self.temp.name) / "hub_memory.json")
        self.memory_patch.start()
        hub_personas.CACHE.clear()

    def tearDown(self):
        self.memory_patch.stop()
        self.temp.cleanup()
        hub_personas.CACHE.clear()

    def test_hub_aliases_and_farming_persona(self):
        result = hub_personas.respond("My tomato leaves are yellow", "shamba", "test-user")
        self.assertEqual(result["hub"], "mkulima")
        self.assertIn("crop", result["reply"].lower())
        self.assertFalse(result["paidModel"])

    def test_camera_description_is_handled_without_model(self):
        result = hub_personas.respond(
            "What do you see?",
            "general",
            "test-user",
            vision={"objects": [{"class": "book", "score": 0.9}], "brightness": 42, "contourCount": 7, "text": "ROMANS 8:28"},
        )
        self.assertTrue(result["visionUsed"])
        self.assertIn("book", result["reply"].lower())
        self.assertIn("ROMANS 8:28", result["reply"])
        self.assertIn("dark", result["reply"].lower())

    def test_explicit_follow_up_uses_recent_hub_memory(self):
        hub_personas.respond("How do I price this?", "biashara", "session-1")
        follow_up = hub_personas.respond("continue", "biashara", "session-1")
        self.assertIn("How do I price this?", follow_up["reply"])

    def test_memory_is_scoped_by_user_and_hub(self):
        hub_personas.respond("How do I price this?", "biashara", "user-a")
        self.assertTrue((Path(self.temp.name) / "hub_memory.json").exists())
        data = hub_personas._load_memory()
        self.assertEqual(len(data), 1)
        self.assertNotIn("user-a", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
