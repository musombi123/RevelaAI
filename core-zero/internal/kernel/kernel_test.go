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
