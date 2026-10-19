package assemble

import (
	"crypto/sha256"
	"encoding/hex"
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

	if item.Target != "esp32-sensor" ||
		item.Version != "1.0.0" ||
		item.ValidationStatus != "valid_curated_template" {
		t.Fatalf("unexpected template registry entry: %+v", item)
	}

	if item.BoardProfileID != "esp32-s3-generic" ||
		!item.ElectricalReviewRequired {
		t.Fatalf(
			"generic board profile must retain unresolved electrical review: %+v",
			item,
		)
	}

	if !item.HumanReviewRequired {
		t.Fatal("human review must be required for every curated template")
	}
}

func TestBoardProfileCatalogIsExplicitlyUnverified(t *testing.T) {
	profiles := ListBoardProfiles()

	if len(profiles) < 2 {
		t.Fatalf("expected reusable board profile references, got %d", len(profiles))
	}

	found := false

	for _, profile := range profiles {
		if profile.ID != "esp32-s3-generic" {
			continue
		}

		found = true

		if profile.LogicVoltageMV != 3300 ||
			profile.HardwareVerified ||
			profile.PinMapStatus != "exact_board_revision_required" {
			t.Fatalf(
				"generic ESP32-S3 profile must not imply hardware verification: %+v",
				profile,
			)
		}

		if strings.TrimSpace(profile.Notes) == "" {
			t.Fatal("unverified profile must explain its limitations")
		}
	}

	if !found {
		t.Fatal("ESP32-S3 generic reference profile missing")
	}
}

func TestElectricalCompatibilityRequiresEvidenceAndRejectsConflictingRanges(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	report := ValidateTemplate(template)

	if !report.Valid || !report.ElectricalReviewRequired {
		t.Fatalf(
			"missing exact breakout constraints must require review without claiming compatibility: %+v",
			report,
		)
	}

	template.Electrical = ElectricalRequirements{
		SupplyMinMV:                  1800,
		SupplyMaxMV:                  3300,
		LogicMinMV:                   1800,
		LogicMaxMV:                   3300,
		DatasheetReference:           "curated-test-datasheet",
		ManufacturerDatasheetReviewed: true,
	}

	report = ValidateTemplate(template)

	// The declared values are structurally consistent, but the registered
	// board profile is generic and has no verified board revision or pin map.
	if !report.Valid || !report.ElectricalReviewRequired {
		t.Fatalf(
			"generic unverified profile must retain electrical review even with declared ranges and datasheet metadata: %+v",
			report,
		)
	}

	template.Electrical.SupplyMaxMV = 3000
	report = ValidateTemplate(template)

	if report.Valid {
		t.Fatalf(
			"board nominal level outside declared supply limits must fail: %+v",
			report,
		)
	}

	if !report.ElectricalReviewRequired {
		t.Fatal("an invalid electrical design must not clear the review flag")
	}

	found := false

	for _, check := range report.Checks {
		if check.Name == "electrical_compatibility" &&
			check.Status == "failed" {
			found = true
			break
		}
	}

	if !found {
		t.Fatalf(
			"electrical incompatibility must be explicit in checks: %+v",
			report.Checks,
		)
	}
}

func TestElectricalReviewCannotBeClearedWithoutDatasheetEvidence(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.Electrical = ElectricalRequirements{
		SupplyMinMV:                  1800,
		SupplyMaxMV:                  3300,
		LogicMinMV:                   1800,
		LogicMaxMV:                   3300,
		ManufacturerDatasheetReviewed: true,
		// DatasheetReference intentionally omitted.
	}

	report := ValidateTemplate(template)

	if !report.Valid {
		t.Fatalf("missing evidence reference should require review, not invalidate structure: %+v", report)
	}

	if !report.ElectricalReviewRequired {
		t.Fatal("missing datasheet reference must retain electrical review")
	}
}

func TestTemplateValidationRejectsUnknownBoardProfile(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.BoardProfileID = "unknown-board"

	report := ValidateTemplate(template)

	if report.Valid {
		t.Fatalf("unknown board profile should fail validation: %+v", report)
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
		if check.Name == "bom_wiring_consistency" &&
			check.Status == "failed" {
			found = true
			break
		}
	}

	if !found {
		t.Fatalf(
			"BOM/wiring failure should be explicit: %+v",
			report.Checks,
		)
	}
}

func TestTemplateValidationRejectsConflictingPinAssignments(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.Connections = append([]Connection{}, template.Connections...)

	// Reuse the same controller pin for a different signal. Shared endpoints
	// are only allowed when they retain the same signal assignment.
	template.Connections[1].FromPin = template.Connections[0].FromPin

	report := ValidateTemplate(template)

	if report.Valid {
		t.Fatalf(
			"conflicting signal assignments to the same endpoint must fail: %+v",
			report,
		)
	}

	found := false

	for _, check := range report.Checks {
		if check.Name == "connections" && check.Status == "failed" {
			found = true
			break
		}
	}

	if !found {
		t.Fatalf("connection failure must be explained in checks: %+v", report.Checks)
	}
}

func TestTemplateValidationRejectsInvalidWireColor(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.Connections = append([]Connection{}, template.Connections...)
	template.Connections[0].WireColor = "red"

	report := ValidateTemplate(template)

	if report.Valid {
		t.Fatal("wire color must use the expected #RRGGBB representation")
	}
}

func TestTemplateValidationRequiresReviewOnlyPolicy(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.ReviewOnly = false

	report := ValidateTemplate(template)

	if report.Valid {
		t.Fatal("a template that is not review-only must be rejected")
	}
}

func TestResolveTemplateReturnsDefensiveCopies(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.Parts[0].Name = "mutated test value"
	template.Connections[0].Signal = "mutated signal"
	template.SafetyNotes[0] = "mutated safety note"

	again, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture disappeared from registry")
	}

	if again.Parts[0].Name == "mutated test value" {
		t.Fatal("mutating returned parts modified the template registry")
	}

	if again.Connections[0].Signal == "mutated signal" {
		t.Fatal("mutating returned connections modified the template registry")
	}

	if again.SafetyNotes[0] == "mutated safety note" {
		t.Fatal("mutating returned safety notes modified the template registry")
	}
}

func TestRegisteredFixtureProducesVersionedReviewArtifacts(t *testing.T) {
	dir := t.TempDir()

	result, err := Generate("esp32-sensor", dir)
	if err != nil {
		t.Fatalf("generate curated artifacts: %v", err)
	}

	if result.Status != "artifacts_generated_pending_review" ||
		!result.HumanReviewRequired ||
		len(result.Artifacts) != 6 {
		t.Fatalf("unexpected generation result: %#v", result)
	}

	if result.TemplateID != "esp32-sensor" ||
		result.TemplateVersion != "1.0.0" ||
		!result.Validation.Valid {
		t.Fatalf("template provenance or validation missing: %#v", result)
	}

	if result.BoardProfileID != "esp32-s3-generic" ||
		!result.Validation.ElectricalReviewRequired {
		t.Fatalf(
			"generation must preserve unresolved electrical review and board profile: %#v",
			result,
		)
	}

	if len(result.Parts) != 5 || len(result.Connections) != 4 {
		t.Fatalf(
			"registry data not returned consistently: parts=%d connections=%d",
			len(result.Parts),
			len(result.Connections),
		)
	}

	expectedFiles := []string{
		"bom.txt",
		"wiring.svg",
		"mount_plate.stl",
		"flash.sh",
		"README.md",
		"template.json",
	}

	for _, name := range expectedFiles {
		body, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatalf("read generated artifact %s: %v", name, err)
		}

		if len(strings.TrimSpace(string(body))) == 0 {
			t.Fatalf("artifact %s is empty", name)
		}
	}

	bom := readGeneratedFile(t, dir, "bom.txt")
	wiring := readGeneratedFile(t, dir, "wiring.svg")
	manifest := readGeneratedFile(t, dir, "template.json")

	if !strings.Contains(bom, "4x 3.3V-compatible jumper wires") {
		t.Fatalf("BOM should be registry-derived: %s", bom)
	}

	if !strings.Contains(wiring, "I2C SDA (example)") ||
		!strings.Contains(wiring, "GPIO 8 (example SDA)") {
		t.Fatalf("wiring SVG should contain connection metadata: %s", wiring)
	}

	if strings.Count(wiring, "<path ") != len(result.Connections) {
		t.Fatalf(
			"SVG should render one connection path per connection: got %d, expected %d",
			strings.Count(wiring, "<path "),
			len(result.Connections),
		)
	}

	var metadata map[string]any
	if err := json.Unmarshal([]byte(manifest), &metadata); err != nil {
		t.Fatalf("decode manifest: %v", err)
	}

	if metadata["schema_version"] != manifestSchemaVersion {
		t.Fatalf("unexpected schema version: %+v", metadata["schema_version"])
	}

	if metadata["template_version"] != "1.0.0" ||
		metadata["hardware_verified"] != false ||
		metadata["generated_executable_code"] != false {
		t.Fatalf("unsafe or missing manifest provenance: %+v", metadata)
	}

	if metadata["board_profile_id"] != "esp32-s3-generic" ||
		metadata["electrical_review_required"] != true {
		t.Fatalf(
			"manifest must record unresolved electrical review and board profile: %+v",
			metadata,
		)
	}

	profile := metadata["template_sha256"]
	if !isSHA256Hex(profile) {
		t.Fatalf("template SHA-256 digest missing or malformed: %#v", profile)
	}

	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	templateJSON, err := json.MarshalIndent(template, "", "  ")
	if err != nil {
		t.Fatalf("marshal expected template: %v", err)
	}

	if expected := testSHA256(templateJSON); profile != expected {
		t.Fatalf("template digest mismatch: got %v, want %s", profile, expected)
	}

	checksumValue, ok := metadata["artifact_checksums_sha256"]
	if !ok {
		t.Fatal("manifest missing artifact checksums")
	}

	checksums, ok := checksumValue.(map[string]any)
	if !ok {
		t.Fatalf("artifact checksums have unexpected type: %T", checksumValue)
	}

	for _, name := range expectedFiles {
		// The manifest cannot include its own digest without a different
		// manifest-signing or detached-checksum design.
		if name == "template.json" {
			continue
		}

		checksum, ok := checksums[name].(string)
		if !ok || !isSHA256Hex(checksum) {
			t.Fatalf("missing or invalid checksum for %s: %#v", name, checksums[name])
		}

		body := readGeneratedFile(t, dir, name)
		if expected := testSHA256([]byte(body)); checksum != expected {
			t.Fatalf(
				"artifact checksum mismatch for %s: got %s, want %s",
				name,
				checksum,
				expected,
			)
		}
	}

	script := readGeneratedFile(t, dir, "flash.sh")

	for _, forbidden := range []string{
		"arduino-cli upload",
		"esptool.py write_flash",
		"openocd -f",
	} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("non-executing flash stub contains command %q", forbidden)
		}
	}

	if !strings.Contains(script, "does not call a flashing command") &&
		!strings.Contains(script, "does not call a flashing") &&
		!strings.Contains(script, "does not call a flashing tool") {
		// The generated script should clearly disclose its non-executing role.
		if !strings.Contains(script, "does not call a flashing command") {
			t.Fatalf("flash stub should explicitly state its limitations: %s", script)
		}
	}
}

func TestUnknownTargetOrVersionDoesNotInventDesign(t *testing.T) {
	cases := []struct {
		target  string
		version string
	}{
		{"unknown-robot", ""},
		{"esp32-sensor", "9.9.9"},
	}

	for _, tc := range cases {
		tc := tc

		t.Run(tc.target+"_"+tc.version, func(t *testing.T) {
			dir := t.TempDir()

			_, err := GenerateVersion(tc.target, tc.version, dir)
			if err == nil {
				t.Fatalf(
					"unsupported target/version should require a curated template: %+v",
					tc,
				)
			}

			entries, err := os.ReadDir(dir)
			if err != nil {
				t.Fatalf("read output directory: %v", err)
			}

			if len(entries) != 0 {
				t.Fatalf(
					"unsupported target should not create artifacts: %+v",
					entries,
				)
			}
		})
	}
}

func TestGenerateRejectsInvalidTargetAndVersion(t *testing.T) {
	cases := []struct {
		target  string
		version string
	}{
		{"../esp32-sensor", ""},
		{"esp32-sensor/../../other", ""},
		{"esp32-sensor", "1.0"},
		{"esp32-sensor", "01.0.0"},
		{"esp32-sensor", "1.0.0\n"},
	}

	for _, tc := range cases {
		dir := t.TempDir()

		if _, err := GenerateVersion(tc.target, tc.version, dir); err == nil {
			t.Fatalf("expected invalid target/version to be rejected: %+v", tc)
		}

		entries, err := os.ReadDir(dir)
		if err != nil {
			t.Fatalf("read output directory: %v", err)
		}

		if len(entries) != 0 {
			t.Fatalf("invalid request created artifacts: %+v", entries)
		}
	}
}

func TestGenerateDoesNotOverwriteExistingArtifact(t *testing.T) {
	dir := t.TempDir()
	const original = "keep this file"

	if err := os.WriteFile(
		filepath.Join(dir, "bom.txt"),
		[]byte(original),
		0600,
	); err != nil {
		t.Fatal(err)
	}

	if _, err := Generate("esp32-sensor", dir); err == nil {
		t.Fatal("existing output paths must not be overwritten")
	}

	body := readGeneratedFile(t, dir, "bom.txt")
	if body != original {
		t.Fatalf("existing file was changed: %q", body)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}

	if len(entries) != 1 {
		t.Fatalf("unexpected artifacts were left behind: %+v", entries)
	}
}

func TestGenerateCleansUpNewArtifactsWhenLaterPathExists(t *testing.T) {
	dir := t.TempDir()

	const original = "preserve existing wiring"
	if err := os.WriteFile(
		filepath.Join(dir, "wiring.svg"),
		[]byte(original),
		0600,
	); err != nil {
		t.Fatal(err)
	}

	if _, err := Generate("esp32-sensor", dir); err == nil {
		t.Fatal("generation should fail when a later artifact already exists")
	}

	body := readGeneratedFile(t, dir, "wiring.svg")
	if body != original {
		t.Fatalf("existing wiring artifact was changed: %q", body)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}

	if len(entries) != 1 || entries[0].Name() != "wiring.svg" {
		t.Fatalf(
			"newly created earlier artifacts should be cleaned up after failure: %+v",
			entries,
		)
	}
}

func TestWiringSVGEscapesUntrustedText(t *testing.T) {
	template, ok := resolveTemplate("esp32-sensor", "1.0.0")
	if !ok {
		t.Fatal("fixture missing from registry")
	}

	template.Title = `<script>alert("title")</script>`
	template.Parts = append([]Part{}, template.Parts...)
	template.Connections = append([]Connection{}, template.Connections...)

	template.Parts[0].Name = `<img src=x onerror="alert(1)">`
	template.Connections[0].Signal = `<script>alert("signal")</script>`
	template.Connections[0].Notes = `<svg onload="alert(1)">`

	svg := renderWiringSVG(template)

	if strings.Contains(svg, `<script>alert`) {
		t.Fatalf("SVG contains unescaped script markup: %s", svg)
	}

	if strings.Contains(svg, `<img src=x`) {
		t.Fatalf("SVG contains unescaped image markup: %s", svg)
	}

	if !strings.Contains(svg, "&lt;script&gt;") {
		t.Fatalf("expected title and signal markup to be escaped: %s", svg)
	}
}

func TestCompareVersionUsesNumericSemantics(t *testing.T) {
	cases := []struct {
		a    string
		b    string
		want int
	}{
		{"1.0.0", "1.0.0", 0},
		{"1.10.0", "1.9.9", 1},
		{"2.0.0", "1.99.99", 1},
		{"1.2.3", "1.2.4", -1},
		{"10.0.0", "9.99.99", 1},
		{"999999999999999999999.0.0", "2.0.0", 1},
	}

	for _, tc := range cases {
		got := compareVersion(tc.a, tc.b)

		// Normalize results to -1, 0, or 1 so the test checks ordering,
		// not a particular integer magnitude.
		if got < 0 {
			got = -1
		} else if got > 0 {
			got = 1
		}

		if got != tc.want {
			t.Errorf(
				"compareVersion(%q, %q) = %d, want %d",
				tc.a,
				tc.b,
				got,
				tc.want,
			)
		}
	}
}

func TestGeneratedArtifactsRemainReviewOnly(t *testing.T) {
	dir := t.TempDir()

	result, err := Generate("esp32-sensor", dir)
	if err != nil {
		t.Fatalf("generate artifacts: %v", err)
	}

	if !result.HumanReviewRequired {
		t.Fatal("generated artifacts must require human review")
	}

	if result.Status != "artifacts_generated_pending_review" {
		t.Fatalf("unexpected status: %q", result.Status)
	}

	manifest := readGeneratedFile(t, dir, "template.json")
	var metadata map[string]any

	if err := json.Unmarshal([]byte(manifest), &metadata); err != nil {
		t.Fatalf("decode manifest: %v", err)
	}

	if metadata["hardware_verified"] != false {
		t.Fatal("generated manifest must not claim hardware verification")
	}

	if metadata["generated_executable_code"] != false {
		t.Fatal("generated manifest must not claim executable code generation")
	}

	if metadata["cost"] != "unverified; local supplier quote required" {
		t.Fatalf("unexpected cost statement: %#v", metadata["cost"])
	}
}

func readGeneratedFile(t *testing.T, dir, name string) string {
	t.Helper()

	body, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		t.Fatalf("read generated file %s: %v", name, err)
	}

	return string(body)
}

func testSHA256(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}

func isSHA256Hex(value any) bool {
	text, ok := value.(string)
	if !ok || len(text) != 64 {
		return false
	}

	decoded, err := hex.DecodeString(text)
	return err == nil && len(decoded) == sha256.Size
}
