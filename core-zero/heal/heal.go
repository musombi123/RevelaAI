// Package heal implements evidence-first, human-approved missing and
// modified-file recovery.
//
// A proposal is advisory until an authorized caller explicitly approves it.
// Every candidate must match the saved baseline and the Git content at the
// recorded revision. Recovery is confined to eligible repository files;
// USECT-ZERO control and evidence files cannot be restored by this module.
//
// This is a best-effort multi-file transaction over ordinary filesystem
// operations. It cannot provide filesystem-wide atomicity across multiple
// files, protect against a fully privileged concurrent local attacker, or
// guarantee that rollback succeeds after an underlying storage failure.
package heal

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"usect-zero.local/core-zero/internal/kernel"
)

const (
	maxRecoveryItems      = 100000
	maxRecoveryFileBytes  = 256 << 20
	maxProposalJSONBytes  = 16 << 20
	maxRecoveryPathBytes  = 4096
	recoveryConfirmation  = "RESTORE_TO_REPOSITORY"
	recoveryBaselineSchema = "usect-zero.baseline.v1"
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
	relative     string
	target       string
	candidate    []byte
	observed     []byte
	mode         os.FileMode
	backupRel    string
	tempPath     string
	rollbackPath string
	movedOriginal bool
	applied      bool
}

// recoveryMu serializes healing operations within this process.
//
// It is not a cross-process lock. Deployments that run multiple USECT-ZERO
// processes against one repository must add OS-level locking or transactional
// coordination before enabling simultaneous recovery requests.
var recoveryMu sync.Mutex

func hash(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func validSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size
}

// validGitCommitID accepts full SHA-1 or SHA-256 Git object IDs, not arbitrary
// revision expressions. Restricting the input avoids option and revision
// ambiguity in commands assembled by this package.
func validGitCommitID(value string) bool {
	if len(value) != 40 && len(value) != 64 {
		return false
	}
	if value != strings.ToLower(value) {
		return false
	}

	decoded, err := hex.DecodeString(value)
	return err == nil && (len(decoded) == 20 || len(decoded) == 32)
}

// ProposeMissing is retained for API compatibility. It detects both missing
// and modified files, but stages only candidates verified against the saved
// baseline and the Git object at the baseline commit.
func ProposeMissing(k *kernel.Kernel) (Proposal, error) {
	return ProposeRecovery(k)
}

// ProposeRecovery builds a recovery proposal without replacing repository
// targets. Candidate files are staged under the reserved evidence directory.
func ProposeRecovery(k *kernel.Kernel) (Proposal, error) {
	recoveryMu.Lock()
	defer recoveryMu.Unlock()

	if k == nil {
		return Proposal{}, errors.New("recovery kernel is not initialized")
	}
	if strings.TrimSpace(k.Root) == "" || strings.TrimSpace(k.CoreRoot) == "" {
		return Proposal{}, errors.New("recovery repository or state root is not configured")
	}

	baseline, err := k.LoadBaseline()
	if err != nil {
		return Proposal{}, fmt.Errorf("record a baseline first: %w", err)
	}
	if err := validateRecoveryBaseline(baseline); err != nil {
		return Proposal{}, fmt.Errorf("saved baseline failed validation: %w", err)
	}

	scan, err := k.Scan()
	if err != nil {
		return Proposal{}, fmt.Errorf("scan repository before recovery proposal: %w", err)
	}
	if err := validateManifest(
		scan.Files,
		scan.FileCount,
		scan.ManifestSHA256,
	); err != nil {
		return Proposal{}, fmt.Errorf("current scan evidence failed validation: %w", err)
	}

	current := make(map[string]kernel.FileRecord, len(scan.Files))
	for _, file := range scan.Files {
		if _, exists := current[file.Path]; exists {
			return Proposal{}, fmt.Errorf("current scan contains duplicate path %q", file.Path)
		}
		current[file.Path] = file
	}

	id, err := newID()
	if err != nil {
		return Proposal{}, err
	}

	p := Proposal{
		ID:                    id,
		CreatedAt:             time.Now().UTC(),
		BaselineHead:          baseline.GitHead,
		Status:                "no_drift_detected",
		Items:                 []RestoreItem{},
		HumanApprovalRequired: true,
	}

	stagedPaths := make([]string, 0)
	cleanupStaged := func() {
		for _, candidate := range stagedPaths {
			_ = removeEvidenceFile(k.Root, candidate)
		}
		_ = removeEvidenceFile(
			k.Root,
			path.Join("core-zero", "evidence", "heal", id, "proposal.json"),
		)
	}

	stagedCount := 0
	modifiedCount := 0
	missingCount := 0

	for _, baselineFile := range baseline.Files {
		currentFile, exists := current[baselineFile.Path]
		if exists &&
			currentFile.SHA256 == baselineFile.SHA256 &&
			currentFile.Bytes == baselineFile.Bytes {
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
			Path:           baselineFile.Path,
			TargetState:    targetState,
			ObservedSHA256: observedHash,
			ExpectedSHA256: baselineFile.SHA256,
			Status:         "blocked",
		}

		// Recovery is deliberately prohibited for reserved control and
		// evidence paths even when they appear in an older baseline.
		clean, pathErr := safeRelative(baselineFile.Path)
		if pathErr != nil {
			item.Note = "Recovery is blocked for this reserved or unsafe repository path"
			p.Items = append(p.Items, item)
			continue
		}

		raw, gitErr := gitShow(k.Root, baseline.GitHead, clean)
		if gitErr != nil {
			item.Note = "Git history does not contain a readable file at the recorded baseline revision"
			p.Items = append(p.Items, item)
			continue
		}

		if int64(len(raw)) > maxRecoveryFileBytes {
			item.Note = "Baseline candidate exceeds the configured per-file recovery size limit"
			p.Items = append(p.Items, item)
			continue
		}

		if hash(raw) != baselineFile.SHA256 || int64(len(raw)) != baselineFile.Bytes {
			item.Note = "Git content does not match the saved baseline hash or byte count; refusing to guess the last-good version"
			p.Items = append(p.Items, item)
			continue
		}

		mode, modeErr := gitFileMode(k.Root, baseline.GitHead, clean)
		if modeErr != nil {
			item.Note = "Git baseline file mode could not be verified"
			p.Items = append(p.Items, item)
			continue
		}

		candidateRel := path.Join(
			"core-zero",
			"evidence",
			"heal",
			id,
			"candidate",
			clean,
		)

		if err := writeEvidenceFile(k.Root, candidateRel, raw, 0600, false); err != nil {
			cleanupStaged()
			return Proposal{}, fmt.Errorf("stage recovery candidate for %q: %w", clean, err)
		}

		stagedPaths = append(stagedPaths, candidateRel)

		item.CandidatePath = candidateRel
		item.CandidateSHA256 = hash(raw)
		item.Status = "candidate_staged"
		item.Note = "Baseline-matching candidate staged; target remains untouched until explicit approval"

		if targetState == "modified" {
			item.Note = "Baseline-matching candidate staged; approval will recheck the current hash and preserve the existing file before replacement"
		}

		// Mode is verified now even though the public RestoreItem does not
		// have a dedicated expected-mode field. It is reverified at approval.
		_ = mode

		p.Items = append(p.Items, item)
		stagedCount++
	}

	switch {
	case stagedCount > 0:
		p.Status = "awaiting_human_approval"
	case len(p.Items) > 0:
		p.Status = "blocked_no_verified_candidates"
	default:
		p.Status = "no_drift_detected"
	}

	if len(p.Items) > 0 {
		p.SandboxEvidence = path.Join(
			"core-zero",
			"evidence",
			"heal",
			id,
			"proposal.json",
		)
	}

	if p.SandboxEvidence != "" {
		if err := writeEvidenceJSON(k.Root, p.SandboxEvidence, p, false); err != nil {
			cleanupStaged()
			return Proposal{}, fmt.Errorf("write proposal evidence: %w", err)
		}
	}

	if err := kWriteProposal(k, p); err != nil {
		cleanupStaged()
		return Proposal{}, fmt.Errorf("persist recovery proposal: %w", err)
	}

	if err := k.Audit(
		"heal_proposal_created",
		"local-operator",
		id,
		p.Status,
		map[string]any{
			"item_count":      len(p.Items),
			"candidate_count": stagedCount,
			"modified_count":  modifiedCount,
			"missing_count":   missingCount,
			"approved":        false,
			"baseline_head":   baseline.GitHead,
		},
	); err != nil {
		// A candidate proposal must not remain approvable if its creation
		// audit event could not be persisted.
		if p.Status == "awaiting_human_approval" {
			p.Status = "blocked_audit_failure"
			for i := range p.Items {
				if p.Items[i].Status == "candidate_staged" {
					p.Items[i].Note = "Blocked because proposal creation could not be audited"
				}
			}

			stateErr := kWriteProposal(k, p)
			evidenceErr := error(nil)
			if p.SandboxEvidence != "" {
				evidenceErr = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)
			}

			if stateErr != nil {
				removeErr := removeProposalRecord(k, id)
				cleanupStaged()
				return p, fmt.Errorf(
					"proposal audit failed; blocking persistence also failed: %v; proposal cleanup error: %v; audit error: %w",
					stateErr,
					removeErr,
					err,
				)
			}

			if evidenceErr != nil {
				return p, fmt.Errorf(
					"proposal is blocked after audit failure, but evidence status update failed: %v; audit error: %w",
					evidenceErr,
					err,
				)
			}
		}

		return p, fmt.Errorf("proposal was saved, but its creation audit failed: %w", err)
	}

	return p, nil
}

// ApproveRestore restores only candidates whose proposal, saved baseline,
// Git content, candidate bytes and current target state all pass validation.
//
// The API layer must authenticate the human administrator before this method
// is called. The explicit confirmation string is an additional execution gate,
// not a substitute for authentication or authorization.
func ApproveRestore(k *kernel.Kernel, id, confirmation string) (Proposal, error) {
	recoveryMu.Lock()
	defer recoveryMu.Unlock()

	if k == nil {
		return Proposal{}, errors.New("recovery kernel is not initialized")
	}

	if confirmation != recoveryConfirmation {
		return Proposal{}, fmt.Errorf(
			"explicit confirmation %s is required",
			recoveryConfirmation,
		)
	}
	if !validProposalID(id) {
		return Proposal{}, os.ErrNotExist
	}

	var p Proposal
	if err := kReadProposal(k, id, &p); err != nil {
		return p, err
	}
	if err := validateProposalForApproval(p, id); err != nil {
		return p, fmt.Errorf("recovery proposal validation failed: %w", err)
	}
	if p.Status != "awaiting_human_approval" {
		return p, errors.New("proposal is not awaiting human approval")
	}

	expectedEvidence := path.Join("core-zero", "evidence", "heal", id, "proposal.json")
	if p.SandboxEvidence != expectedEvidence {
		return p, errors.New("proposal evidence path does not match its canonical sandbox path")
	}

	// The proposal evidence snapshot must exist and match the persisted state.
	// Older proposals without this snapshot must be recreated rather than
	// approved from incomplete evidence.
	var evidenceProposal Proposal
	if err := readEvidenceJSON(k.Root, p.SandboxEvidence, &evidenceProposal); err != nil {
		return p, fmt.Errorf("proposal evidence is unavailable: %w", err)
	}
	if !sameProposalJSON(p, evidenceProposal) {
		return p, errors.New("proposal state does not match its evidence snapshot")
	}

	baseline, err := k.LoadBaseline()
	if err != nil {
		return p, fmt.Errorf("saved baseline is unavailable: %w", err)
	}
	if err := validateRecoveryBaseline(baseline); err != nil {
		return p, fmt.Errorf("saved baseline failed validation: %w", err)
	}
	if baseline.GitHead != p.BaselineHead {
		return p, errors.New("saved baseline revision changed after proposal creation; create a new proposal")
	}

	scan, err := k.Scan()
	if err != nil {
		return p, fmt.Errorf("current repository scan failed: %w", err)
	}
	if err := validateManifest(scan.Files, scan.FileCount, scan.ManifestSHA256); err != nil {
		return p, fmt.Errorf("current repository scan failed integrity validation: %w", err)
	}

	baselineByPath := make(map[string]kernel.FileRecord, len(baseline.Files))
	for _, file := range baseline.Files {
		baselineByPath[file.Path] = file
	}

	currentByPath := make(map[string]kernel.FileRecord, len(scan.Files))
	for _, file := range scan.Files {
		currentByPath[file.Path] = file
	}

	prepared := make([]*preparedRestore, 0, len(p.Items))

	cleanupTemps := func() {
		for _, item := range prepared {
			if item.tempPath != "" {
				_ = os.Remove(item.tempPath)
			}
		}
	}

	seenTargets := make(map[string]struct{}, len(p.Items))

	// Validate all candidates and targets before writing backups or changing
	// repository source files.
	for i := range p.Items {
		item := &p.Items[i]

		if item.Status != "candidate_staged" {
			continue
		}

		rel, err := safeRelative(item.Path)
		if err != nil {
			cleanupTemps()
			return p, fmt.Errorf("unsafe target path in proposal: %w", err)
		}
		if rel != item.Path {
			cleanupTemps()
			return p, errors.New("proposal target path is not in canonical repository-relative form")
		}

		if _, duplicate := seenTargets[rel]; duplicate {
			cleanupTemps()
			return p, fmt.Errorf("proposal contains duplicate target %q", rel)
		}
		seenTargets[rel] = struct{}{}

		baselineFile, ok := baselineByPath[rel]
		if !ok {
			cleanupTemps()
			return p, fmt.Errorf("target %q does not exist in the validated baseline", rel)
		}
		if baselineFile.SHA256 != item.ExpectedSHA256 {
			cleanupTemps()
			return p, fmt.Errorf("proposal expected hash does not match the baseline for %q", rel)
		}

		expectedCandidate := path.Join(
			"core-zero",
			"evidence",
			"heal",
			id,
			"candidate",
			rel,
		)
		if item.CandidatePath != expectedCandidate {
			cleanupTemps()
			return p, errors.New("candidate path does not match the proposal's canonical sandbox")
		}
		if !validSHA256(item.CandidateSHA256) ||
			item.CandidateSHA256 != item.ExpectedSHA256 {
			cleanupTemps()
			return p, fmt.Errorf("candidate metadata failed hash validation for %q", rel)
		}

		if err := verifyPathComponents(k.Root, item.CandidatePath, true); err != nil {
			cleanupTemps()
			return p, fmt.Errorf("candidate evidence path is unsafe for %q: %w", rel, err)
		}

		candidatePath := filepath.Join(k.Root, filepath.FromSlash(item.CandidatePath))
		candidate, err := readRegularFile(candidatePath, maxRecoveryFileBytes)
		if err != nil {
			cleanupTemps()
			return p, fmt.Errorf("read candidate evidence for %q: %w", rel, err)
		}
		if hash(candidate) != item.CandidateSHA256 ||
			int64(len(candidate)) != baselineFile.Bytes {
			cleanupTemps()
			return p, fmt.Errorf("candidate evidence hash or size mismatch for %q", rel)
		}

		// Re-read Git content at approval time. This prevents a locally
		// altered proposal and candidate file from changing the restoration
		// source without matching the saved baseline.
		gitBytes, err := gitShow(k.Root, baseline.GitHead, rel)
		if err != nil {
			cleanupTemps()
			return p, fmt.Errorf("revalidate Git baseline candidate %q: %w", rel, err)
		}
		if hash(gitBytes) != baselineFile.SHA256 ||
			int64(len(gitBytes)) != baselineFile.Bytes ||
			!bytes.Equal(candidate, gitBytes) {
			cleanupTemps()
			return p, fmt.Errorf("Git content no longer matches the recovery evidence for %q", rel)
		}

		mode, err := gitFileMode(k.Root, baseline.GitHead, rel)
		if err != nil {
			cleanupTemps()
			return p, fmt.Errorf("verify Git file mode for %q: %w", rel, err)
		}

		state := item.TargetState
		if state == "" {
			// Compatibility with older missing-file proposals.
			state = "missing"
		}
		if state != "missing" && state != "modified" {
			cleanupTemps()
			return p, fmt.Errorf("unsupported target state for %q", rel)
		}

		targetPath := filepath.Join(k.Root, filepath.FromSlash(rel))
		if err := verifyPathComponents(k.Root, rel, false); err != nil {
			cleanupTemps()
			return p, fmt.Errorf("target parent path is unsafe for %q: %w", rel, err)
		}

		info, statErr := os.Lstat(targetPath)

		next := &preparedRestore{
			index:     i,
			state:     state,
			relative:  rel,
			target:    targetPath,
			candidate: candidate,
			mode:      mode,
		}

		switch state {
		case "missing":
			if _, exists := currentByPath[rel]; exists {
				cleanupTemps()
				return p, fmt.Errorf("missing target appeared in the current scan: %s", rel)
			}
			if statErr == nil {
				cleanupTemps()
				return p, fmt.Errorf("refusing to overwrite a path that appeared after the proposal: %s", rel)
			}
			if !errors.Is(statErr, os.ErrNotExist) {
				cleanupTemps()
				return p, fmt.Errorf("inspect missing target %q: %w", rel, statErr)
			}

		case "modified":
			if !validSHA256(item.ObservedSHA256) {
				cleanupTemps()
				return p, fmt.Errorf("modified target has no valid observed hash: %s", rel)
			}
			if statErr != nil {
				cleanupTemps()
				return p, fmt.Errorf("modified target is no longer accessible: %s", rel)
			}
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				cleanupTemps()
				return p, fmt.Errorf("refusing to replace a non-regular or symbolic-link target: %s", rel)
			}

			observed, readErr := readRegularFile(targetPath, maxRecoveryFileBytes)
			if readErr != nil {
				cleanupTemps()
				return p, fmt.Errorf("read current target %q: %w", rel, readErr)
			}
			if hash(observed) != item.ObservedSHA256 {
				cleanupTemps()
				return p, fmt.Errorf("target changed after proposal creation: %s", rel)
			}
			if currentFile, exists := currentByPath[rel]; !exists ||
				currentFile.SHA256 != item.ObservedSHA256 {
				cleanupTemps()
				return p, fmt.Errorf("current scan evidence no longer matches the modified target: %s", rel)
			}

			next.observed = observed
			item.OriginalMode = uint32(info.Mode().Perm())
			next.backupRel = path.Join(
				"core-zero",
				"evidence",
				"heal",
				id,
				"backup",
				rel,
			)

			if item.BackupPath != "" && item.BackupPath != next.backupRel {
				cleanupTemps()
				return p, fmt.Errorf("backup path in proposal is not canonical for %q", rel)
			}
			item.BackupPath = next.backupRel
			item.BackupSHA256 = hash(observed)
		}

		prepared = append(prepared, next)
	}

	if len(prepared) == 0 {
		return p, errors.New("proposal contains no verified recovery candidates")
	}

	// Make and verify backups before beginning repository modifications.
	for _, item := range prepared {
		if item.state != "modified" {
			continue
		}
		if err := writeBackup(
			k.Root,
			item.backupRel,
			item.observed,
			p.Items[item.index].BackupSHA256,
		); err != nil {
			cleanupTemps()
			return p, fmt.Errorf("preserve original file backup: %w", err)
		}
	}

	// Persist backup metadata before any replacement so an interruption has
	// an evidence trail. This does not execute the recovery.
	if err := kWriteProposal(k, p); err != nil {
		cleanupTemps()
		return p, fmt.Errorf("persist recovery backup metadata: %w", err)
	}
	if err := writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true); err != nil {
		cleanupTemps()
		return p, fmt.Errorf("persist recovery evidence metadata: %w", err)
	}

	// A durable pre-execution audit event is required before modifying source
	// targets. If this fails, no repository target has been replaced.
	if err := k.Audit(
		"heal_restore_started",
		"human-operator",
		p.ID,
		"approved_pending_execution",
		map[string]any{
			"confirmation": recoveryConfirmation,
			"candidate_count": len(prepared),
			"baseline_head": p.BaselineHead,
		},
	); err != nil {
		cleanupTemps()
		return p, fmt.Errorf("recovery was not executed because the start audit failed: %w", err)
	}

	// Stage replacement files beside their targets. This ensures that the
	// subsequent hard link is on the same filesystem and is created without
	// overwriting an entry that appeared after our last check.
	for _, item := range prepared {
		if err := ensureTargetParents(k.Root, item.relative); err != nil {
			cleanupTemps()
			_ = k.Audit(
				"heal_restore_aborted",
				"human-operator",
				p.ID,
				"staging_failed",
				map[string]any{"reason": "target_parent_unsafe"},
			)
			return p, fmt.Errorf("target parent directory is unsafe for %q: %w", item.relative, err)
		}

		item.tempPath = ""
		tempPath, err := stageFile(filepath.Dir(item.target), item.candidate, item.mode)
		if err != nil {
			cleanupTemps()
			_ = k.Audit(
				"heal_restore_aborted",
				"human-operator",
				p.ID,
				"staging_failed",
				map[string]any{"reason": "replacement_stage_failed"},
			)
			return p, fmt.Errorf("stage replacement for %q: %w", item.relative, err)
		}
		item.tempPath = tempPath
	}

	// All target bytes and backups have been verified. Apply sequentially,
	// tracking every filesystem transition so a partial failure can be
	// rolled back in reverse order where it is safe to do so.
	var applyErr error

	for _, item := range prepared {
		if err := verifyPathComponents(k.Root, item.relative, false); err != nil {
			applyErr = fmt.Errorf("target parent changed before replacement for %q: %w", item.relative, err)
			break
		}

		switch item.state {
		case "missing":
			if _, err := os.Lstat(item.target); err == nil {
				applyErr = fmt.Errorf(
					"refusing to overwrite a path that appeared during approval: %s",
					item.relative,
				)
				break
			} else if !errors.Is(err, os.ErrNotExist) {
				applyErr = fmt.Errorf("recheck target %q: %w", item.relative, err)
				break
			}

			if err := os.Link(item.tempPath, item.target); err != nil {
				applyErr = fmt.Errorf("publish restored file %q without overwriting: %w", item.relative, err)
				break
			}

			item.applied = true

			if err := os.Remove(item.tempPath); err != nil {
				// The target is already created. Keep tempPath recorded for
				// cleanup and treat this as an execution error that requires
				// rollback or manual review.
				applyErr = fmt.Errorf("remove staging link for %q: %w", item.relative, err)
				break
			}
			item.tempPath = ""

		case "modified":
			info, err := os.Lstat(item.target)
			if err != nil {
				applyErr = fmt.Errorf("recheck modified target %q: %w", item.relative, err)
				break
			}
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				applyErr = fmt.Errorf("modified target is no longer a regular file: %s", item.relative)
				break
			}

			current, err := readRegularFile(item.target, maxRecoveryFileBytes)
			if err != nil {
				applyErr = fmt.Errorf("re-read modified target %q: %w", item.relative, err)
				break
			}
			if hash(current) != p.Items[item.index].ObservedSHA256 {
				applyErr = fmt.Errorf("modified target changed during approval: %s", item.relative)
				break
			}

			rollbackID, err := newID()
			if err != nil {
				applyErr = fmt.Errorf("create rollback identifier for %q: %w", item.relative, err)
				break
			}

			item.rollbackPath = item.target + ".usect-zero-rollback-" + rollbackID

			if _, err := os.Lstat(item.rollbackPath); err == nil {
				applyErr = fmt.Errorf("rollback destination already exists for %q", item.relative)
				break
			} else if !errors.Is(err, os.ErrNotExist) {
				applyErr = fmt.Errorf("inspect rollback destination for %q: %w", item.relative, err)
				break
			}

			if err := os.Rename(item.target, item.rollbackPath); err != nil {
				applyErr = fmt.Errorf("preserve original target %q before replacement: %w", item.relative, err)
				break
			}
			item.movedOriginal = true

			rollbackInfo, err := os.Lstat(item.rollbackPath)
			if err != nil ||
				rollbackInfo.Mode()&os.ModeSymlink != 0 ||
				!rollbackInfo.Mode().IsRegular() {
				applyErr = fmt.Errorf(
					"original target moved to an unsafe or inaccessible rollback path for %q",
					item.relative,
				)
				break
			}

			rollbackBytes, err := readRegularFile(item.rollbackPath, maxRecoveryFileBytes)
			if err != nil || hash(rollbackBytes) != p.Items[item.index].ObservedSHA256 {
				applyErr = fmt.Errorf(
					"original target changed while being moved to rollback storage: %s",
					item.relative,
				)
				break
			}

			// os.Link fails if target exists and therefore does not overwrite
			// an unexpected replacement that appeared after the original move.
			if err := os.Link(item.tempPath, item.target); err != nil {
				applyErr = fmt.Errorf("publish replacement for %q without overwriting: %w", item.relative, err)
				break
			}

			item.applied = true

			if err := os.Remove(item.tempPath); err != nil {
				applyErr = fmt.Errorf("remove staging link for %q: %w", item.relative, err)
				break
			}
			item.tempPath = ""
		}

		if applyErr != nil {
			break
		}

		// Verify the committed target before proceeding to the next file.
		restored, err := readRegularFile(item.target, maxRecoveryFileBytes)
		if err != nil || hash(restored) != p.Items[item.index].ExpectedSHA256 {
			applyErr = fmt.Errorf("restored target failed post-write verification: %s", item.relative)
			break
		}
	}

	if applyErr != nil {
		rollbackErr := rollbackPrepared(prepared)
		cleanupTemps()

		if rollbackErr != nil {
			p.Status = "recovery_inconsistent_requires_manual_review"
			for _, item := range prepared {
				if item.applied || item.movedOriginal {
					p.Items[item.index].Status = "recovery_inconsistent"
					p.Items[item.index].Note = "A recovery error occurred and automatic rollback was incomplete; inspect target, rollback copy and verified evidence backup manually"
				}
			}

			_ = kWriteProposal(k, p)
			_ = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)
			_ = k.Audit(
				"heal_restore_rollback_incomplete",
				"human-operator",
				p.ID,
				p.Status,
				map[string]any{
					"apply_error":    applyErr.Error(),
					"rollback_error": rollbackErr.Error(),
				},
			)

			return p, fmt.Errorf(
				"recovery failed and automatic rollback was incomplete; manual review is required: apply error: %v; rollback error: %w",
				applyErr,
				rollbackErr,
			)
		}

		// All target changes were reversed. Keep the proposal pending so an
		// operator can review the cause and decide whether to retry.
		p.Status = "awaiting_human_approval"
		for _, item := range prepared {
			p.Items[item.index].Status = "candidate_staged"
			p.Items[item.index].Note = "Recovery attempt failed; target changes were rolled back where verified. Review the error and evidence before retrying."
		}
		_ = kWriteProposal(k, p)
		_ = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)
		_ = k.Audit(
			"heal_restore_aborted",
			"human-operator",
			p.ID,
			"rolled_back",
			map[string]any{"reason": applyErr.Error()},
		)

		return p, fmt.Errorf("recovery was aborted; rollback completed: %w", applyErr)
	}

	// All restored targets have passed hash verification.
	for _, item := range prepared {
		restoreItem := &p.Items[item.index]
		restoreItem.Status = "restored_after_approval"

		if item.state == "modified" {
			restoreItem.Note = "Modified file replaced after approval; original bytes and hash are preserved in the evidence backup"
		} else {
			restoreItem.Note = "Missing tracked file restored from the verified Git baseline after explicit approval"
		}
	}

	p.Status = "completed_after_approval"

	if err := kWriteProposal(k, p); err != nil {
		rollbackErr := rollbackPrepared(prepared)
		cleanupTemps()

		if rollbackErr != nil {
			p.Status = "recovery_inconsistent_requires_manual_review"
			_ = kWriteProposal(k, p)
			_ = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)
			return p, fmt.Errorf(
				"completion state could not be persisted and rollback was incomplete: persistence error: %v; rollback error: %w",
				err,
				rollbackErr,
			)
		}

		p.Status = "awaiting_human_approval"
		for _, item := range prepared {
			p.Items[item.index].Status = "candidate_staged"
			p.Items[item.index].Note = "Completion could not be persisted; targets were rolled back where verified"
		}

		_ = kWriteProposal(k, p)
		_ = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)

		return p, fmt.Errorf("completion state could not be persisted; restoration was rolled back: %w", err)
	}

	if err := writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true); err != nil {
		rollbackErr := rollbackPrepared(prepared)
		cleanupTemps()

		if rollbackErr != nil {
			p.Status = "recovery_inconsistent_requires_manual_review"
			_ = kWriteProposal(k, p)
			return p, fmt.Errorf(
				"completion evidence could not be updated and rollback was incomplete: evidence error: %v; rollback error: %w",
				err,
				rollbackErr,
			)
		}

		p.Status = "awaiting_human_approval"
		for _, item := range prepared {
			p.Items[item.index].Status = "candidate_staged"
			p.Items[item.index].Note = "Completion evidence could not be updated; targets were rolled back where verified"
		}
		_ = kWriteProposal(k, p)
		return p, fmt.Errorf("completion evidence could not be persisted; restoration was rolled back: %w", err)
	}

	// The final audit is attempted while rollback copies still exist. If the
	// audit fails, do not delete those additional recovery copies.
	if err := k.Audit(
		"heal_restore_executed",
		"human-operator",
		p.ID,
		p.Status,
		map[string]any{
			"confirmation":              recoveryConfirmation,
			"restored_count":            countRestored(p),
			"backed_up_modified_count":  countBackedUp(p),
			"baseline_head":             p.BaselineHead,
		},
	); err != nil {
		for _, item := range prepared {
			if item.rollbackPath != "" && item.state == "modified" {
				p.Items[item.index].Note += "; an additional rollback copy was retained because the completion audit failed"
			}
		}
		_ = kWriteProposal(k, p)
		_ = writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true)

		return p, fmt.Errorf(
			"recovery completed and target hashes verified, but the completion audit failed; rollback copies were retained where available: %w",
			err,
		)
	}

	// Verified backups now exist under the evidence directory. Temporary
	// rollback copies beside target files can be removed.
	for _, item := range prepared {
		if item.rollbackPath == "" {
			continue
		}

		if err := removeRegularFile(item.rollbackPath); err != nil {
			p.Items[item.index].Note += "; additional rollback copy remains beside the target for manual cleanup"
		}
	}

	// Record cleanup status without changing the already-confirmed recovery.
	if err := kWriteProposal(k, p); err != nil {
		return p, fmt.Errorf("recovery completed, but final cleanup metadata could not be persisted: %w", err)
	}
	if err := writeEvidenceJSON(k.Root, p.SandboxEvidence, p, true); err != nil {
		return p, fmt.Errorf("recovery completed, but final evidence metadata could not be updated: %w", err)
	}

	return p, nil
}

func validateRecoveryBaseline(baseline kernel.Baseline) error {
	if baseline.SchemaVersion != recoveryBaselineSchema {
		return fmt.Errorf("unsupported baseline schema %q", baseline.SchemaVersion)
	}
	if baseline.CreatedAt.IsZero() {
		return errors.New("baseline timestamp is missing")
	}
	if !validGitCommitID(baseline.GitHead) {
		return errors.New("baseline Git HEAD must be a full SHA-1 or SHA-256 object ID")
	}
	if baseline.Files == nil {
		return errors.New("baseline manifest is missing")
	}
	if len(baseline.Files) > maxRecoveryItems {
		return fmt.Errorf("baseline contains too many files: %d", len(baseline.Files))
	}

	return validateManifest(
		baseline.Files,
		len(baseline.Files),
		baseline.ManifestSHA256,
	)
}

func validateManifest(
	files []kernel.FileRecord,
	count int,
	manifestSHA256 string,
) error {
	if count < 0 || count != len(files) {
		return errors.New("manifest file count is inconsistent")
	}
	if !validSHA256(manifestSHA256) {
		return errors.New("manifest SHA-256 value is invalid")
	}

	seen := make(map[string]struct{}, len(files))

	for _, file := range files {
		if err := validateManifestPath(file.Path); err != nil {
			return fmt.Errorf("invalid manifest path: %w", err)
		}
		if !validSHA256(file.SHA256) {
			return fmt.Errorf("invalid file hash for %q", file.Path)
		}
		if file.Bytes < 0 {
			return fmt.Errorf("negative file size for %q", file.Path)
		}
		if _, exists := seen[file.Path]; exists {
			return fmt.Errorf("duplicate manifest path %q", file.Path)
		}
		seen[file.Path] = struct{}{}
	}

	raw, err := json.Marshal(files)
	if err != nil {
		return fmt.Errorf("serialize manifest for verification: %w", err)
	}
	if hash(raw) != manifestSHA256 {
		return errors.New("manifest SHA-256 does not match its file records")
	}

	return nil
}

func validateManifestPath(value string) error {
	if value == "" ||
		len(value) > maxRecoveryPathBytes ||
		strings.ContainsRune(value, '\x00') ||
		strings.Contains(value, "\\") ||
		path.IsAbs(value) ||
		strings.TrimSpace(value) != value {
		return errors.New("manifest path must be a clean slash-separated relative path")
	}

	// Reject Windows volume paths even on Unix, where filepath.VolumeName
	// does not recognize Windows drive syntax.
	if len(value) >= 2 &&
		((value[0] >= 'a' && value[0] <= 'z') ||
			(value[0] >= 'A' && value[0] <= 'Z')) &&
		value[1] == ':' {
		return errors.New("manifest path must not contain a drive prefix")
	}

	clean := path.Clean(value)
	if clean != value || clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
		return errors.New("manifest path is not normalized or escapes its root")
	}

	for _, r := range value {
		if r < 0x20 || r == 0x7f {
			return errors.New("manifest path contains a control character")
		}
	}

	return nil
}

// safeRelative validates a repository target eligible for recovery.
// USECT-ZERO control files and generated/runtime directories are excluded.
func safeRelative(value string) (string, error) {
	if err := validateManifestPath(value); err != nil {
		return "", err
	}

	first := strings.Split(value, "/")[0]
	switch first {
	case "core-zero", ".git", "node_modules", "vendor", "venv", ".venv",
		"__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build":
		return "", errors.New("recovery of reserved control or generated paths is blocked")
	}

	return value, nil
}

func validateProposalForApproval(p Proposal, requestedID string) error {
	if p.ID != requestedID || !validProposalID(p.ID) {
		return errors.New("proposal identifier is invalid or inconsistent")
	}
	if p.CreatedAt.IsZero() {
		return errors.New("proposal creation time is missing")
	}
	if !validGitCommitID(p.BaselineHead) {
		return errors.New("proposal baseline revision is invalid")
	}
	if !p.HumanApprovalRequired {
		return errors.New("proposal does not declare its human approval requirement")
	}
	if p.Items == nil || len(p.Items) == 0 || len(p.Items) > maxRecoveryItems {
		return errors.New("proposal item count is invalid")
	}

	seen := make(map[string]struct{}, len(p.Items))

	for _, item := range p.Items {
		if err := validateManifestPath(item.Path); err != nil {
			return fmt.Errorf("invalid proposal target path: %w", err)
		}

		if _, duplicate := seen[item.Path]; duplicate {
			return fmt.Errorf("proposal contains duplicate target %q", item.Path)
		}
		seen[item.Path] = struct{}{}

		if !validSHA256(item.ExpectedSHA256) {
			return fmt.Errorf("proposal has an invalid expected hash for %q", item.Path)
		}

		switch item.Status {
		case "candidate_staged":
			if _, err := safeRelative(item.Path); err != nil {
				return fmt.Errorf("candidate target is not recoverable: %w", err)
			}
			if !validSHA256(item.CandidateSHA256) {
				return fmt.Errorf("candidate has an invalid hash for %q", item.Path)
			}
			if item.CandidateSHA256 != item.ExpectedSHA256 {
				return fmt.Errorf("candidate and expected hashes disagree for %q", item.Path)
			}
			if item.TargetState != "" &&
				item.TargetState != "missing" &&
				item.TargetState != "modified" {
				return fmt.Errorf("unsupported target state for %q", item.Path)
			}
			if item.TargetState == "modified" && !validSHA256(item.ObservedSHA256) {
				return fmt.Errorf("modified target has an invalid observed hash for %q", item.Path)
			}

		case "blocked":
			// A blocked item is not eligible to execute. It may be present in
			// the proposal for diagnostic transparency.
		default:
			return fmt.Errorf("unsupported proposal item status %q", item.Status)
		}
	}

	return nil
}

func gitOutput(root string, args ...string) ([]byte, error) {
	return runGit(root, args...)
}

// gitShow reads a regular-file candidate at a full immutable Git commit ID.
func gitShow(root, revision, target string) ([]byte, error) {
	if !validGitCommitID(revision) {
		return nil, errors.New("invalid full Git commit ID")
	}

	rel, err := safeRelative(target)
	if err != nil {
		return nil, fmt.Errorf("invalid Git target path: %w", err)
	}

	raw, err := gitOutput(
		root,
		"show",
		"--no-ext-diff",
		"--no-textconv",
		revision+":"+filepath.ToSlash(rel),
	)
	if err != nil {
		return nil, fmt.Errorf("read Git baseline object: %w", err)
	}

	if int64(len(raw)) > maxRecoveryFileBytes {
		return nil, errors.New("Git baseline file exceeds the recovery size limit")
	}

	return raw, nil
}

// gitFileMode obtains the file mode from the Git tree. Recovery restores only
// ordinary Git blobs and preserves the executable bit when the tree records it.
// Symlinks and submodules are explicitly rejected.
func gitFileMode(root, revision, target string) (os.FileMode, error) {
	if !validGitCommitID(revision) {
		return 0, errors.New("invalid full Git commit ID")
	}

	rel, err := safeRelative(target)
	if err != nil {
		return 0, err
	}

	raw, err := gitOutput(
		root,
		"--literal-pathspecs",
		"ls-tree",
		"-z",
		revision,
		"--",
		filepath.ToSlash(rel),
	)
	if err != nil {
		return 0, fmt.Errorf("read Git tree mode: %w", err)
	}

	entry := strings.TrimSuffix(string(raw), "\x00")
	fields := strings.SplitN(entry, "\t", 2)
	if len(fields) != 2 || fields[1] != filepath.ToSlash(rel) {
		return 0, errors.New("Git tree does not contain the exact requested path")
	}

	metadata := strings.Fields(fields[0])
	if len(metadata) != 3 {
		return 0, errors.New("Git tree entry metadata is malformed")
	}
	if metadata[1] != "blob" {
		return 0, errors.New("Git baseline entry is not a regular file blob")
	}

	switch metadata[0] {
	case "100644":
		return 0644, nil
	case "100755":
		return 0755, nil
	case "120000":
		return 0, errors.New("refusing to restore a symbolic link")
	case "160000":
		return 0, errors.New("refusing to restore a Git submodule")
	default:
		return 0, fmt.Errorf("unsupported Git file mode %q", metadata[0])
	}
}

func verifyPathComponents(root, relative string, includeLeaf bool) error {
	if err := validateManifestPath(relative); err != nil {
		return err
	}

	rootInfo, err := os.Lstat(root)
	if err != nil {
		return fmt.Errorf("inspect repository root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return errors.New("repository root is not a physical directory")
	}

	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return err
	}
	rootAbs = filepath.Clean(rootAbs)

	parts := strings.Split(filepath.FromSlash(relative), string(filepath.Separator))
	current := rootAbs
	limit := len(parts)
	if !includeLeaf {
		limit--
	}

	for index := 0; index < limit; index++ {
		current = filepath.Join(current, parts[index])

		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return fmt.Errorf("inspect path component: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("symbolic-link path components are not permitted")
		}

		if index < len(parts)-1 && !info.IsDir() {
			return errors.New("non-directory component in repository path")
		}
		if index == len(parts)-1 && includeLeaf && !info.Mode().IsRegular() {
			return errors.New("path leaf is not a regular file")
		}
	}

	target := filepath.Join(rootAbs, filepath.FromSlash(relative))
	relativeCheck, err := filepath.Rel(rootAbs, target)
	if err != nil ||
		relativeCheck == ".." ||
		filepath.IsAbs(relativeCheck) ||
		strings.HasPrefix(relativeCheck, ".."+string(filepath.Separator)) {
		return errors.New("path escapes repository root")
	}

	return nil
}

func ensureTargetParents(root, relative string) error {
	if _, err := safeRelative(relative); err != nil {
		return err
	}

	if err := verifyPathComponents(root, relative, false); err != nil {
		return err
	}

	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return err
	}

	parts := strings.Split(filepath.FromSlash(relative), string(filepath.Separator))
	current := filepath.Clean(rootAbs)

	for _, component := range parts[:len(parts)-1] {
		current = filepath.Join(current, component)

		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) {
			if err := os.Mkdir(current, 0755); err != nil && !errors.Is(err, os.ErrExist) {
				return fmt.Errorf("create missing target parent: %w", err)
			}
			info, err = os.Lstat(current)
		}
		if err != nil {
			return fmt.Errorf("inspect target parent: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return errors.New("refusing unsafe target parent directory")
		}
	}

	return verifyPathComponents(root, relative, false)
}

func readRegularFile(filename string, maximum int64) ([]byte, error) {
	info, err := os.Lstat(filename)
	if err != nil {
		return nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, errors.New("refusing to read a non-regular or symlink file")
	}
	if info.Size() > maximum {
		return nil, errors.New("file exceeds configured read size limit")
	}

	file, err := os.Open(filename)
	if err != nil {
		return nil, err
	}

	openedInfo, statErr := file.Stat()
	pathInfo, pathErr := os.Lstat(filename)
	if statErr != nil ||
		pathErr != nil ||
		pathInfo.Mode()&os.ModeSymlink != 0 ||
		!openedInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, pathInfo) {
		_ = file.Close()
		return nil, errors.New("file changed or became unsafe while opening")
	}

	raw, readErr := io.ReadAll(io.LimitReader(file, maximum+1))
	closeErr := file.Close()

	if readErr != nil {
		return nil, readErr
	}
	if closeErr != nil {
		return nil, closeErr
	}
	if int64(len(raw)) > maximum {
		return nil, errors.New("file exceeded configured read size limit")
	}

	return raw, nil
}

func validateEvidencePath(relative string) error {
	if err := validateManifestPath(relative); err != nil {
		return err
	}

	parts := strings.Split(relative, "/")
	if len(parts) < 5 ||
		parts[0] != "core-zero" ||
		parts[1] != "evidence" ||
		parts[2] != "heal" ||
		!validProposalID(parts[3]) {
		return errors.New("evidence path is outside the canonical recovery sandbox")
	}

	switch parts[4] {
	case "proposal.json":
		if len(parts) != 5 {
			return errors.New("proposal evidence path is malformed")
		}
	case "candidate", "backup":
		if len(parts) < 6 {
			return errors.New("candidate or backup path is incomplete")
		}
		remainder := strings.Join(parts[5:], "/")
		if _, err := safeRelative(remainder); err != nil {
			return err
		}
	default:
		return errors.New("unsupported recovery evidence path")
	}

	return nil
}

func ensureEvidenceParents(root, relative string) error {
	if err := validateEvidencePath(relative); err != nil {
		return err
	}

	rootInfo, err := os.Lstat(root)
	if err != nil {
		return fmt.Errorf("inspect evidence root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return errors.New("evidence root must be a physical directory")
	}

	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return err
	}

	parts := strings.Split(filepath.FromSlash(filepath.Dir(relative)), string(filepath.Separator))
	current := filepath.Clean(rootAbs)

	for _, component := range parts {
		if component == "" || component == "." {
			continue
		}
		current = filepath.Join(current, component)

		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) {
			if err := os.Mkdir(current, 0700); err != nil && !errors.Is(err, os.ErrExist) {
				return fmt.Errorf("create recovery evidence directory: %w", err)
			}
			info, err = os.Lstat(current)
		}
		if err != nil {
			return fmt.Errorf("inspect recovery evidence directory: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return errors.New("unsafe recovery evidence directory")
		}
	}

	return nil
}

// writeEvidenceFile writes a bounded regular file under the reserved recovery
// evidence directory. When replace is false, an existing path is never
// overwritten.
func writeEvidenceFile(
	root,
	relative string,
	body []byte,
	mode os.FileMode,
	replace bool,
) error {
	if int64(len(body)) > maxRecoveryFileBytes {
		return errors.New("recovery evidence exceeds the maximum file size")
	}
	if err := ensureEvidenceParents(root, relative); err != nil {
		return err
	}

	destination := filepath.Join(root, filepath.FromSlash(relative))

	info, err := os.Lstat(destination)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return errors.New("evidence destination is not a safe regular file")
		}
		if !replace {
			return errors.New("evidence destination already exists")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect evidence destination: %w", err)
	}

	if !replace {
		file, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
		if err != nil {
			return fmt.Errorf("create evidence file exclusively: %w", err)
		}

		n, writeErr := file.Write(body)
		if writeErr == nil && n != len(body) {
			writeErr = io.ErrShortWrite
		}
		if writeErr == nil {
			writeErr = file.Sync()
		}
		closeErr := file.Close()

		if writeErr != nil {
			_ = os.Remove(destination)
			return fmt.Errorf("write evidence file: %w", writeErr)
		}
		if closeErr != nil {
			_ = os.Remove(destination)
			return fmt.Errorf("close evidence file: %w", closeErr)
		}

		return nil
	}

	temp, err := os.CreateTemp(filepath.Dir(destination), ".usect-zero-evidence-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary evidence file: %w", err)
	}

	tempPath := temp.Name()
	defer os.Remove(tempPath)

	if err := temp.Chmod(mode); err != nil {
		_ = temp.Close()
		return err
	}

	n, writeErr := temp.Write(body)
	if writeErr == nil && n != len(body) {
		writeErr = io.ErrShortWrite
	}
	if writeErr == nil {
		writeErr = temp.Sync()
	}
	closeErr := temp.Close()

	if writeErr != nil {
		return fmt.Errorf("write temporary evidence file: %w", writeErr)
	}
	if closeErr != nil {
		return fmt.Errorf("close temporary evidence file: %w", closeErr)
	}

	if err := verifyPathComponents(root, relative, true); err != nil {
		return fmt.Errorf("revalidate evidence destination: %w", err)
	}

	if err := os.Rename(tempPath, destination); err != nil {
		return fmt.Errorf("replace evidence file: %w", err)
	}

	return nil
}

func writeEvidenceJSON(root, relative string, value any, replace bool) error {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return fmt.Errorf("serialize recovery evidence: %w", err)
	}
	encoded = append(encoded, '\n')

	if int64(len(encoded)) > maxProposalJSONBytes {
		return errors.New("recovery proposal evidence exceeds its maximum size")
	}

	return writeEvidenceFile(root, relative, encoded, 0600, replace)
}

func readEvidenceJSON(root, relative string, value any) error {
	if err := validateEvidencePath(relative); err != nil {
		return err
	}
	if value == nil {
		return errors.New("recovery evidence destination is nil")
	}
	if err := verifyPathComponents(root, relative, true); err != nil {
		return err
	}

	filename := filepath.Join(root, filepath.FromSlash(relative))
	raw, err := readRegularFile(filename, maxProposalJSONBytes)
	if err != nil {
		return err
	}

	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(value); err != nil {
		return fmt.Errorf("decode recovery evidence: %w", err)
	}

	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return errors.New("recovery evidence must contain one JSON value")
		}
		return fmt.Errorf("invalid trailing recovery evidence: %w", err)
	}

	return nil
}

func sameProposalJSON(a, b Proposal) bool {
	left, errLeft := json.Marshal(a)
	right, errRight := json.Marshal(b)
	return errLeft == nil && errRight == nil && bytes.Equal(left, right)
}

func removeEvidenceFile(root, relative string) error {
	if err := validateEvidencePath(relative); err != nil {
		return err
	}

	filename := filepath.Join(root, filepath.FromSlash(relative))
	info, err := os.Lstat(filename)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("refusing to remove unsafe evidence path")
	}

	return os.Remove(filename)
}

func removeProposalRecord(k *kernel.Kernel, id string) error {
	if k == nil || !validProposalID(id) {
		return errors.New("invalid proposal removal request")
	}

	relative := filepath.Join("state", "proposals", "heal-"+id+".json")
	filename, err := healManagedFile(k.CoreRoot, relative, false)
	if err != nil {
		return err
	}

	info, err := os.Lstat(filename)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("refusing to remove unsafe proposal record")
	}

	return os.Remove(filename)
}

// writeBackup preserves a modified file in the proposal's reserved backup
// directory and verifies the resulting content hash.
func writeBackup(root, relative string, body []byte, expectedHash string) error {
	if !validSHA256(expectedHash) || hash(body) != expectedHash {
		return errors.New("backup content does not match the expected hash")
	}
	if int64(len(body)) > maxRecoveryFileBytes {
		return errors.New("backup exceeds the configured maximum size")
	}

	if err := ensureEvidenceParents(root, relative); err != nil {
		return err
	}

	filename := filepath.Join(root, filepath.FromSlash(relative))

	if _, err := os.Lstat(filename); err == nil {
		if err := verifyPathComponents(root, relative, true); err != nil {
			return err
		}
		existing, err := readRegularFile(filename, maxRecoveryFileBytes)
		if err != nil {
			return err
		}
		if hash(existing) != expectedHash || !bytes.Equal(existing, body) {
			return errors.New("existing backup path contains different bytes")
		}
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}

	if err := writeEvidenceFile(root, relative, body, 0600, false); err != nil {
		return err
	}

	if err := verifyPathComponents(root, relative, true); err != nil {
		return fmt.Errorf("verify backup destination: %w", err)
	}
	saved, err := readRegularFile(filename, maxRecoveryFileBytes)
	if err != nil {
		return err
	}
	if hash(saved) != expectedHash {
		return errors.New("backup verification failed")
	}

	return nil
}

func stageFile(directory string, body []byte, mode os.FileMode) (string, error) {
	if int64(len(body)) > maxRecoveryFileBytes {
		return "", errors.New("replacement exceeds configured maximum size")
	}
	if mode != 0644 && mode != 0755 {
		return "", errors.New("unsupported recovery file mode")
	}

	info, err := os.Lstat(directory)
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("replacement staging directory is unsafe")
	}

	file, err := os.CreateTemp(directory, ".usect-zero-recovery-*")
	if err != nil {
		return "", err
	}

	filename := file.Name()

	if err := file.Chmod(mode); err != nil {
		_ = file.Close()
		_ = os.Remove(filename)
		return "", err
	}

	n, writeErr := file.Write(body)
	if writeErr == nil && n != len(body) {
		writeErr = io.ErrShortWrite
	}
	if writeErr == nil {
		writeErr = file.Sync()
	}
	closeErr := file.Close()

	if writeErr != nil {
		_ = os.Remove(filename)
		return "", writeErr
	}
	if closeErr != nil {
		_ = os.Remove(filename)
		return "", closeErr
	}

	return filename, nil
}

func rollbackPrepared(prepared []*preparedRestore) error {
	var rollbackErr error

	for index := len(prepared) - 1; index >= 0; index-- {
		item := prepared[index]

		if item.applied {
			current, err := readRegularFile(item.target, maxRecoveryFileBytes)
			if err != nil || hash(current) != hash(item.candidate) {
				rollbackErr = errors.Join(
					rollbackErr,
					fmt.Errorf("refusing to remove a target that changed during rollback: %s", item.relative),
				)
				continue
			}

			if err := os.Remove(item.target); err != nil {
				rollbackErr = errors.Join(
					rollbackErr,
					fmt.Errorf("remove restored target during rollback %s: %w", item.relative, err),
				)
				continue
			}
			item.applied = false
		}

		if item.movedOriginal && item.rollbackPath != "" {
			original, err := readRegularFile(item.rollbackPath, maxRecoveryFileBytes)
			if err != nil || hash(original) != hash(item.observed) {
				rollbackErr = errors.Join(
					rollbackErr,
					fmt.Errorf("original rollback copy failed verification for %s", item.relative),
				)
				continue
			}

			if _, err := os.Lstat(item.target); err == nil {
				rollbackErr = errors.Join(
					rollbackErr,
					fmt.Errorf("refusing to overwrite unexpected target during rollback: %s", item.relative),
				)
				continue
			} else if !errors.Is(err, os.ErrNotExist) {
				rollbackErr = errors.Join(rollbackErr, err)
				continue
			}

			if err := os.Rename(item.rollbackPath, item.target); err != nil {
				rollbackErr = errors.Join(
					rollbackErr,
					fmt.Errorf("restore original target %s: %w", item.relative, err),
				)
				continue
			}

			item.movedOriginal = false
			item.rollbackPath = ""
		}
	}

	return rollbackErr
}

func removeRegularFile(filename string) error {
	info, err := os.Lstat(filename)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("refusing to remove a non-regular rollback file")
	}
	return os.Remove(filename)
}

func countRestored(p Proposal) int {
	count := 0
	for _, item := range p.Items {
		if item.Status == "restored_after_approval" {
			count++
		}
	}
	return count
}

func countBackedUp(p Proposal) int {
	count := 0
	for _, item := range p.Items {
		if item.Status == "restored_after_approval" && item.BackupPath != "" {
			count++
		}
	}
	return count
}
