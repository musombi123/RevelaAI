import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from revela_fieldkit.repair import apply_repair_plan, rollback_repair


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.target = self.root / "src" / "settings.py"
        self.target.parent.mkdir()
        self.original = b"FEATURE_ENABLED = False\n"
        self.replacement = b"FEATURE_ENABLED = True\n"
        self.target.write_bytes(self.original)
        self.backups = self.base / "backups"
        self.plan = self.base / "repair-plan.json"
        self.plan.write_text(json.dumps({
            "schema_version": "revelaai.repair-plan.v1",
            "id": "enable-feature-reviewed",
            "changes": [{
                "path": "src/settings.py",
                "expected_sha256": __import__("hashlib").sha256(self.original).hexdigest(),
                "new_content_base64": base64.b64encode(self.replacement).decode("ascii"),
                "reason": "Operator-reviewed configuration change",
            }],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_repair_requires_two_explicit_approvals(self):
        with self.assertRaises(ValueError):
            apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=False)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_apply_creates_backup_and_rollback_restores_original(self):
        result = apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.target.read_bytes(), self.replacement)
        self.assertTrue(Path(result["transaction"]).is_file())
        rolled = rollback_repair(Path(result["transaction"]), authorized=True, approved=True)
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_hash_precondition_prevents_stale_repair(self):
        self.target.write_text("changed after plan\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)

    def test_path_traversal_and_sensitive_targets_are_rejected(self):
        payload = json.loads(self.plan.read_text(encoding="utf-8"))
        payload["changes"][0]["path"] = "../outside.py"
        self.plan.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)
        payload["changes"][0]["path"] = ".env"
        self.plan.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)


    def test_rollback_preflights_all_files_before_restoring_any(self):
        second = self.root / "src" / "second.py"
        second_original = b"VERSION = 1\n"
        second_replacement = b"VERSION = 2\n"
        second.write_bytes(second_original)
        payload = {
            "schema_version": "revelaai.repair-plan.v1",
            "id": "two-file-change",
            "changes": [
                {
                    "path": "src/settings.py",
                    "expected_sha256": __import__("hashlib").sha256(self.original).hexdigest(),
                    "new_content_base64": base64.b64encode(self.replacement).decode("ascii"),
                    "reason": "reviewed first change",
                },
                {
                    "path": "src/second.py",
                    "expected_sha256": __import__("hashlib").sha256(second_original).hexdigest(),
                    "new_content_base64": base64.b64encode(second_replacement).decode("ascii"),
                    "reason": "reviewed second change",
                },
            ],
        }
        self.plan.write_text(json.dumps(payload), encoding="utf-8")
        result = apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)
        self.assertEqual(self.target.read_bytes(), self.replacement)
        self.assertEqual(second.read_bytes(), second_replacement)

        # A post-repair edit to the second target must block rollback of the first.
        second.write_bytes(b"operator changed this later\n")
        with self.assertRaises(ValueError):
            rollback_repair(Path(result["transaction"]), authorized=True, approved=True)
        self.assertEqual(self.target.read_bytes(), self.replacement)
        self.assertEqual(second.read_bytes(), b"operator changed this later\n")

    def test_rollback_refuses_to_overwrite_post_repair_changes(self):
        result = apply_repair_plan(self.root, self.plan, self.backups, authorized=True, approved=True)
        self.target.write_text("later operator edit\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            rollback_repair(Path(result["transaction"]), authorized=True, approved=True)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "later operator edit\n")


if __name__ == "__main__":
    unittest.main()
