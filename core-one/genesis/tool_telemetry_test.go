package genesis

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestToolTelemetryUsesPersistentRegistryAndContainsNoInvocationContent(t *testing.T) {
	persistent := filepath.Join(t.TempDir(), "persistent-registry")
	t.Setenv("GENESIS_REGISTRY_DIR", persistent)
	engine := newTestEngine(t)

	event := ToolCallTelemetry{
		At: time.Now().UTC(), Tool: "safe_tool", VersionHash: strings.Repeat("a", 64),
		Success: true, LatencyMS: 42, ErrorClass: "",
	}
	if err := appendToolCallTelemetry(engine.CoreRoot, event); err != nil {
		t.Fatal(err)
	}

	logPath := filepath.Join(persistent, "telemetry", "tool_calls.jsonl")
	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	for _, forbidden := range []string{"prompt", "arguments", "result", "credential", "authorization"} {
		if strings.Contains(strings.ToLower(text), forbidden) {
			t.Fatalf("content-free telemetry unexpectedly contains %q", forbidden)
		}
	}
	if strings.Contains(text, "safe_tool") == false {
		t.Fatal("telemetry should identify the tool")
	}
	events, err := listToolCallTelemetry(engine.CoreRoot, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 1 || events[0].Tool != "safe_tool" || events[0].VersionHash != strings.Repeat("a", 64) {
		t.Fatalf("unexpected telemetry result: %#v", events)
	}
}

func TestToolTelemetryRejectsNonHexArtifactHash(t *testing.T) {
	engine := newTestEngine(t)
	err := appendToolCallTelemetry(engine.CoreRoot, ToolCallTelemetry{
		At: time.Now().UTC(), Tool: "safe_tool", VersionHash: strings.Repeat("g", 64),
	})
	if err == nil {
		t.Fatal("telemetry must reject invalid artifact hashes")
	}
}
