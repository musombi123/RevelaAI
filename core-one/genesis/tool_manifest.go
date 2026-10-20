package genesis

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"reflect"
	"regexp"
	"strings"
)

var toolManifestNamePattern = regexp.MustCompile("^[a-z][a-z0-9_-]{0,63}$")
var toolManifestVersionPattern = regexp.MustCompile("^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")

const (
	ToolManifestSchemaVersion = "genesis.tool-manifest.v1"
	MaxToolTimeoutMillis      = 120000
	MaxToolMemoryBytes        = 512 << 20
	MinToolMemoryBytes        = 16 << 20
)

const runtimeToolInputSchemaJSON = `{"type":"object","properties":{"action":{"type":"string","maxLength":2000},"inputs":{"type":"object","additionalProperties":{"type":"string","maxLength":4000}},"consent":{"type":"boolean"}},"required":["action"],"additionalProperties":false}`
const runtimeToolOutputSchemaJSON = `{"type":"object","properties":{"status":{"type":"string"},"tool":{"type":"string"},"summary":{"type":"string"},"created_at":{"type":"string"},"evidence":{"type":"array","items":{"type":"string"}}},"required":["status","tool","summary"],"additionalProperties":false}`

// ToolPermissions are capabilities granted to a candidate at runtime.
// Tier is validated against these permissions; a manifest cannot self-downgrade.
type ToolPermissions struct {
	Network    bool "json:\"network\""
	Filesystem bool "json:\"filesystem\""
	Secrets    bool "json:\"secrets\""
	Hardware   bool "json:\"hardware\""
}

// ToolManifest is the strict, versioned contract required for every generated tool.
type ToolManifest struct {
	SchemaVersion string          "json:\"schema_version\""
	Name          string          "json:\"name\""
	Version       string          "json:\"version\""
	Language      string          "json:\"language\""
	Entrypoint    string          "json:\"entrypoint\""
	InputSchema   json.RawMessage "json:\"input_schema\""
	OutputSchema  json.RawMessage "json:\"output_schema\""
	RiskTier      int             "json:\"risk_tier\""
	Permissions   ToolPermissions "json:\"permissions\""
	TimeoutMillis int             "json:\"timeout_ms\""
	MemoryBytes   int64           "json:\"memory_bytes\""
}

// DerivedRiskTier is the policy source of truth: hardware => Tier 2;
// network, filesystem, or secrets => at least Tier 1.
func DerivedRiskTier(p ToolPermissions) int {
	if p.Hardware {
		return 2
	}
	if p.Network || p.Filesystem || p.Secrets {
		return 1
	}
	return 0
}

// ValidateToolManifest validates all required fields, limits, schema roots,
// entrypoint path safety and permission-derived risk tier.
func ValidateToolManifest(m ToolManifest) error {
	if m.SchemaVersion != ToolManifestSchemaVersion {
		return errors.New("unsupported tool manifest schema version")
	}
	if !toolManifestNamePattern.MatchString(m.Name) || len(m.Name) > maxAPIToolName {
		return errors.New("invalid tool manifest name")
	}
	if !toolManifestVersionPattern.MatchString(m.Version) {
		return errors.New("invalid tool manifest version")
	}
	if m.Language != "go" && m.Language != "python" {
		return errors.New("tool language must be go or python")
	}
	if m.Language == "go" && m.Entrypoint != "code.go" {
		return errors.New("Go tools must use the code.go entrypoint")
	}
	if m.Language == "python" && path.Ext(m.Entrypoint) != ".py" {
		return errors.New("Python tools must use a .py entrypoint")
	}
	if m.Entrypoint == "" || len(m.Entrypoint) > 240 ||
		strings.ContainsAny(m.Entrypoint, "\\\r\n") ||
		path.IsAbs(m.Entrypoint) ||
		path.Clean(m.Entrypoint) != m.Entrypoint ||
		m.Entrypoint == "." || m.Entrypoint == ".." ||
		strings.HasPrefix(m.Entrypoint, "../") ||
		strings.Contains(m.Entrypoint, ":") {
		return errors.New("entrypoint must be a clean relative path inside the artifact")
	}
	if err := validateLocalJSONObjectSchema(m.InputSchema); err != nil {
		return fmt.Errorf("invalid input schema: %w", err)
	}
	if err := validateLocalJSONObjectSchema(m.OutputSchema); err != nil {
		return fmt.Errorf("invalid output schema: %w", err)
	}
	if err := validateRuntimeSchema(m.InputSchema, runtimeToolInputSchemaJSON); err != nil {
		return fmt.Errorf("input schema does not match the supported tool runtime ABI: %w", err)
	}
	if err := validateRuntimeSchema(m.OutputSchema, runtimeToolOutputSchemaJSON); err != nil {
		return fmt.Errorf("output schema does not match the supported tool runtime ABI: %w", err)
	}
	if m.TimeoutMillis < 1 || m.TimeoutMillis > MaxToolTimeoutMillis {
		return errors.New("timeout_ms is outside the permitted range")
	}
	if m.MemoryBytes < MinToolMemoryBytes || m.MemoryBytes > MaxToolMemoryBytes {
		return errors.New("memory_bytes is outside the permitted range")
	}
	if m.RiskTier != DerivedRiskTier(m.Permissions) {
		return errors.New("risk_tier does not match the derived permissions tier")
	}
	return nil
}

func validateRuntimeSchema(raw json.RawMessage, expected string) error {
	var actual any
	if err := json.Unmarshal(raw, &actual); err != nil {
		return errors.New("schema could not be decoded")
	}
	var canonical any
	if err := json.Unmarshal([]byte(expected), &canonical); err != nil {
		return errors.New("runtime schema definition is invalid")
	}
	if !reflect.DeepEqual(actual, canonical) {
		return errors.New("schema differs from the supported action/inputs/consent runtime contract")
	}
	return nil
}

func validateLocalJSONObjectSchema(raw json.RawMessage) error {
	if len(raw) == 0 || len(raw) > 64*1024 || !json.Valid(raw) {
		return errors.New("schema must be valid JSON no larger than 64 KiB")
	}
	var schema any
	if err := json.Unmarshal(raw, &schema); err != nil {
		return errors.New("schema could not be decoded")
	}
	root, ok := schema.(map[string]any)
	if !ok || root["type"] != "object" {
		return errors.New("schema root type must be object")
	}
	if containsSchemaReference(root) {
		return errors.New("referenced schemas are not accepted")
	}
	return nil
}

func containsSchemaReference(value any) bool {
	switch item := value.(type) {
	case map[string]any:
		for key, child := range item {
			if key == "$ref" || key == "$dynamicRef" {
				return true
			}
			if containsSchemaReference(child) {
				return true
			}
		}
	case []any:
		for _, child := range item {
			if containsSchemaReference(child) {
				return true
			}
		}
	}
	return false
}

// DecodeToolManifest refuses unknown fields and trailing JSON values at trust boundaries.
func DecodeToolManifest(raw []byte) (ToolManifest, error) {
	if len(raw) == 0 || len(raw) > 256*1024 {
		return ToolManifest{}, errors.New("manifest is empty or too large")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var manifest ToolManifest
	if err := decoder.Decode(&manifest); err != nil {
		return ToolManifest{}, fmt.Errorf("decode tool manifest: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return ToolManifest{}, errors.New("manifest must contain exactly one JSON value")
	}
	if err := ValidateToolManifest(manifest); err != nil {
		return ToolManifest{}, err
	}
	return manifest, nil
}

func buildToolManifest(spec ToolSpec) ToolManifest {
	permissions := inferToolPermissions(spec)
	manifest := ToolManifest{
		SchemaVersion: ToolManifestSchemaVersion,
		Name:          spec.Name,
		Version:       "1.0.0",
		Language:      "go",
		Entrypoint:    "code.go",
		InputSchema: json.RawMessage("{\"type\":\"object\",\"properties\":{\"action\":{\"type\":\"string\",\"maxLength\":2000},\"inputs\":{\"type\":\"object\",\"additionalProperties\":{\"type\":\"string\",\"maxLength\":4000}},\"consent\":{\"type\":\"boolean\"}},\"required\":[\"action\"],\"additionalProperties\":false}"),
		OutputSchema: json.RawMessage("{\"type\":\"object\",\"properties\":{\"status\":{\"type\":\"string\"},\"tool\":{\"type\":\"string\"},\"summary\":{\"type\":\"string\"},\"created_at\":{\"type\":\"string\"},\"evidence\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"status\",\"tool\",\"summary\"],\"additionalProperties\":false}"),
		Permissions:   permissions,
		TimeoutMillis: 10000,
		MemoryBytes:   256 << 20,
	}
	manifest.RiskTier = DerivedRiskTier(permissions)
	return manifest
}

func inferToolPermissions(spec ToolSpec) ToolPermissions {
	text := strings.ToLower(strings.Join([]string{
		spec.Demand, spec.Purpose, strings.Join(spec.Capabilities, " "),
		strings.Join(spec.Inputs, " "), strings.Join(spec.Outputs, " "),
	}, " "))
	contains := func(terms ...string) bool {
		for _, term := range terms {
			if strings.Contains(text, term) {
				return true
			}
		}
		return false
	}
	return ToolPermissions{
		Network: contains("network", "internet", "web search", "browser", "http request", "external api", "remote api", "online", "fetch url"),
		Filesystem: contains("file", "filesystem", "folder", "directory", "local storage", "read/write", "save to disk", "file system"),
		Secrets: contains("password", "credential", "api key", "secret", "authentication token", "private key"),
		Hardware: spec.NeedsHardwareGuide || contains("hardware", "sensor", "actuator", "robot", "motor", "device control", "physical device", "camera", "microphone"),
	}
}

// validateGeneratedToolManifest is called before an invention is persisted.
func validateGeneratedToolManifest(spec ToolSpec) (ToolManifest, error) {
	manifest := buildToolManifest(spec)
	if err := ValidateToolManifest(manifest); err != nil {
		return ToolManifest{}, err
	}
	return manifest, nil
}
