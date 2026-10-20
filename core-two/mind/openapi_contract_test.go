package mind

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestOpenAPIPathKeysAreUnique catches duplicate YAML mapping keys under
// "paths:" before a permissive YAML parser can silently discard earlier
// endpoint definitions.
func TestOpenAPIPathKeysAreUnique(t *testing.T) {
	candidates := []string{
		filepath.Join("..", "openapi.yaml"),
		filepath.Join("core-two", "openapi.yaml"),
	}
	var raw []byte
	var err error
	for _, name := range candidates {
		raw, err = os.ReadFile(name)
		if err == nil {
			break
		}
	}
	if err != nil {
		t.Fatalf("read OpenAPI contract: %v", err)
	}

	scanner := bufio.NewScanner(strings.NewReader(string(raw)))
	inPaths := false
	pathsSections := 0
	seen := map[string]int{}
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		line := scanner.Text()
		if line == "paths:" {
			pathsSections++
			inPaths = true
			continue
		}
		if inPaths && line != "" && !strings.HasPrefix(line, " ") && !strings.HasPrefix(line, "#") {
			inPaths = false
		}
		if !inPaths || !strings.HasPrefix(line, "  /") || !strings.HasSuffix(strings.TrimSpace(line), ":") {
			continue
		}
		key := strings.TrimSuffix(strings.TrimSpace(line), ":")
		if first, exists := seen[key]; exists {
			t.Errorf("duplicate OpenAPI path key %q at line %d (first declared at line %d)", key, lineNo, first)
		} else {
			seen[key] = lineNo
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan OpenAPI contract: %v", err)
	}
	if pathsSections != 1 {
		t.Fatalf("expected exactly one top-level paths key, found %d", pathsSections)
	}
	if len(seen) == 0 {
		t.Fatal("OpenAPI contract declares no path entries")
	}
	requiredPaths := []string{
		"/v1/mind/health", "/v1/mind/metrics", "/v1/mind/evolve",
		"/v1/mind/evolutions", "/v1/mind/learning", "/v1/mind/feedback",
		"/v1/mind/stream", "/v1/mind/key", "/v1/mind/tools/{name}/improvement",
		"/v1/mind/telemetry/events", "/v1/mind/candidates",
		"/v1/zero/health", "/v1/genesis/health", "/v1/rvx/compile",
	}
	for _, required := range requiredPaths {
		if _, ok := seen[required]; !ok {
			t.Errorf("OpenAPI contract is missing required path %q", required)
		}
	}
}
