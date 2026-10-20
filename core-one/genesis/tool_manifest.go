package genesis

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"strings"
)

const (
	ToolManifestSchemaVersion = "genesis.tool-manifest.v1"
	MaxToolTimeoutMillis      = 120000
	MaxToolMemoryBytes        = 512 << 20
	MinToolMemoryBytes        = 16 << 20
)

// ToolPermissions are capabilities granted to a candidate at runtime.
// The tier is always derived from these permissions; callers cannot lower it.
type ToolPermissions struct {
	Network    bool `json:"network"`
	Filesystem bool `json:"filesystem"`
	Secrets    bool `json:"secrets"`
	Hardware   bool `json:"hardware"`
}

// ToolManifest is the strict, versioned contract required for a generated tool.
type ToolManifest struct {
	SchemaVersion string          `json:"schema_version"`
	Name          string          `json:"name"`
	Version       string          `json:"version"`
	Language      string          `json:"language"`
	Entrypoint    string          `json:"entrypoint"`
	InputSchema   json.RawMessage `json:"input_schema"`
	OutputSchema  json.RawMessage `json:"output_schema"`
	RiskTier      int             `json:"risk_tier"`
	Permissions   ToolPermissions `json:"permissions"`
	TimeoutMillis int             `json:"timeout_ms"`
	MemoryBytes   int64           `json:"memory_bytes"`
}

// DerivedRiskTier is the policy source of truth. Filesystem and secret access
// require Tier 1 review; hardware access requires Tier 2 per-action confirmation.
func DerivedRiskTier(p ToolPermissions) int {
	if p.Hardware {
		return 2
	}
	if p.Network || p.Filesystem || p.Secrets {
		return 1
	}
	return 0
}

// ValidateToolManifest rejects incomplete, oversized, ambiguous, or over-
// privileged manifests. JSON schemas are bounded local documents only.
func ValidateToolManifest(m ToolManifest) error {
	if m.SchemaVersion != ToolManifestSchemaVersion {
		return errors.New("unsupported tool manifest schema version")
	}
	if !validResourceName(m.Name) || len(m.Name) > maxAPIToolName {
		return errors.New("invalid tool manifest name")
	}
	if strings.TrimSpace(m.Version) == "" || len(m.Version) > 64 || strings.ContainsAny(m.Version, "\r\n") {
		return errors.New("invalid tool manifest version")
	}
	if m.Language != "go" && m.Language != "python" {
		return errors.New("tool language must be go or python")
	}
	if m.Entrypoint == "" || len(m.Entrypoint) > 240 || strings.Contains(m.Entrypoint, "\\") ||
		path.IsAbs(m.Entrypoint) || path.Clean(m.Entrypoint) != m.Entrypoint ||
		m.Entrypoint == "." || m.Entrypoint == ".." || strings.HasPrefix(m.Entrypoint, "../") {
		return errors.New("entrypoint must be a clean relative path inside the artifact")
	}
	if err := validateLocalJSONObjectSchema(m.InputSchema); err != nil {
		return fmt.Errorf("invalid input schema: %w", err)
	}
	if err := validateLocalJSONObjectSchema(m.OutputSchema); err != nil {
		return fmt.Errorf("invalid output schema: %w", err)
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

func validateLocalJSONObjectSchema(raw json.RawMessage) error {
	if len(raw) == 0 || len(raw) > 64*1024 || !json.Valid(raw) {
		return errors.New("schema must be valid JSON no larger than 64 KiB")
	}
	var schema map[string]json.RawMessage
	if err := json.Unmarshal(raw, &schema); err != nil || schema == nil {
		return errors.New("schema root must be an object")
	}
	var schemaType string
	if err := json.Unmarshal(schema["type"], &schemaType); err != nil || schemaType != "object" {
		return errors.New("schema root type must be object")
	}
	if _, ok := schema["$ref"]; ok {
		return errors.New("external or referenced schemas are not accepted")
	}
	return nil
}

// DecodeToolManifest uses strict JSON decoding so undeclared fields are not
// silently ignored at trust boundaries.
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
		InputSchema:   json.RawMessage(`{"type":"object","properties":{},"additionalProperties":false}`),
		OutputSchema:  json.RawMessage(`{"type":"object","properties":{},"additionalProperties":true}`),
		Permissions:   permissions,
		TimeoutMillis: 10000,
		MemoryBytes:   128 << 20,
	}
	manifest.RiskTier = DerivedRiskTier(permissions)
	return manifest
}

func inferToolPermissions(spec ToolSpec) ToolPermissions {
	text := strings.ToLower(strings.Join([]string{spec.Demand, spec.Purpose, strings.Join(spec.Capabilities, " ")}, " "))
	contains := func(terms ...string) bool {
		for _, term := range terms {
			if strings.Contains(text, term) {
				return true
			}
		}
		return false
	}
	return ToolPermissions{
		Network: contains("network", "internet", "web search", "http request", "external api", "remote api"),
		Filesystem: contains("file", "filesystem", "folder", "directory", "local storage", "read/write", "save to disk"),
		Secrets: contains("password", "credential", "api key", "secret", "authentication token"),
		Hardware: spec.NeedsHardwareGuide || contains("hardware", "sensor", "actuator", "robot", "motor", "device control", "physical device"),
	}
}

// validateGeneratedToolManifest is called before the artifact is persisted.
func validateGeneratedToolManifest(spec ToolSpec) (ToolManifest, error) {
	manifest := buildToolManifest(spec)
	if err := ValidateToolManifest(manifest); err != nil {
		return ToolManifest{}, err
	}
	return manifest, nil
}

