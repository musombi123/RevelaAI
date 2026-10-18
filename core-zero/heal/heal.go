// Package heal implements evidence-first, human-approved missing-file recovery.
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
	CandidatePath   string `json:"candidate_path"`
	ExpectedSHA256  string `json:"expected_sha256"`
	CandidateSHA256 string `json:"candidate_sha256"`
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

func hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func ProposeMissing(k *kernel.Kernel) (Proposal, error) {
	baseline, err := k.LoadBaseline()
	if err != nil { return Proposal{}, fmt.Errorf("record a baseline first: %w", err) }
	scan, err := k.Scan()
	if err != nil { return Proposal{}, err }
	present := map[string]bool{}
	for _, f := range scan.Files { present[f.Path] = true }
	id, err := newID()
	if err != nil { return Proposal{}, err }
	p := Proposal{ID: id, CreatedAt: time.Now().UTC(), BaselineHead: baseline.GitHead, Status: "no_missing_files", Items: []RestoreItem{}, HumanApprovalRequired: true}
	for _, f := range baseline.Files {
		if present[f.Path] { continue }
		clean, err := safeRelative(f.Path)
		if err != nil { continue }
		raw, gitErr := gitShow(k.Root, baseline.GitHead, clean)
		item := RestoreItem{Path: clean, ExpectedSHA256: f.SHA256, Status: "blocked"}
		if gitErr != nil {
			item.Note = "Git history does not contain this path at the recorded baseline revision"
		} else if hash(raw) != f.SHA256 {
			item.Note = "Git HEAD content does not match the recorded baseline hash; refusing to guess the last-good version"
		} else {
			candidateRel := filepath.ToSlash(filepath.Join("evidence", "heal", id, "candidate", clean))
			candidate := filepath.Join(k.CoreRoot, candidateRel)
			if err = os.MkdirAll(filepath.Dir(candidate), 0700); err != nil { return p, err }
			if err = os.WriteFile(candidate, raw, 0600); err != nil { return p, err }
			item.CandidatePath = filepath.ToSlash(filepath.Join("core-zero", candidateRel))
			item.CandidateSHA256 = hash(raw)
			item.Status = "candidate_staged"
			item.Note = "Restoration candidate staged inside the USECT-ZERO sandbox; target file remains untouched"
		}
		p.Items = append(p.Items, item)
	}
	if len(p.Items) > 0 { p.Status = "awaiting_human_approval"; p.SandboxEvidence = filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "proposal.json")) }
	if err = kWriteProposal(k, p); err != nil { return p, err }
	if err = k.Audit("heal_proposal_created", "local-operator", id, p.Status, map[string]any{"item_count": len(p.Items), "approved": false}); err != nil { return p, err }
	return p, nil
}
func ApproveRestore(k *kernel.Kernel, id, confirmation string) (Proposal, error) {
	if confirmation != "RESTORE_TO_REPOSITORY" { return Proposal{}, errors.New("explicit confirmation RESTORE_TO_REPOSITORY is required") }
	var p Proposal
	if err := kReadProposal(k, id, &p); err != nil { return p, err }
	if p.Status != "awaiting_human_approval" { return p, errors.New("proposal is not awaiting approval") }
	for i := range p.Items {
		item := &p.Items[i]
		if item.Status != "candidate_staged" { continue }
		rel, err := safeRelative(item.Path)
		if err != nil { return p, err }
		target := filepath.Join(k.Root, rel)
		if _, err = os.Lstat(target); err == nil { return p, fmt.Errorf("refusing to overwrite a path that now exists: %s", rel) } else if !os.IsNotExist(err) { return p, err }
		expectedPrefix := filepath.ToSlash(filepath.Join("core-zero", "evidence", "heal", id, "candidate")) + "/"
		if !strings.HasPrefix(filepath.ToSlash(item.CandidatePath), expectedPrefix) { return p, errors.New("candidate path is outside this proposal sandbox") }
		candidate := filepath.Join(k.Root, filepath.FromSlash(item.CandidatePath))
		raw, err := os.ReadFile(candidate)
		if err != nil { return p, err }
		if hash(raw) != item.CandidateSHA256 || item.CandidateSHA256 != item.ExpectedSHA256 { return p, fmt.Errorf("candidate evidence hash mismatch for %s", rel) }
		if err = os.MkdirAll(filepath.Dir(target), 0755); err != nil { return p, err }
		tmp := target + ".usect-zero.tmp"
		if err = os.WriteFile(tmp, raw, 0644); err != nil { return p, err }
		if err = os.Rename(tmp, target); err != nil { _ = os.Remove(tmp); return p, err }
		item.Status = "restored_after_approval"
		item.Note = "Whole tracked file restored from the recorded local Git baseline after explicit approval"
	}
	p.Status = "completed_after_approval"
	if err := kWriteProposal(k, p); err != nil { return p, err }
	if err := k.Audit("heal_restore_executed", "human-operator", id, p.Status, map[string]any{"confirmation": "RESTORE_TO_REPOSITORY", "restored_count": countRestored(p)}); err != nil { return p, err }
	return p, nil
}
func countRestored(p Proposal) int { n := 0; for _, i := range p.Items { if i.Status == "restored_after_approval" { n++ } }; return n }
func safeRelative(p string) (string, error) {
	if strings.TrimSpace(p) == "" || filepath.IsAbs(p) { return "", errors.New("absolute or empty path denied") }
	c := filepath.Clean(filepath.FromSlash(p))
	if c == "." || c == ".." || strings.HasPrefix(c, ".."+string(filepath.Separator)) { return "", errors.New("path escapes repository") }
	if c == "core-zero" || strings.HasPrefix(c, "core-zero"+string(filepath.Separator)) { return "", errors.New("self-recovery of USECT-ZERO control files is blocked") }
	return c, nil
}

// Git calls use fixed argument vectors, never a shell, and have no network operation.
func gitShow(root, rev, path string) ([]byte, error) {
	if strings.Contains(rev, "-") && len(rev) < 7 { return nil, errors.New("invalid revision") }
	if strings.ContainsAny(path, "\x00\n\r") || strings.HasPrefix(path, "-") { return nil, errors.New("invalid path") }
	return gitOutput(root, "show", rev+":"+filepath.ToSlash(path))
}
