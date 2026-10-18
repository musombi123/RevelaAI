package heal

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"usect-zero.local/core-zero/internal/kernel"
)

func git(t *testing.T, dir string, args ...string) {
	t.Helper()
	c := exec.Command("git", append([]string{"-C", dir}, args...)...)
	if b, e := c.CombinedOutput(); e != nil { t.Fatalf("git %v: %v %s", args, e, b) }
}
func TestDeletedTrackedFileWaitsForApproval(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init", "-b", "main")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "USECT test")
	p := filepath.Join(root, "sample.py")
	if e := os.WriteFile(p, []byte("VALUE = 7\n"), 0644); e != nil { t.Fatal(e) }
	git(t, root, "add", "sample.py")
	git(t, root, "commit", "-m", "known good")
	k, e := kernel.New(root); if e != nil { t.Fatal(e) }
	if _, e = k.RecordBaseline(); e != nil { t.Fatal(e) }
	if e = os.Remove(p); e != nil { t.Fatal(e) }
	prop, e := ProposeMissing(k); if e != nil { t.Fatal(e) }
	if prop.Status != "awaiting_human_approval" || len(prop.Items) != 1 { t.Fatalf("unexpected proposal: %#v", prop) }
	if _, e = os.Stat(p); !os.IsNotExist(e) { t.Fatal("proposal unexpectedly restored source before approval") }
	if _, e = ApproveRestore(k, prop.ID, "wrong"); e == nil { t.Fatal("invalid confirmation must fail") }
	if _, e = os.Stat(p); !os.IsNotExist(e) { t.Fatal("invalid confirmation wrote source") }
	finished, e := ApproveRestore(k, prop.ID, "RESTORE_TO_REPOSITORY"); if e != nil { t.Fatal(e) }
	b, e := os.ReadFile(p); if e != nil { t.Fatal(e) }
	if string(b) != "VALUE = 7\n" { t.Fatalf("wrong restored bytes: %q", b) }
	if finished.Status != "completed_after_approval" { t.Fatalf("wrong final status: %s", finished.Status) }
}
