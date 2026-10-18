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
	if b, e := c.CombinedOutput(); e != nil {
		t.Fatalf("git %v: %v %s", args, e, b)
	}
}

func newGitRepoWithFile(t *testing.T) (string, *kernel.Kernel, string) {
	t.Helper()
	root := t.TempDir()
	git(t, root, "init", "-b", "main")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "USECT test")
	path := filepath.Join(root, "sample.py")
	if err := os.WriteFile(path, []byte("VALUE = 7\n"), 0644); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", "sample.py")
	git(t, root, "commit", "-m", "known good")
	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = k.RecordBaseline(); err != nil {
		t.Fatal(err)
	}
	return root, k, path
}

func TestDeletedTrackedFileWaitsForApproval(t *testing.T) {
	root, k, path := newGitRepoWithFile(t)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	prop, err := ProposeMissing(k)
	if err != nil {
		t.Fatal(err)
	}
	if prop.Status != "awaiting_human_approval" || len(prop.Items) != 1 {
		t.Fatalf("unexpected proposal: %#v", prop)
	}
	if prop.Items[0].TargetState != "missing" {
		t.Fatalf("expected missing target state: %+v", prop.Items[0])
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("proposal unexpectedly restored source before approval")
	}
	if _, err = ApproveRestore(k, prop.ID, "wrong"); err == nil {
		t.Fatal("invalid confirmation must fail")
	}
	if _, err = os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("invalid confirmation wrote source")
	}
	finished, err := ApproveRestore(k, prop.ID, "RESTORE_TO_REPOSITORY")
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "VALUE = 7\n" {
		t.Fatalf("wrong restored bytes: %q", b)
	}
	if finished.Status != "completed_after_approval" {
		t.Fatalf("wrong final status: %s", finished.Status)
	}
	if _, err := os.Stat(root); err != nil {
		t.Fatal(err)
	}
}

func TestModifiedTrackedFileGetsBackupAndRequiresApproval(t *testing.T) {
	root, k, path := newGitRepoWithFile(t)
	modified := "VALUE = 999\n"
	if err := os.WriteFile(path, []byte(modified), 0644); err != nil {
		t.Fatal(err)
	}
	prop, err := ProposeRecovery(k)
	if err != nil {
		t.Fatal(err)
	}
	if prop.Status != "awaiting_human_approval" || len(prop.Items) != 1 {
		t.Fatalf("unexpected proposal: %#v", prop)
	}
	item := prop.Items[0]
	if item.TargetState != "modified" || item.ObservedSHA256 == "" || item.Status != "candidate_staged" {
		t.Fatalf("modified file was not staged safely: %+v", item)
	}
	if content, err := os.ReadFile(path); err != nil || string(content) != modified {
		t.Fatalf("proposal changed the target before approval: %q %v", content, err)
	}
	if _, err := ApproveRestore(k, prop.ID, "wrong"); err == nil {
		t.Fatal("invalid confirmation must fail")
	}
	if content, err := os.ReadFile(path); err != nil || string(content) != modified {
		t.Fatalf("invalid approval changed the target: %q %v", content, err)
	}

	finished, err := ApproveRestore(k, prop.ID, "RESTORE_TO_REPOSITORY")
	if err != nil {
		t.Fatal(err)
	}
	if content, err := os.ReadFile(path); err != nil || string(content) != "VALUE = 7\n" {
		t.Fatalf("baseline bytes not restored: %q %v", content, err)
	}
	restored := finished.Items[0]
	if restored.Status != "restored_after_approval" || restored.BackupPath == "" {
		t.Fatalf("backup evidence missing after modified restore: %+v", restored)
	}
	backup, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(restored.BackupPath)))
	if err != nil || string(backup) != modified {
		t.Fatalf("modified bytes were not backed up: %q %v", backup, err)
	}
	if hash(backup) != restored.BackupSHA256 || restored.BackupSHA256 != item.ObservedSHA256 {
		t.Fatalf("backup hash mismatch: item=%+v got=%s", restored, hash(backup))
	}
}

func TestModifiedTargetChangedAfterProposalIsRejected(t *testing.T) {
	_, k, path := newGitRepoWithFile(t)
	if err := os.WriteFile(path, []byte("VALUE = 8\n"), 0644); err != nil {
		t.Fatal(err)
	}
	prop, err := ProposeRecovery(k)
	if err != nil {
		t.Fatal(err)
	}
	latest := "VALUE = 9\n"
	if err := os.WriteFile(path, []byte(latest), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := ApproveRestore(k, prop.ID, "RESTORE_TO_REPOSITORY"); err == nil {
		t.Fatal("stale proposal must not overwrite a newer edit")
	}
	if content, err := os.ReadFile(path); err != nil || string(content) != latest {
		t.Fatalf("stale approval overwrote newer work: %q %v", content, err)
	}
}

func TestModifiedSymlinkTargetIsNotFollowed(t *testing.T) {
	root, k, path := newGitRepoWithFile(t)
	outside := filepath.Join(t.TempDir(), "outside.py")
	if err := os.WriteFile(outside, []byte("DO NOT CHANGE\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, path); err != nil {
		t.Skipf("symlinks unavailable on this host: %v", err)
	}
	prop, err := ProposeRecovery(k)
	if err != nil {
		t.Fatal(err)
	}
	if prop.Status != "awaiting_human_approval" {
		t.Fatalf("unexpected proposal: %+v", prop)
	}
	if _, err := ApproveRestore(k, prop.ID, "RESTORE_TO_REPOSITORY"); err == nil {
		t.Fatal("approval must not overwrite or follow the symlink target")
	}
	if content, err := os.ReadFile(outside); err != nil || string(content) != "DO NOT CHANGE\n" {
		t.Fatalf("external symlink target changed: %q %v", content, err)
	}
}
