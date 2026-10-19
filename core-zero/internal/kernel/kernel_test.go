package kernel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newTestKernel(t *testing.T) (*Kernel, string) {
	t.Helper()

	// Keep each test independent of deployment-specific data directory
	// settings inherited from the machine running the test suite.
	t.Setenv("USECT_ZERO_DATA_DIR", "")

	root := t.TempDir()
	k, err := New(root)
	if err != nil {
		t.Fatalf("initialize kernel: %v", err)
	}

	return k, root
}

func TestScanHashesFilesAndSkipsGeneratedState(t *testing.T) {
	k, root := newTestKernel(t)

	if err := os.MkdirAll(filepath.Join(root, "src"), 0755); err != nil {
		t.Fatal(err)
	}

	content := []byte("print('ok')\n")
	mainFile := filepath.Join(root, "src", "main.py")

	if err := os.WriteFile(mainFile, content, 0644); err != nil {
		t.Fatal(err)
	}

	ignoredFiles := map[string]string{
		filepath.Join("node_modules", "sample", "ignored.js"): "ignored",
		filepath.Join("dist", "bundle.js"):                    "generated",
		filepath.Join("build", "output.py"):                   "generated",
	}

	for relative, value := range ignoredFiles {
		path := filepath.Join(root, relative)
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0644); err != nil {
			t.Fatal(err)
		}
	}

	// Files generated in managed state directories must not become part of
	// the source manifest.
	generatedState := filepath.Join(k.CoreRoot, "state", "generated.json")
	if err := os.WriteFile(generatedState, []byte(`{"generated":true}`), 0600); err != nil {
		t.Fatal(err)
	}

	scan, err := k.Scan()
	if err != nil {
		t.Fatalf("scan failed: %v", err)
	}

	if scan.FileCount != 1 {
		t.Fatalf("expected exactly one scanned source file, got %d: %#v", scan.FileCount, scan.Files)
	}

	if len(scan.Files) != 1 {
		t.Fatalf("expected one file record, got %d", len(scan.Files))
	}

	record := scan.Files[0]

	if record.Path != "src/main.py" {
		t.Fatalf("unexpected repository-relative path: %q", record.Path)
	}

	if record.Bytes != int64(len(content)) {
		t.Fatalf("unexpected byte count: got %d, want %d", record.Bytes, len(content))
	}

	if record.Language != "Python" {
		t.Fatalf("unexpected language: %q", record.Language)
	}

	expectedHash := sha256.Sum256(content)
	if record.SHA256 != hex.EncodeToString(expectedHash[:]) {
		t.Fatalf("incorrect file hash: %q", record.SHA256)
	}

	if scan.LanguageCounts["Python"] != 1 {
		t.Fatalf("unexpected language counts: %#v", scan.LanguageCounts)
	}

	if scan.ManifestSHA256 == "" {
		t.Fatal("manifest hash missing")
	}

	if scan.RepositoryRoot != "." {
		t.Fatalf("scan should use a logical root instead of an absolute path: %q", scan.RepositoryRoot)
	}

	if !scan.ReadOnly {
		t.Fatal("repository inventory must be identified as read-only")
	}

	if strings.Contains(scan.EvidenceNote, "hardware verified") {
		t.Fatal("scan evidence must not claim hardware verification")
	}

	for _, record := range scan.Files {
		if strings.Contains(record.Path, "node_modules") ||
			strings.HasPrefix(record.Path, "dist/") ||
			strings.HasPrefix(record.Path, "build/") ||
			strings.HasPrefix(record.Path, "core-zero/state/") {
			t.Fatalf("excluded path appeared in scan: %q", record.Path)
		}
	}
}

func TestScanSkipsSymlinkedFiles(t *testing.T) {
	k, root := newTestKernel(t)

	src := filepath.Join(root, "src")
	if err := os.MkdirAll(src, 0755); err != nil {
		t.Fatal(err)
	}

	target := filepath.Join(t.TempDir(), "outside.py")
	if err := os.WriteFile(target, []byte("print('outside')\n"), 0644); err != nil {
		t.Fatal(err)
	}

	link := filepath.Join(src, "linked.py")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink creation is unavailable in this environment: %v", err)
	}

	scan, err := k.Scan()
	if err != nil {
		t.Fatalf("scan failed: %v", err)
	}

	for _, file := range scan.Files {
		if file.Path == "src/linked.py" {
			t.Fatal("scan included a symlinked file")
		}
	}

	if scan.FileCount != 0 {
		t.Fatalf("expected no regular source files, got %d: %#v", scan.FileCount, scan.Files)
	}
}

func TestScanReportsLogicalRepositoryRoot(t *testing.T) {
	k, root := newTestKernel(t)

	if err := os.WriteFile(
		filepath.Join(root, "README.md"),
		[]byte("# USECT-ZERO\n"),
		0644,
	); err != nil {
		t.Fatal(err)
	}

	scan, err := k.Scan()
	if err != nil {
		t.Fatal(err)
	}

	if scan.RepositoryRoot != "." {
		t.Fatalf("absolute repository path should not be in scan evidence: %q", scan.RepositoryRoot)
	}

	if strings.Contains(scan.RepositoryRoot, root) {
		t.Fatal("repository root leaked into public evidence")
	}
}

func TestConfiguredDataDirectoryKeepsRuntimeStateOutsideRepository(t *testing.T) {
	root := t.TempDir()
	dataRoot := filepath.Join(t.TempDir(), "persistent", "usect-zero")
	t.Setenv("USECT_ZERO_DATA_DIR", dataRoot)

	k, err := New(root)
	if err != nil {
		t.Fatal(err)
	}

	if k.CoreRoot != dataRoot {
		t.Fatalf("expected configured data root %q, got %q", dataRoot, k.CoreRoot)
	}

	for _, dir := range []string{"state", "evidence", "audit_log"} {
		info, err := os.Stat(filepath.Join(dataRoot, dir))
		if err != nil {
			t.Fatalf("runtime data directory %s missing: %v", dir, err)
		}

		if !info.IsDir() {
			t.Fatalf("runtime path %s is not a directory", dir)
		}
	}

	if _, err := os.Stat(filepath.Join(root, "core-zero")); !os.IsNotExist(err) {
		t.Fatalf("configured persistent data should not create a repository-local core-zero directory: %v", err)
	}
}

func TestConfiguredDataDirectoryRejectsFilePath(t *testing.T) {
	root := t.TempDir()
	dataRoot := filepath.Join(t.TempDir(), "not-a-directory")

	if err := os.WriteFile(dataRoot, []byte("file"), 0600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("USECT_ZERO_DATA_DIR", "")

	// Configure the existing file after clearing inherited configuration.
	t.Setenv("USECT_ZERO_DATA_DIR", dataRoot)

	if _, err := New(root); err == nil {
		t.Fatal("configured data path must be a directory")
	}
}

func TestRelativeSafeRejectsTraversalAndAbsolutePaths(t *testing.T) {
	k, root := newTestKernel(t)

	valid, err := k.relativeSafe(filepath.Join("src", "main.go"))
	if err != nil {
		t.Fatalf("valid relative path rejected: %v", err)
	}

	if valid != filepath.Join("src", "main.go") {
		t.Fatalf("unexpected cleaned path: %q", valid)
	}

	invalidPaths := []string{
		"",
		" ",
		".",
		"..",
		filepath.Join("..", "outside.txt"),
		filepath.Join("src", "..", "..", "outside.txt"),
	}

	for _, path := range invalidPaths {
		t.Run("relative_"+strings.ReplaceAll(path, string(filepath.Separator), "_"), func(t *testing.T) {
			if _, err := k.relativeSafe(path); err == nil {
				t.Fatalf("unsafe path accepted: %q", path)
			}
		})
	}

	absolute := filepath.Join(root, "outside.txt")
	if _, err := k.relativeSafe(absolute); err == nil {
		t.Fatalf("absolute path accepted: %q", absolute)
	}
}

func TestWriteJSONReadJSONRoundTrip(t *testing.T) {
	k, _ := newTestKernel(t)

	type sampleState struct {
		Version int      `json:"version"`
		Enabled bool     `json:"enabled"`
		Values  []string `json:"values"`
	}

	expected := sampleState{
		Version: 1,
		Enabled: true,
		Values:  []string{"scan", "diagnostics", "evidence"},
	}

	if err := k.writeJSON("state/sample.json", expected); err != nil {
		t.Fatalf("write JSON state: %v", err)
	}

	var actual sampleState
	if err := k.readJSON("state/sample.json", &actual); err != nil {
		t.Fatalf("read JSON state: %v", err)
	}

	if actual.Version != expected.Version ||
		actual.Enabled != expected.Enabled ||
		len(actual.Values) != len(expected.Values) {
		t.Fatalf("state round trip mismatch: got %#v want %#v", actual, expected)
	}

	for i := range expected.Values {
		if actual.Values[i] != expected.Values[i] {
			t.Fatalf("value mismatch at index %d: got %q want %q", i, actual.Values[i], expected.Values[i])
		}
	}
}

func TestWriteJSONRejectsPathTraversal(t *testing.T) {
	k, root := newTestKernel(t)

	outside := filepath.Join(root, "escape.json")

	err := k.writeJSON(filepath.Join("state", "..", "..", "escape.json"), map[string]any{
		"executed": true,
	})
	if err == nil {
		t.Fatal("state path traversal was accepted")
	}

	if _, statErr := os.Stat(outside); !os.IsNotExist(statErr) {
		t.Fatalf("path traversal created a file outside managed storage: %v", statErr)
	}
}

func TestReadJSONRejectsSymlinkedStateFile(t *testing.T) {
	k, _ := newTestKernel(t)

	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte(`{"trusted":true}`), 0600); err != nil {
		t.Fatal(err)
	}

	link := filepath.Join(k.CoreRoot, "state", "linked.json")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink creation is unavailable in this environment: %v", err)
	}

	var result map[string]any
	if err := k.readJSON("state/linked.json", &result); err == nil {
		t.Fatal("readJSON accepted a symlink pointing outside managed storage")
	}
}

func TestWriteJSONRejectsSymlinkedStateFile(t *testing.T) {
	k, _ := newTestKernel(t)

	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte(`{"trusted":true}`), 0600); err != nil {
		t.Fatal(err)
	}

	link := filepath.Join(k.CoreRoot, "state", "linked.json")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink creation is unavailable in this environment: %v", err)
	}

	err := k.writeJSON("state/linked.json", map[string]any{"trusted": false})
	if err == nil {
		t.Fatal("writeJSON accepted a symlinked destination")
	}

	data, err := os.ReadFile(outside)
	if err != nil {
		t.Fatal(err)
	}

	if string(data) != `{"trusted":true}` {
		t.Fatalf("outside target was modified: %s", data)
	}
}

func TestAuditAppendsValidJSONLines(t *testing.T) {
	k, _ := newTestKernel(t)

	if err := k.Audit(
		"repository_scan",
		"test-operator",
		"manifest-123",
		"evidence_saved",
		map[string]any{"file_count": 3},
	); err != nil {
		t.Fatalf("first audit event failed: %v", err)
	}

	if err := k.Audit(
		"baseline_recorded",
		"test-operator",
		"git-head-123",
		"evidence_saved",
		map[string]any{"file_count": 3},
	); err != nil {
		t.Fatalf("second audit event failed: %v", err)
	}

	logPath := filepath.Join(k.CoreRoot, "audit_log", "events.jsonl")
	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read audit log: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected two JSONL audit events, got %d: %s", len(lines), raw)
	}

	var first AuditEvent
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil {
		t.Fatalf("first audit event is invalid JSON: %v", err)
	}

	if first.Action != "repository_scan" ||
		first.Actor != "test-operator" ||
		first.Subject != "manifest-123" ||
		first.Outcome != "evidence_saved" {
		t.Fatalf("unexpected first audit event: %#v", first)
	}

	if first.At.IsZero() {
		t.Fatal("audit event timestamp missing")
	}

	var second AuditEvent
	if err := json.Unmarshal([]byte(lines[1]), &second); err != nil {
		t.Fatalf("second audit event is invalid JSON: %v", err)
	}

	if second.Action != "baseline_recorded" {
		t.Fatalf("second audit event was not appended correctly: %#v", second)
	}
}

func TestNewRejectsSymlinkedManagedStateDirectory(t *testing.T) {
	t.Setenv("USECT_ZERO_DATA_DIR", "")

	root := t.TempDir()
	coreRoot := filepath.Join(root, "core-zero")
	if err := os.MkdirAll(coreRoot, 0700); err != nil {
		t.Fatal(err)
	}

	outsideState := filepath.Join(t.TempDir(), "outside-state")
	if err := os.MkdirAll(outsideState, 0700); err != nil {
		t.Fatal(err)
	}

	stateLink := filepath.Join(coreRoot, "state")
	if err := os.Symlink(outsideState, stateLink); err != nil {
		t.Skipf("symlink creation is unavailable in this environment: %v", err)
	}

	if _, err := New(root); err == nil {
		t.Fatal("kernel initialization followed a symlinked state directory")
	}
}
