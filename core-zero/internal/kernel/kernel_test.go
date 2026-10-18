package kernel

import (
	"os"
	"path/filepath"
	"testing"
)

func TestScanHashesFilesAndSkipsGeneratedState(t *testing.T) {
	root := t.TempDir()
	if e := os.MkdirAll(filepath.Join(root, "src"), 0755); e != nil { t.Fatal(e) }
	if e := os.WriteFile(filepath.Join(root, "src", "main.py"), []byte("print('ok')\n"), 0644); e != nil { t.Fatal(e) }
	if e := os.MkdirAll(filepath.Join(root, "node_modules", "sample"), 0755); e != nil { t.Fatal(e) }
	_ = os.WriteFile(filepath.Join(root, "node_modules", "sample", "ignored.js"), []byte("x"), 0644)
	k, e := New(root)
	if e != nil { t.Fatal(e) }
	scan, e := k.Scan()
	if e != nil { t.Fatal(e) }
	if scan.FileCount != 1 || scan.LanguageCounts["Python"] != 1 { t.Fatalf("unexpected scan: %#v", scan) }
	if scan.ManifestSHA256 == "" { t.Fatal("manifest hash missing") }
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
	if _, err := os.Stat(filepath.Join(root, "core-zero", "state")); !os.IsNotExist(err) {
		t.Fatalf("configured persistent data should not silently write state into repository: %v", err)
	}
}

func TestConfiguredDataDirectoryRejectsFilePath(t *testing.T) {
	root := t.TempDir()
	dataRoot := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(dataRoot, []byte("file"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("USECT_ZERO_DATA_DIR", dataRoot)
	if _, err := New(root); err == nil {
		t.Fatal("configured data directory must be a directory")
	}
}
