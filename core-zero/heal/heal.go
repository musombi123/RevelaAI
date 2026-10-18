// Package heal implements evidence-first, human-approved missing and modified-file recovery.
package heal

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"usect-zero.local/core-zero/internal/kernel"
)

type RestoreItem struct {
	Path            string `json:"path"`
	TargetState     string `json:"target_state,omitempty"` // missing or modified
	ObservedSHA256  string `json:"observed_sha256,omitempty"`
	ExpectedSHA256  string `json:"expected_sha256"`
	CandidatePath   string `json:"candidate_path"`
	CandidateSHA256 string `json:"candidate_sha256"`
	BackupPath      string `json:"backup_path,omitempty"`
	BackupSHA256    string `json:"backup_sha256,omitempty"`
	OriginalMode    uint32 `json:"original_mode,omitempty"`
	Status          string `json:"status"`
	Note            string `json:"note,omitempty"`
}
type Proposal struct {
	ID                    string        `json:"id"`
	CreatedAt             time.Time     `json:"created_at"`
	BaselineHead          string        `json:"baseline_head"`
	Status                string        `json:"status"`
	Items                 []RestoreItem `json:"items"`
	HumanApprovalRequired bool          `json:"human_approval_required"`
	SandboxEvidence       string        `json:"sandbox_evidence"`
}

type preparedRestore struct {
	index        int
	state        string
	target       string
	candidate    []byte
	observed     []byte
	mode         os.FileMode
	backupRel    string
	tempPath     string
	rollbackPath string
	applied      bool
}

func hash(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

// ProposeMissing is retained for API compatibility. It now detects both missing
// and modified baseline files, but only stages candidates whose Git content hash
// exactly matches the saved baseline.
func ProposeMissing(k *kernel.Kernel) (Proposal, error) {
	return ProposeRecovery(k)
}

func ProposeRecovery(k *kernel.Kernel) (Proposal, error) {
	baseline, err := k.LoadBaseline()
	if err != nil {
		return Proposal{}, fmt.Errorf("record a baseline first: %w", err)
	}
	scan, err := k.Scan()
	if err != nil {
		return Proposal{}, err
	}
	current := make(map[string]kernel.FileRecord, len(scan.Files))
	for _, file := range scan.Files {
		current[file.Path] = file
	}

	id, err := newID()
	if err != nil {
		return Proposal{}, err
	}
	p := Proposal{
		ID: id, CreatedAt: time.Now().UTC(), BaselineHead: baseline.GitHead,
		Status: "no_drift_detected", Items: []RestoreItem{}, HumanApprovalRequired: true,
	}
	stagedCount := 0
	modifiedCount := 0
	missingCount := 0

	for _, baselineFile := range baseline.Files {
		currentFile, exists := current[baselineFile.Path]
		if exists && currentFile.SHA256 == baselineFile.SHA256 {
			continue
		}

		clean, pathErr := safeRelative(baselineFile.Path)
		if pathErr != nil {
			continue
		}
		targetState := "missing"
		observedHash := ""
		if exists {
			targetState = "modified"
			observedHash = currentFile.SHA256
			modifiedCount++
		} else {
			missingCount++
		}

		item := RestoreItem{
			Path: clean, TargetState: targetState, ObservedSHA256: observedHash,
			ExpectedSHA256: baselineFile.SHA256, Status: "blocked",
		}
		raw, gitErr := gitShow(k.Root, baseline.GitHead, clean)
		if gitErr != nil {
			item.Note = "Git history does not contain this path at the recorded baseline revision"
		} else if hash(raw) != baselineFile.SHA256 {
			item.Note = "Git content does not match the saved baseline hash; refusing to guess the last-good version"
		} else {
			candidateRel := filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "candidate", clean))
			if err = verifyPathComponents(k.Root, candidateRel, false); err != nil {
				return p, fmt.Errorf("candidate sandbox path is unsafe: %w", err)
			}
			candidate := filepath.Join(k.Root, filepath.FromSlash(candidateRel))
			if err = os.MkdirAll(filepath.Dir(candidate), 0700); err != nil {
				return p, err
			}
			if err = verifyPathComponents(k.Root, candidateRel, false); err != nil {
				return p, fmt.Errorf("candidate sandbox path is unsafe: %w", err)
			}
			if err = os.WriteFile(candidate, raw, 0600); err != nil {
				return p, err
			}
			item.CandidatePath = candidateRel
			item.CandidateSHA256 = hash(raw)
			item.Status = "candidate_staged"
			item.Note = "Baseline-matching candidate staged; target file remains untouched until explicit approval"
			if targetState == "modified" {
				item.Note = "Baseline-matching candidate staged; approval rechecks the current hash and saves a backup before replacement"
			}
			stagedCount++
		}
		p.Items = append(p.Items, item)
	}
	if stagedCount > 0 {
		p.Status = "awaiting_human_approval"
		p.SandboxEvidence = filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "proposal.json"))
	} else if len(p.Items) > 0 {
		p.Status = "blocked_no_verified_candidates"
		p.SandboxEvidence = filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "proposal.json"))
	}

	if err = kWriteProposal(k, p); err != nil {
		return p, err
	}
	if err = k.Audit("heal_proposal_created", "local-operator", id, p.Status, map[string]any{
		"item_count": len(p.Items), "candidate_count": stagedCount,
		"modified_count": modifiedCount, "missing_count": missingCount, "approved": false,
	}); err != nil {
		return p, err
	}
	return p, nil
}

func ApproveRestore(k *kernel.Kernel, id, confirmation string) (Proposal, error) {
	if confirmation != "RESTORE_TO_REPOSITORY" {
		return Proposal{}, errors.New("explicit confirmation RESTORE_TO_REPOSITORY is required")
	}
	var p Proposal
	if err := kReadProposal(k, id, &p); err != nil {
		return p, err
	}
	if p.Status != "awaiting_human_approval" {
		return p, errors.New("proposal is not awaiting approval")
	}

	prepared := make([]*preparedRestore, 0, len(p.Items))
	cleanupTemps := func() {
		for _, item := range prepared {
			if item.tempPath != "" {
				_ = os.Remove(item.tempPath)
			}
		}
	}

	// Validate every target and candidate before staging backups or touching targets.
	for i := range p.Items {
		item := &p.Items[i]
		if item.Status != "candidate_staged" {
			continue
		}
		rel, err := safeRelative(item.Path)
		if err != nil {
			return p, err
		}
		expectedCandidate := filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "candidate", rel))
		if filepath.ToSlash(item.CandidatePath) != expectedCandidate {
			return p, errors.New("candidate path does not match the recorded proposal sandbox")
		}
		if err = verifyPathComponents(k.Root, item.CandidatePath, true); err != nil {
			return p, errors.New("candidate path contains an unsafe or inaccessible component")
		}
		candidatePath := filepath.Join(k.Root, filepath.FromSlash(item.CandidatePath))
		candidate, err := os.ReadFile(candidatePath)
		if err != nil {
			return p, err
		}
		if hash(candidate) != item.CandidateSHA256 || item.CandidateSHA256 != item.ExpectedSHA256 {
			return p, fmt.Errorf("candidate evidence hash mismatch for %s", rel)
		}

		state := item.TargetState
		if state == "" {
			state = "missing" // compatibility with proposals created by earlier versions
		}
		target := filepath.Join(k.Root, rel)
		if err = verifyPathComponents(k.Root, rel, state == "modified"); err != nil {
			return p, fmt.Errorf("target path is unsafe: %w", err)
		}
		next := &preparedRestore{index: i, state: state, target: target, candidate: candidate, mode: 0644}
		switch state {
		case "missing":
			if _, statErr := os.Lstat(target); statErr == nil {
				return p, fmt.Errorf("refusing to overwrite a path that appeared after the proposal: %s", rel)
			} else if !os.IsNotExist(statErr) {
				return p, statErr
			}
		case "modified":
			info, statErr := os.Lstat(target)
			if statErr != nil {
				return p, fmt.Errorf("modified target is no longer present: %s", rel)
			}
			if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
				return p, fmt.Errorf("refusing to replace a non-regular or symlink target: %s", rel)
			}
			observed, readErr := os.ReadFile(target)
			if readErr != nil {
				return p, readErr
			}
			if item.ObservedSHA256 == "" || hash(observed) != item.ObservedSHA256 {
				return p, fmt.Errorf("target changed after the recovery proposal; refusing a stale replacement: %s", rel)
			}
			next.observed = observed
			next.mode = info.Mode().Perm()
			next.backupRel = filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "backup", rel))
			item.OriginalMode = uint32(info.Mode().Perm())
			item.BackupPath = next.backupRel
			item.BackupSHA256 = hash(observed)
		default:
			return p, errors.New("proposal contains an unsupported target state")
		}
		prepared = append(prepared, next)
	}
	if len(prepared) == 0 {
		return p, errors.New("proposal contains no verified recovery candidates")
	}

	// Preserve every modified target in evidence before any replacement is attempted.
	for _, item := range prepared {
		if item.state != "modified" {
			continue
		}
		if err := writeBackup(k.Root, item.backupRel, item.observed, p.Items[item.index].BackupSHA256); err != nil {
			cleanupTemps()
			return p, fmt.Errorf("could not preserve the modified file backup: %w", err)
		}
	}
	if err := kWriteProposal(k, p); err != nil {
		cleanupTemps()
		return p, err
	}

	// Stage replacement bytes beside each target so renames stay on the same filesystem.
	for _, item := range prepared {
		if err := verifyPathComponents(k.Root, filepath.ToSlash(filepath.Rel(k.Root, item.target)), false); err != nil {
			cleanupTemps()
			return p, fmt.Errorf("target parent path became unsafe: %w", err)
		}
		if err := os.MkdirAll(filepath.Dir(item.target), 0755); err != nil {
			cleanupTemps()
			return p, err
		}
		tempPath, err := stageFile(filepath.Dir(item.target), item.candidate, item.mode)
		if err != nil {
			cleanupTemps()
			return p, err
		}
		item.tempPath = tempPath
	}

	// Apply only after all candidates, target hashes, backups and staged files validate.
	applied := make([]*preparedRestore, 0, len(prepared))
	rollbackApplied := func() error {
		var rollbackErr error
		for i := len(applied) - 1; i >= 0; i-- {
			item := applied[i]
			current, readErr := os.ReadFile(item.target)
			if readErr != nil || hash(current) != hash(item.candidate) {
				rollbackErr = errors.Join(rollbackErr, fmt.Errorf("target changed during rollback: %s", item.target))
				continue
			}
			if item.state == "modified" {
				if err := os.Remove(item.target); err != nil {
					rollbackErr = errors.Join(rollbackErr, err)
					continue
				}
				if err := os.Rename(item.rollbackPath, item.target); err != nil {
					rollbackErr = errors.Join(rollbackErr, err)
					continue
				}
			} else if err := os.Remove(item.target); err != nil {
				rollbackErr = errors.Join(rollbackErr, err)
			}
			item.applied = false
		}
		return rollbackErr
	}

	for _, item := range prepared {
		rel, _ := filepath.Rel(k.Root, item.target)
		rel = filepath.ToSlash(rel)
		if err := verifyPathComponents(k.Root, rel, item.state == "modified"); err != nil {
			rollbackErr := rollbackApplied()
			cleanupTemps()
			if rollbackErr != nil {
				return p, fmt.Errorf("recovery blocked and rollback was incomplete: %v; %w", rollbackErr, err)
			}
			return p, fmt.Errorf("target path changed during approval: %w", err)
		}

		if item.state == "missing" {
			if _, err := os.Lstat(item.target); err == nil {
				rollbackErr := rollbackApplied()
				cleanupTemps()
				if rollbackErr != nil {
					return p, fmt.Errorf("recovery blocked and rollback was incomplete: %w", rollbackErr)
				}
				return p, fmt.Errorf("refusing to overwrite a path that appeared during approval: %s", rel)
			} else if !os.IsNotExist(err) {
				rollbackErr := rollbackApplied()
				cleanupTemps()
				if rollbackErr != nil {
					return p, fmt.Errorf("recovery blocked and rollback was incomplete: %v; %w", rollbackErr, err)
				}
				return p, err
			}
		} else {
			current, err := os.ReadFile(item.target)
			if err != nil || hash(current) != p.Items[item.index].ObservedSHA256 {
				rollbackErr := rollbackApplied()
				cleanupTemps()
				if rollbackErr != nil {
					return p, fmt.Errorf("target changed during approval and rollback was incomplete: %w", rollbackErr)
				}
				return p, fmt.Errorf("target changed during approval; refusing stale replacement: %s", rel)
			}
			rollbackID, err := newID()
			if err != nil {
				rollbackErr := rollbackApplied()
				cleanupTemps()
				if rollbackErr != nil {
					return p, fmt.Errorf("rollback preparation failed and rollback was incomplete: %v; %w", rollbackErr, err)
				}
				return p, err
			}
			item.rollbackPath = item.target + ".usect-zero-rollback-" + rollbackID
			if err = os.Rename(item.target, item.rollbackPath); err != nil {
				rollbackErr := rollbackApplied()
				cleanupTemps()
				if rollbackErr != nil {
					return p, fmt.Errorf("replacement blocked and rollback was incomplete: %v; %w", rollbackErr, err)
				}
				return p, err
			}
		}

		if err := os.Rename(item.tempPath, item.target); err != nil {
			if item.state == "modified" && item.rollbackPath != "" {
				if restoreErr := os.Rename(item.rollbackPath, item.target); restoreErr != nil {
					rollbackErr := rollbackApplied()
					cleanupTemps()
					if rollbackErr != nil {
						return p, fmt.Errorf("replacement failed; original target remains in rollback storage and previous changes could not be fully rolled back: %v; %w", rollbackErr, restoreErr)
					}
					return p, fmt.Errorf("replacement failed and original target could not be put back; original remains at the recorded rollback path: %v (replacement error: %w)", restoreErr, err)
				}
				item.rollbackPath = ""
			}
			rollbackErr := rollbackApplied()
			cleanupTemps()
			if rollbackErr != nil {
				return p, fmt.Errorf("replacement failed and rollback was incomplete: %v; %w", rollbackErr, err)
			}
			return p, err
		}
		item.tempPath = ""
		item.applied = true
		applied = append(applied, item)
	}

	// Evidence backups are durable; the short-lived in-tree rollback copies are removed.
	for _, item := range prepared {
		cleanupWarning := ""
		if item.state == "modified" && item.rollbackPath != "" {
			if err := os.Remove(item.rollbackPath); err != nil {
				cleanupWarning = "; an extra rollback copy remains in the target directory"
			}
		}
		p.Items[item.index].Status = "restored_after_approval"
		if item.state == "modified" {
			p.Items[item.index].Note = "Modified file replaced after approval; previous bytes and hash are preserved in the evidence backup" + cleanupWarning
		} else {
			p.Items[item.index].Note = "Missing tracked file restored from the recorded Git baseline after explicit approval"
		}
	}
	p.Status = "completed_after_approval"
	if err := kWriteProposal(k, p); err != nil {
		return p, err
	}
	if err := k.Audit("heal_restore_executed", "human-operator", p.ID, p.Status, map[string]any{
		"confirmation": "RESTORE_TO_REPOSITORY",
		"restored_count": countRestored(p),
		"backed_up_modified_count": countBackedUp(p),
	}); err != nil {
		return p, err
	}
	return p, nil
}

func writeBackup(root, rel string, body []byte, expectedHash string) error {
	if err := verifyPathComponents(root, rel, false); err != nil {
		return err
	}
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	if err := verifyPathComponents(root, rel, false); err != nil {
		return err
	}
	if existing, err := os.ReadFile(path); err == nil {
		if hash(existing) != expectedHash || hash(existing) != hash(body) {
			return errors.New("an existing backup path contains different bytes")
		}
		return nil
	} else if !os.IsNotExist(err) {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	_, writeErr := f.Write(body)
	if writeErr == nil {
		writeErr = f.Sync()
	}
	closeErr := f.Close()
	if writeErr != nil {
		_ = os.Remove(path)
		return writeErr
	}
	if closeErr != nil {
		_ = os.Remove(path)
		return closeErr
	}
	if hashOnDisk, err := os.ReadFile(path); err != nil || hash(hashOnDisk) != expectedHash {
		_ = os.Remove(path)
		return errors.New("backup verification failed")
	}
	return nil
}

func stageFile(dir string, body []byte, mode os.FileMode) (string, error) {
	f, err := os.CreateTemp(dir, ".usect-zero-recovery-*")
	if err != nil {
		return "", err
	}
	path := f.Name()
	if err = f.Chmod(mode); err == nil {
		_, err = f.Write(body)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(path)
		return "", err
	}
	return path, nil
}

func verifyPathComponents(root, rel string, includeLeaf bool) error {
	if strings.TrimSpace(rel) == "" || filepath.IsAbs(rel) {
		return errors.New("path must be relative to the repository")
	}
	clean := filepath.Clean(filepath.FromSlash(rel))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return errors.New("path escapes repository root")
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return err
	}
	parts := strings.Split(clean, string(filepath.Separator))
	limit := len(parts)
	if !includeLeaf {
		limit--
	}
	current := rootAbs
	for i := 0; i < limit; i++ {
		current = filepath.Join(current, parts[i])
		info, statErr := os.Lstat(current)
		if os.IsNotExist(statErr) {
			continue
		}
		if statErr != nil {
			return statErr
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("symlink path components are not permitted")
		}
		if i < len(parts)-1 && !info.IsDir() {
			return errors.New("non-directory parent in path")
		}
	}
	return nil
}

func countRestored(p Proposal) int {
	n := 0
	for _, item := range p.Items {
		if item.Status == "restored_after_approval" {
			n++
		}
	}
	return n
}

func countBackedUp(p Proposal) int {
	n := 0
	for _, item := range p.Items {
		if item.Status == "restored_after_approval" && item.BackupPath != "" {
			n++
		}
	}
	return n
}

func safeRelative(p string) (string, error) {
	if strings.TrimSpace(p) == "" || filepath.IsAbs(p) {
		return "", errors.New("absolute or empty path denied")
	}
	c := filepath.Clean(filepath.FromSlash(p))
	if c == "." || c == ".." || strings.HasPrefix(c, ".."+string(filepath.Separator)) {
		return "", errors.New("path escapes repository")
	}
	if c == "core-zero" || strings.HasPrefix(c, "core-zero"+string(filepath.Separator)) {
		return "", errors.New("self-recovery of USECT-ZERO control files is blocked")
	}
	return c, nil
}

// Git calls use fixed argument vectors, never a shell, and have no network operation.
func gitShow(root, rev, path string) ([]byte, error) {
	if strings.Contains(rev, "-") && len(rev) < 7 {
		return nil, errors.New("invalid revision")
	}
	if strings.ContainsAny(path, "\x00\n\r") || strings.HasPrefix(path, "-") {
		return nil, errors.New("invalid path")
	}
	return gitOutput(root, "show", rev+":"+filepath.ToSlash(path))
}
