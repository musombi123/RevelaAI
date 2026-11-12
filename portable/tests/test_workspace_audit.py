import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from revela_fieldkit.workspace_audit import audit_workspace, export_handoff_findings, discover_projects


class WorkspaceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "revela-project"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "src" / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
        (self.project / "src" / "routes.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n'
            '@app.get("/health")\ndef one(): return "ok"\n'
            '@app.get("/health")\ndef two(): return "again"\n',
            encoding="utf-8",
        )
        (self.project / "src" / "main.js").write_text(
            'import missing from "./missing.js";\nexport default missing;\n', encoding="utf-8"
        )
        (self.project / "index.html").write_text(
            '<html><script src="missing.js"></script></html>', encoding="utf-8"
        )
        (self.project / "package.json").write_text(
            json.dumps({"name": "fixture", "dependencies": {"left-pad": "1.0.0"}}),
            encoding="utf-8",
        )
        (self.project / "package-lock.json").write_text('{"packages":{}}', encoding="utf-8")
        (self.project / "render.yaml").write_text(
            "services:\n"
            "  - type: web\n"
            "    name: api\n"
            "  - type: web\n"
            "    name: frontend\n"
            "    envVars:\n"
            "      - key: API_URL\n"
            "        fromService:\n"
            "          type: web\n"
            "          name: missing-service\n"
            "          property: host\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_audit_detects_multiple_static_issue_classes(self):
        report = audit_workspace(self.project)
        rules = {finding["rule_id"] for finding in report["findings"]}
        self.assertEqual(report["schema_version"], "revelaai.workspace-audit.v1")
        self.assertIn("PY-SYNTAX", rules)
        self.assertIn("PY-DUPLICATE-ROUTE", rules)
        self.assertIn("JS-MISSING-LOCAL-IMPORT", rules)
        self.assertIn("HTML-MISSING-ASSET", rules)
        self.assertIn("NPM-LOCK-DRIFT", rules)
        self.assertIn("RENDER-MISSING-SERVICE", rules)
        self.assertFalse(report["safety"]["source_files_modified"])
        self.assertFalse(report["safety"]["project_commands_executed"])

    def test_audit_does_not_modify_source_files(self):
        before = {str(path): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        audit_workspace(self.project)
        after = {str(path): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_nested_projects_are_discovered(self):
        nested = self.project / "frontend"
        nested.mkdir()
        (nested / "package.json").write_text('{"name":"frontend"}', encoding="utf-8")
        found = discover_projects(self.root)
        resolved = {path.resolve() for path in found}
        self.assertIn(self.project.resolve(), resolved)
        self.assertIn(nested.resolve(), resolved)

    def test_secret_values_are_not_included_in_audit_report(self):
        secret = "ghp_" + "Z" * 40
        (self.project / "settings.py").write_text(f'API_TOKEN = "{secret}"\n', encoding="utf-8")
        report = audit_workspace(self.project)
        self.assertNotIn(secret, json.dumps(report))

    def test_handoff_export_uses_approved_finding_contract_shape(self):
        report = audit_workspace(self.project)
        out = self.root / "handoff"
        result = export_handoff_findings(report, out)
        self.assertEqual(result["count"], len(report["findings"]))
        row = json.loads((out / result["files"][0]).read_text(encoding="utf-8"))
        self.assertEqual(row["schema_version"], "1.0")
        self.assertEqual(row["source"], "revela-field-engine")
        self.assertEqual(row["scope"], "local")
        self.assertFalse(row["simulated"])

    def test_export_refuses_to_overwrite_existing_handoff_files(self):
        report = audit_workspace(self.project)
        out = self.root / "handoff"
        out.mkdir()
        (out / "existing.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            export_handoff_findings(report, out)


if __name__ == "__main__":
    unittest.main()
