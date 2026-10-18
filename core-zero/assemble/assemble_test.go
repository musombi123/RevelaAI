package assemble

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRegistryListsOnlyValidatedVersionedTemplates(t *testing.T) {
	items := ListTemplates()
	if len(items) != 1 {
		t.Fatalf("expected one curated template, got %d", len(items))
	}
	item := items[0]
	if item.Target != "esp32-sensor" || item.Version != "1.0.0" || item.ValidationStatus != "valid_curated_template" {
		t.Fatalf("unexpected template registry entry: %+v", item)
	}
}

func TestTemplateValidationRejectsBOMWiringMismatch(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}
	template.Parts = append([]Part{}, template.Parts...)
	for i := range template.Parts {
		if template.Parts[i].ID == template.WiringPartID {
			template.Parts[i].Quantity = 2
		}
	}
	report := ValidateTemplate(template)
	if report.Valid || report.Status != "invalid_template" {
		t.Fatalf("BOM with too few wires should fail validation: %+v", report)
	}
	found := false
	for _, check := range report.Checks {
		if check.Name == "bom_wiring_consistency" && check.Status == "failed" {
			found = true
		}
	}
	if !found {
		t.Fatalf("BOM/wiring failure should be explicit: %+v", report.Checks)
	}
}

func TestTemplateValidationRejectsDuplicatePinEndpoints(t *testing.T) {
	template, _ := resolveTemplate("esp32-sensor", "1.0.0")
	template.Connections = append([]Connection{}, template.Connections...)
	template.Connections[1].FromPin = template.Connections[0].FromPin
	report := ValidateTemplate(template)
	if report.Valid {
		t.Fatal("duplicate pin endpoint should fail validation")
	}
}

func TestRegisteredFixtureProducesVersionedReviewArtifacts(t *testing.T) {
	d := t.TempDir()
	r, err := Generate("esp32-sensor", d)
	if err != nil {
		t.Fatal(err)
	}
	if r.Status != "artifacts_generated_pending_review" || !r.HumanReviewRequired || len(r.Artifacts) != 6 {
		t.Fatalf("bad result: %#v", r)
	}
	if r.TemplateID != "esp32-sensor" || r.TemplateVersion != "1.0.0" || !r.Validation.Valid {
		t.Fatalf("template provenance or validation missing: %#v", r)
	}
	if len(r.Parts) != 5 || len(r.Connections) != 4 {
		t.Fatalf("registry data not returned consistently: parts=%d connections=%d", len(r.Parts), len(r.Connections))
	}
	for _, name := range []string{"bom.txt", "wiring.svg", "mount_plate.stl", "flash.sh", "README.md", "template.json"} {
		body, err := os.ReadFile(filepath.Join(d, name))
		if err != nil {
			t.Fatal(err)
		}
		if len(strings.TrimSpace(string(body))) == 0 {
			t.Fatalf("%s empty", name)
		}
	}
	bom, _ := os.ReadFile(filepath.Join(d, "bom.txt"))
	wiring, _ := os.ReadFile(filepath.Join(d, "wiring.svg"))
	manifest, _ := os.ReadFile(filepath.Join(d, "template.json"))
	if !strings.Contains(string(bom), "4x 3.3V-compatible jumper wires") {
		t.Fatalf("BOM should be registry-derived: %s", bom)
	}
	if !strings.Contains(string(wiring), "I2C SDA (example)") || !strings.Contains(string(wiring), "GPIO 8 (example SDA)") {
		t.Fatalf("wiring SVG should contain validated connection metadata: %s", wiring)
	}
	var metadata map[string]any
	if err := json.Unmarshal(manifest, &metadata); err != nil {
		t.Fatal(err)
	}
	if metadata["template_version"] != "1.0.0" || metadata["hardware_verified"] != false || metadata["generated_executable_code"] != false {
		t.Fatalf("unsafe or missing manifest provenance: %+v", metadata)
	}
	script, _ := os.ReadFile(filepath.Join(d, "flash.sh"))
	if strings.Contains(string(script), "arduino-cli upload") || strings.Contains(string(script), "esptool.py write_flash") {
		t.Fatal("stub must not flash hardware")
	}
}

func TestUnknownTargetOrVersionDoesNotInventDesign(t *testing.T) {
	for _, tc := range []struct{ target, version string }{
		{"unknown-robot", ""},
		{"esp32-sensor", "9.9.9"},
	} {
		dir := t.TempDir()
		if _, err := GenerateVersion(tc.target, tc.version, dir); err == nil {
			t.Fatalf("unsupported target/version should require a curated template: %+v", tc)
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			t.Fatal(err)
		}
		if len(entries) != 0 {
			t.Fatalf("unsupported target should not create artifacts: %+v", entries)
		}
	}
}

func TestGenerateDoesNotOverwriteExistingArtifact(t *testing.T) {
	dir := t.TempDir()
	const original = "keep this file"
	if err := os.WriteFile(filepath.Join(dir, "bom.txt"), []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Generate("esp32-sensor", dir); err == nil {
		t.Fatal("existing output paths must not be overwritten")
	}
	body, err := os.ReadFile(filepath.Join(dir, "bom.txt"))
	if err != nil || string(body) != original {
		t.Fatalf("existing file was changed: %q %v", body, err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("partially generated files were not cleaned up: %+v", entries)
	}
}
