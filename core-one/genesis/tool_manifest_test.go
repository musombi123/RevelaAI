package genesis

import (
	"encoding/json"
	"strings"
	"testing"
)

func validManifestForTest() ToolManifest {
	return ToolManifest{
		SchemaVersion: ToolManifestSchemaVersion,
		Name: "safe_tool",
		Version: "1.0.0",
		Language: "go",
		Entrypoint: "code.go",
		InputSchema: json.RawMessage(runtimeToolInputSchemaJSON),
		OutputSchema: json.RawMessage(runtimeToolOutputSchemaJSON),
		RiskTier: 0,
		Permissions: ToolPermissions{},
		TimeoutMillis: 10000,
		MemoryBytes: 128 << 20,
	}
}

func TestManifestDerivesTierFromPermissions(t *testing.T) {
	m := validManifestForTest()
	m.Permissions.Network = true
	if err := ValidateToolManifest(m); err == nil || !strings.Contains(err.Error(), "derived permissions tier") {
		t.Fatalf("network permission with self-declared Tier 0 must be rejected; got %v", err)
	}
	m.RiskTier = 1
	if err := ValidateToolManifest(m); err != nil {
		t.Fatalf("network permission with Tier 1 should validate: %v", err)
	}
	m.Permissions.Hardware = true
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("hardware permission must require Tier 2")
	}
	m.RiskTier = 2
	if err := ValidateToolManifest(m); err != nil {
		t.Fatalf("hardware permission with Tier 2 should validate: %v", err)
	}
}

func TestManifestRejectsUnsafeEntrypointsAndSchemas(t *testing.T) {
	for _, entrypoint := range []string{"../outside.go", "/tmp/code.go", "folder/../code.go", "folder\\code.go"} {
		m := validManifestForTest()
		m.Entrypoint = entrypoint
		if err := ValidateToolManifest(m); err == nil {
			t.Errorf("expected entrypoint %q to be rejected", entrypoint)
		}
	}
	m := validManifestForTest()
	m.InputSchema = json.RawMessage(`{"type":"object","$ref":"https://example.invalid/schema.json"}`)
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("referenced schema must be rejected")
	}
}

func TestManifestRejectsSchemasUnsupportedByRuntimeABI(t *testing.T) {
	m := validManifestForTest()
	m.InputSchema = json.RawMessage(`{"type":"object","properties":{"arbitrary":{"type":"string"}},"additionalProperties":false}`)
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("input schema that the runtime cannot accept must be rejected")
	}
	m = validManifestForTest()
	m.OutputSchema = json.RawMessage(`{"type":"object","properties":{"arbitrary":{"type":"string"}},"additionalProperties":false}`)
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("output schema that the runtime cannot produce must be rejected")
	}
}

func TestManifestStrictDecoderRejectsUnknownFields(t *testing.T) {
	m := validManifestForTest()
	raw, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	raw = []byte(strings.TrimSuffix(string(raw), "}") + `, "approved": true}`)
	if _, err := DecodeToolManifest(raw); err == nil {
		t.Fatal("unknown manifest field must be rejected")
	}
}

func TestGeneratedManifestAlwaysValidAndTierDerived(t *testing.T) {
	spec := ToolSpec{
		Name: "sensor_monitor",
		Demand: "Build a sensor monitor with hardware device control and remote API access",
		Purpose: "Monitor sensors over network",
		NeedsHardwareGuide: true,
	}
	manifest, err := validateGeneratedToolManifest(spec)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.RiskTier != 2 || !manifest.Permissions.Hardware || !manifest.Permissions.Network {
		t.Fatalf("expected conservative Tier 2 manifest, got %#v", manifest)
	}
}


func TestManifestRejectsNamesThatPythonGatewayCannotAddress(t *testing.T) {
	for _, name := range []string{"1tool", "_tool", "Tool", "tool.name"} {
		m := validManifestForTest()
		m.Name = name
		if err := ValidateToolManifest(m); err == nil {
			t.Errorf("expected non-canonical tool name %q to be rejected", name)
		}
	}
}

func TestManifestEnforcesLanguageSpecificEntrypoints(t *testing.T) {
	m := validManifestForTest()
	m.Entrypoint = "src/main.go"
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("Go runtime ABI must use code.go")
	}
	m = validManifestForTest()
	m.Language = "python"
	m.Entrypoint = "main.py"
	if err := ValidateToolManifest(m); err != nil {
		t.Fatalf("Python .py entrypoint should validate: %v", err)
	}
	m.Entrypoint = "main.go"
	if err := ValidateToolManifest(m); err == nil {
		t.Fatal("Python entrypoint must use .py")
	}
}
