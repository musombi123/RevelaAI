import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revela_fieldkit import cli


class FieldKitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.case_root = self.root / "cases"
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "hello.txt").write_text("hello forensic world\n", encoding="utf-8")
        (self.source / "sample.pdf").write_bytes(b"%PDF-1.7\nnot a real PDF\n")

    def tearDown(self):
        self.temp.cleanup()

    def create_case(self):
        result = cli.create_case(self.case_root, "CASE-001", "Test case", "test-operator")
        return Path(result["case_directory"])

    def test_create_case_builds_case_and_custody_log(self):
        case_dir = self.create_case()
        self.assertTrue((case_dir / "case.json").is_file())
        self.assertTrue((case_dir / "chain_of_custody.jsonl").is_file())
        self.assertTrue((case_dir / "evidence").is_dir())
        self.assertTrue((case_dir / "reports").is_dir())

    def test_case_id_cannot_escape_case_root(self):
        with self.assertRaises(ValueError):
            cli.create_case(self.case_root, "../escape", "bad", "tester")

    def test_inventory_and_verify_directory(self):
        case_dir = self.create_case()
        result = cli.inventory_source(case_dir, self.source, "tester", False)
        self.assertEqual(result["items_hashed"], 2)
        verified = cli.verify_manifest(case_dir, "tester")
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["failed"], 0)

    def test_inventory_and_verify_single_file(self):
        case_dir = self.create_case()
        source_file = self.source / "hello.txt"
        result = cli.inventory_source(case_dir, source_file, "tester", False)
        self.assertEqual(result["items_hashed"], 1)
        verified = cli.verify_manifest(case_dir, "tester")
        self.assertEqual(verified["status"], "verified")

    def test_verify_detects_modified_source_file(self):
        case_dir = self.create_case()
        cli.inventory_source(case_dir, self.source, "tester", False)
        (self.source / "hello.txt").write_text("changed content\n", encoding="utf-8")
        result = cli.verify_manifest(case_dir, "tester")
        self.assertEqual(result["status"], "mismatch_or_unavailable")
        self.assertGreater(result["failed"], 0)

    def test_inventory_detects_pdf_signature(self):
        case_dir = self.create_case()
        cli.inventory_source(case_dir, self.source, "tester", False)
        manifest = json.loads((case_dir / "evidence_manifest.json").read_text(encoding="utf-8"))
        row = next(x for x in manifest["items"] if x["relative_path"] == "sample.pdf")
        self.assertEqual(row["signature"], "PDF document")

    def test_secret_scan_redacts_hidden_env_file(self):
        secret = "ghp_" + "A" * 40
        (self.source / ".env").write_text(f"GITHUB_TOKEN={secret}\n", encoding="utf-8")
        result = cli.scan_secrets(self.source, include_hidden=False)
        encoded = json.dumps(result)
        self.assertIn("[REDACTED]", encoded)
        self.assertNotIn(secret, encoded)
        self.assertEqual(result["findings_count"], 1)

    def test_credential_assignment_detector_redacts(self):
        secret = "sensitive-example-password-123"
        (self.source / "config.txt").write_text(f"password={secret}\n", encoding="utf-8")
        result = cli.scan_secrets(self.source, include_hidden=False)
        self.assertNotIn(secret, json.dumps(result))
        self.assertTrue(any(x["detector"] == "Credential-like assignment" for x in result["findings"]))

    def test_local_ollama_host_rejects_remote_endpoint(self):
        old = os.environ.get("OLLAMA_HOST")
        try:
            os.environ["OLLAMA_HOST"] = "http://example.com:11434"
            with self.assertRaises(ValueError):
                cli._ollama_endpoint()
        finally:
            if old is None:
                os.environ.pop("OLLAMA_HOST", None)
            else:
                os.environ["OLLAMA_HOST"] = old

    def test_local_ollama_endpoint_accepts_loopback(self):
        old = os.environ.get("OLLAMA_HOST")
        try:
            os.environ["OLLAMA_HOST"] = "http://127.0.0.1:11434"
            self.assertEqual(cli._ollama_endpoint(), "http://127.0.0.1:11434/api/generate")
        finally:
            if old is None:
                os.environ.pop("OLLAMA_HOST", None)
            else:
                os.environ["OLLAMA_HOST"] = old

    def test_knowledge_search_uses_bundled_notes(self):
        root = Path(__file__).resolve().parents[1] / "knowledge"
        result = cli.search_knowledge("evidence hash", root)
        self.assertGreaterEqual(len(result["matches"]), 1)

    def test_case_report_generation(self):
        case_dir = self.create_case()
        cli.inventory_source(case_dir, self.source, "tester", False)
        result = cli.create_report(case_dir, "tester")
        self.assertTrue(Path(result["report"]).is_file())
        self.assertEqual(result["evidence_records"], 2)


if __name__ == "__main__":
    unittest.main()
