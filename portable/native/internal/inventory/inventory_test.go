package inventory

import (
	"os"
	"path/filepath"
	"testing"
)

func TestScanHashesRegularFileWithoutChangingIt(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "notes.txt")
	if err := os.WriteFile(file, []byte("defensive lab fixture"), 0600); err != nil { t.Fatal(err) }
	before, _ := os.ReadFile(file)
	got, err := Scan(root, 100)
	if err != nil { t.Fatal(err) }
	after, _ := os.ReadFile(file)
	if string(before) != string(after) { t.Fatal("inventory modified source file") }
	if got.Hashed != 1 || got.TotalFiles != 1 || got.Files[0].SHA256 == "" { t.Fatalf("unexpected result: %+v", got) }
}

func TestScanRejectsSymlinkRoot(t *testing.T) {
	base := t.TempDir()
	target := filepath.Join(base, "target")
	if err := os.Mkdir(target, 0700); err != nil { t.Fatal(err) }
	link := filepath.Join(base, "link")
	if err := os.Symlink(target, link); err != nil { t.Skipf("symlink unavailable: %v", err) }
	if _, err := Scan(link, 10); err == nil { t.Fatal("expected symlink root rejection") }
}

func TestScanRejectsFileLimitOutsideBounds(t *testing.T) {
	if _, err := Scan(t.TempDir(), DefaultMaxFiles+1); err == nil { t.Fatal("expected invalid limit") }
}
