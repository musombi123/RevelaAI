package heal

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"

	"usect-zero.local/core-zero/internal/kernel"
)

const (
	restoreConfirmation = "RESTORE_TO_REPOSITORY"
	knownGoodContent   = "VALUE = 7\n"
)

// git executes Git commands against the test repository.
func git(t *testing.T, dir string, args ...string) {
	t.Helper()

	cmdArgs := append([]string{"-C", dir}, args...)
	cmd := exec.Command("git", cmdArgs...)

	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v failed: %v\n%s", args, err, output)
	}
}

// newGitRepoWithFile creates a committed repository with a recorded baseline.
// The repository and its managed state are isolated to the test's temp directory.
func newGitRepoWithFile(t *testing.T) (string, *kernel.Kernel, string) {
	t.Helper()

	root := t.TempDir()

	git(t, root, "init", "-b", "main")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "USECT test")

	filePath := filepath.Join(root, "sample.py")
	if err := os.WriteFile(filePath, []byte(knownGoodContent), 0644); err != nil {
		t.Fatalf("create tracked file: %v", err)
	}

	git(t, root, "add", "sample.py")
	git(t, root, "commit", "-m", "known good")

	k, err := kernel.New(root)
	if err != nil {
		t.Fatalf("create kernel: %v", err)
	}

	if _, err := k.RecordBaseline(); err != nil {
		t.Fatalf("record baseline: %v", err)
	}

	return root, k, filePath
}

func readFile(t *testing.T, path string) []byte {
	t.Helper()

	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %q: %v", path, err)
	}

	return content
}

func assertFileContent(t *testing.T, path, want string) {
	t.Helper()

	got := readFile(t, path)
	if string(got) != want {
		t.Fatalf("unexpected content in %q:\n got: %q\nwant: %q", path, got, want)
	}
}

func assertFileMissing(t *testing.T, path string) {
	t.Helper()

	_, err := os.Lstat(path)
	if err == nil {
		t.Fatalf("expected %q to be absent", path)
	}
	if !os.IsNotExist(err) {
		t.Fatalf("expected %q to be absent, got stat error: %v", path, err)
	}
}

func TestDeletedTrackedFileWaitsForApproval(t *testing.T) {
	root, k, filePath := newGitRepoWithFile(t)

	if err := os.Remove(filePath); err != nil {
		t.Fatalf("remove tracked file: %v", err)
	}

	proposal, err := ProposeMissing(k)
	if err != nil {
		t.Fatalf("propose missing-file recovery: %v", err)
	}

	if proposal.Status != "awaiting_human_approval" {
		t.Fatalf("unexpected proposal status: %q", proposal.Status)
	}
	if len(proposal.Items) != 1 {
		t.Fatalf("expected one recovery item, got %d: %#v", len(proposal.Items), proposal.Items)
	}
	if proposal.Items[0].TargetState != "missing" {
		t.Fatalf("expected missing target state, got: %+v", proposal.Items[0])
	}

	// Proposal creation must not restore the missing source automatically.
	assertFileMissing(t, filePath)

	// Incorrect approval must not restore the source.
	if _, err := ApproveRestore(k, proposal.ID, "wrong"); err == nil {
		t.Fatal("expected invalid confirmation to be rejected")
	}
	assertFileMissing(t, filePath)

	// A valid confirmation authorizes the restore.
	finished, err := ApproveRestore(k, proposal.ID, restoreConfirmation)
	if err != nil {
		t.Fatalf("approve missing-file restore: %v", err)
	}

	assertFileContent(t, filePath, knownGoodContent)

	if finished.Status != "completed_after_approval" {
		t.Fatalf("unexpected final proposal status: %q", finished.Status)
	}
	if _, err := os.Stat(root); err != nil {
		t.Fatalf("repository root disappeared: %v", err)
	}
}

func TestModifiedTrackedFileGetsBackupAndRequiresApproval(t *testing.T) {
	root, k, filePath := newGitRepoWithFile(t)

	modifiedContent := "VALUE = 999\n"
	if err := os.WriteFile(filePath, []byte(modifiedContent), 0644); err != nil {
		t.Fatalf("modify tracked file: %v", err)
	}

	proposal, err := ProposeRecovery(k)
	if err != nil {
		t.Fatalf("propose recovery: %v", err)
	}

	if proposal.Status != "awaiting_human_approval" {
		t.Fatalf("unexpected proposal status: %q", proposal.Status)
	}
	if len(proposal.Items) != 1 {
		t.Fatalf("expected one recovery item, got %d: %#v", len(proposal.Items), proposal.Items)
	}

	proposedItem := proposal.Items[0]
	if proposedItem.TargetState != "modified" {
		t.Fatalf("expected modified target state, got: %+v", proposedItem)
	}
	if proposedItem.ObservedSHA256 == "" {
		t.Fatal("proposal did not record the observed target hash")
	}
	if proposedItem.Status != "candidate_staged" {
		t.Fatalf("expected candidate_staged status, got %q", proposedItem.Status)
	}

	// The current version must remain intact until approval.
	assertFileContent(t, filePath, modifiedContent)

	// Incorrect approval must leave the user's content unchanged.
	if _, err := ApproveRestore(k, proposal.ID, "wrong"); err == nil {
		t.Fatal("expected invalid confirmation to be rejected")
	}
	assertFileContent(t, filePath, modifiedContent)

	finished, err := ApproveRestore(k, proposal.ID, restoreConfirmation)
	if err != nil {
		t.Fatalf("approve modified-file restore: %v", err)
	}

	assertFileContent(t, filePath, knownGoodContent)

	if finished.Status != "completed_after_approval" {
		t.Fatalf("unexpected final status: %q", finished.Status)
	}
	if len(finished.Items) != 1 {
		t.Fatalf("expected one completed item, got %d", len(finished.Items))
	}

	restoredItem := finished.Items[0]
	if restoredItem.Status != "restored_after_approval" {
		t.Fatalf("unexpected restored item status: %+v", restoredItem)
	}
	if restoredItem.BackupPath == "" {
		t.Fatal("backup evidence path was not recorded")
	}
	if restoredItem.BackupSHA256 == "" {
		t.Fatal("backup evidence hash was not recorded")
	}

	backupPath := filepath.Join(root, filepath.FromSlash(restoredItem.BackupPath))
	backupContent := readFile(t, backupPath)

	if string(backupContent) != modifiedContent {
		t.Fatalf("backup does not preserve modified bytes:\n got: %q\nwant: %q",
			string(backupContent), modifiedContent)
	}

	backupHash := hash(backupContent)
	if backupHash != restoredItem.BackupSHA256 {
		t.Fatalf("backup hash mismatch: recorded=%s actual=%s",
			restoredItem.BackupSHA256, backupHash)
	}
	if restoredItem.BackupSHA256 != proposedItem.ObservedSHA256 {
		t.Fatalf("backup hash differs from the original observed hash: backup=%s observed=%s",
			restoredItem.BackupSHA256, proposedItem.ObservedSHA256)
	}
}

func TestModifiedTargetChangedAfterProposalIsRejected(t *testing.T) {
	_, k, filePath := newGitRepoWithFile(t)

	if err := os.WriteFile(filePath, []byte("VALUE = 8\n"), 0644); err != nil {
		t.Fatalf("modify target: %v", err)
	}

	proposal, err := ProposeRecovery(k)
	if err != nil {
		t.Fatalf("propose recovery: %v", err)
	}

	latestContent := "VALUE = 9\n"
	if err := os.WriteFile(filePath, []byte(latestContent), 0644); err != nil {
		t.Fatalf("write newer target version: %v", err)
	}

	// Approval must revalidate the target instead of overwriting a newer edit.
	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err == nil {
		t.Fatal("expected stale proposal to be rejected")
	}

	assertFileContent(t, filePath, latestContent)
}

func TestMissingTargetCreatedAfterProposalIsNotOverwritten(t *testing.T) {
	_, k, filePath := newGitRepoWithFile(t)

	if err := os.Remove(filePath); err != nil {
		t.Fatalf("remove tracked file: %v", err)
	}

	proposal, err := ProposeMissing(k)
	if err != nil {
		t.Fatalf("propose missing-file recovery: %v", err)
	}

	// Simulate another process creating the target after proposal generation.
	newContent := "VALUE = 12345\n"
	if err := os.WriteFile(filePath, []byte(newContent), 0644); err != nil {
		t.Fatalf("create new target version: %v", err)
	}

	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err == nil {
		t.Fatal("expected approval to reject a target that appeared after proposal creation")
	}

	assertFileContent(t, filePath, newContent)
}

func TestSymlinkTargetIsNotFollowed(t *testing.T) {
	_, k, filePath := newGitRepoWithFile(t)

	outsidePath := filepath.Join(t.TempDir(), "outside.py")
	outsideContent := "DO NOT CHANGE\n"
	if err := os.WriteFile(outsidePath, []byte(outsideContent), 0600); err != nil {
		t.Fatalf("create outside file: %v", err)
	}

	if err := os.Remove(filePath); err != nil {
		t.Fatalf("remove tracked file: %v", err)
	}
	if err := os.Symlink(outsidePath, filePath); err != nil {
		t.Skipf("symlinks unavailable on this host: %v", err)
	}

	proposal, err := ProposeRecovery(k)
	if err != nil {
		t.Fatalf("propose recovery for symlink target: %v", err)
	}
	if proposal.Status != "awaiting_human_approval" {
		t.Fatalf("unexpected proposal status: %q", proposal.Status)
	}

	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err == nil {
		t.Fatal("expected restore approval to reject a symlink target")
	}

	assertFileContent(t, outsidePath, outsideContent)

	info, err := os.Lstat(filePath)
	if err != nil {
		t.Fatalf("inspect symlink after rejected approval: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("expected the original symlink to remain in place")
	}
}

func TestSymlinkSwapAfterProposalIsRejected(t *testing.T) {
	_, k, filePath := newGitRepoWithFile(t)

	if err := os.WriteFile(filePath, []byte("VALUE = 500\n"), 0644); err != nil {
		t.Fatalf("modify tracked file: %v", err)
	}

	proposal, err := ProposeRecovery(k)
	if err != nil {
		t.Fatalf("propose recovery: %v", err)
	}

	outsidePath := filepath.Join(t.TempDir(), "outside.py")
	outsideContent := "EXTERNAL DATA MUST REMAIN UNCHANGED\n"
	if err := os.WriteFile(outsidePath, []byte(outsideContent), 0600); err != nil {
		t.Fatalf("create outside file: %v", err)
	}

	// Replace the target with a symlink after the proposal was created.
	if err := os.Remove(filePath); err != nil {
		t.Fatalf("remove proposed target: %v", err)
	}
	if err := os.Symlink(outsidePath, filePath); err != nil {
		t.Skipf("symlinks unavailable on this host: %v", err)
	}

	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err == nil {
		t.Fatal("expected approval to reject a symlink introduced after proposal creation")
	}

	assertFileContent(t, outsidePath, outsideContent)

	info, err := os.Lstat(filePath)
	if err != nil {
		t.Fatalf("inspect swapped target: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("the unexpected symlink should not have been followed or replaced")
	}
}

func TestCompletedProposalCannotBeReplayed(t *testing.T) {
	_, k, filePath := newGitRepoWithFile(t)

	if err := os.Remove(filePath); err != nil {
		t.Fatalf("remove tracked file: %v", err)
	}

	proposal, err := ProposeMissing(k)
	if err != nil {
		t.Fatalf("propose missing-file recovery: %v", err)
	}

	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err != nil {
		t.Fatalf("approve restore: %v", err)
	}
	assertFileContent(t, filePath, knownGoodContent)

	// A completed proposal must not be reusable as a second write authorization.
	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err == nil {
		t.Fatal("expected replay of a completed proposal to be rejected")
	}

	assertFileContent(t, filePath, knownGoodContent)
}

func TestRestorePreservesExecutableMode(t *testing.T) {
	// Git executable-bit semantics and filesystem permissions differ on Windows.
	if runtime.GOOS == "windows" {
		t.Skip("executable permission-bit assertion is not portable to Windows")
	}

	root, k, filePath := newGitRepoWithFile(t)

	if err := os.Chmod(filePath, 0755); err != nil {
		t.Fatalf("set executable permission: %v", err)
	}

	git(t, root, "add", "sample.py")
	git(t, root, "commit", "-m", "mark sample executable")

	if _, err := k.RecordBaseline(); err != nil {
		t.Fatalf("record executable baseline: %v", err)
	}

	if err := os.WriteFile(filePath, []byte("VALUE = 200\n"), 0755); err != nil {
		t.Fatalf("modify executable file: %v", err)
	}

	proposal, err := ProposeRecovery(k)
	if err != nil {
		t.Fatalf("propose executable-file recovery: %v", err)
	}

	if _, err := ApproveRestore(k, proposal.ID, restoreConfirmation); err != nil {
		t.Fatalf("approve executable-file restore: %v", err)
	}

	assertFileContent(t, filePath, knownGoodContent)

	info, err := os.Stat(filePath)
	if err != nil {
		t.Fatalf("stat restored executable: %v", err)
	}

	if info.Mode().Perm()&0111 == 0 {
		t.Fatalf("restored file is not executable: mode=%#o", info.Mode().Perm())
	}
}
