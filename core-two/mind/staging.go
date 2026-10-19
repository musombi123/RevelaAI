package mind

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	rvx "revela-mind.local/core-two/rvx"
	zeroRVX "usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

const (
	maxStagingObjectiveBytes = 4096
	maxStagingReasonBytes    = 2048
)

type proposalSafetyEvidence struct {
	CoreOneGuardianPassed  bool   `json:"core_one_guardian_passed"`
	CoreZeroPolicyStatus   string `json:"core_zero_policy_status"`
	CoreZeroRVLangPassed   bool   `json:"core_zero_rv_lang_probe_passed"`
	CoreZeroRadarPassed    bool   `json:"core_zero_radar_probe_passed"`
	RVXProbePassed         bool   `json:"rvx_probe_passed"`
	RVXProbeNote           string `json:"rvx_probe_note"`
	RadarRecommendation    string `json:"radar_recommendation"`
	RadarEvidenceSynthetic bool   `json:"radar_evidence_synthetic"`
	CandidateSourceExecuted bool  `json:"candidate_source_executed"`
	AutomaticMerge         bool   `json:"automatic_merge"`
}

func (s *Service) stageMutationBatch(
	objective string,
	evaluations []CandidateEvaluation,
	bench graphBenchmark,
) (string, int, error) {
	if s == nil {
		return "", 0, errors.New("Core-Two service is required")
	}

	if err := validateStagingText(objective, maxStagingObjectiveBytes); err != nil {
		return "", 0, fmt.Errorf("invalid evolution objective: %w", err)
	}

	mutationRoot := filepath.Join(s.CoreRoot, "mutations")
	if !directoryExists(s.CoreRoot) || !directoryExists(mutationRoot) {
		return "", 0, errors.New("Core-Two mutation directory is missing or unsafe")
	}

	// Screen the objective and validate policy before creating staging files.
	allowed, reason := s.guardianDecision(objective)
	if !allowed {
		return "", 0, s.rejectAndAudit("objective", objective, reason)
	}

	safety, err := checkProposalSafety(s)
	if err != nil {
		return "", 0, fmt.Errorf(
			"proposal safety preflight failed before mutation staging: %w",
			err,
		)
	}

	// Validate every static candidate, and screen its purpose and source,
	// before creating the first staging directory.
	for _, spec := range candidateCatalog {
		if err := validateCandidateSource(spec); err != nil {
			return "", 0, fmt.Errorf(
				"candidate %q failed source validation: %w",
				spec.ID,
				err,
			)
		}

		combined := objective + "\n" + spec.Purpose + "\n" + spec.Source
		allowed, reason := s.guardianDecision(combined)
		if !allowed {
			return "", 0, s.rejectAndAudit(
				"candidate_source",
				spec.Source,
				reason,
			)
		}
	}

	evalByID := make(map[string]CandidateEvaluation, len(evaluations))
	for _, evaluation := range evaluations {
		if strings.TrimSpace(evaluation.ID) == "" {
			return "", 0, errors.New("candidate evaluation contains an empty ID")
		}
		if _, exists := evalByID[evaluation.ID]; exists {
			return "", 0, fmt.Errorf(
				"duplicate candidate evaluation ID %q",
				evaluation.ID,
			)
		}
		evalByID[evaluation.ID] = evaluation
	}

	qualified := make([]struct {
		spec       candidateSpec
		evaluation CandidateEvaluation
	}, 0, len(candidateCatalog))

	for _, spec := range candidateCatalog {
		evaluation, exists := evalByID[spec.ID]
		if !exists {
			continue
		}
		if !evaluation.Passed {
			continue
		}

		qualified = append(qualified, struct {
			spec       candidateSpec
			evaluation CandidateEvaluation
		}{
			spec:       spec,
			evaluation: evaluation,
		})
	}

	if len(qualified) == 0 {
		return "", 0, ErrNoQualifiedMutation
	}

	batchID := "batch-" + time.Now().UTC().Format("20060102T150405.000000000Z")

	stagingRoot := filepath.Join(mutationRoot, ".staging-"+batchID)
	finalRoot := filepath.Join(mutationRoot, batchID)

	// Mkdir, rather than MkdirAll, avoids silently following an existing
	// staging directory or accepting an already-created staging name.
	if err := os.Mkdir(stagingRoot, 0o700); err != nil {
		return "", 0, fmt.Errorf("create mutation staging directory: %w", err)
	}

	cleanup := true
	defer func() {
		if cleanup {
			removeOwnedStagingDirectory(mutationRoot, stagingRoot)
		}
	}()

	for _, item := range qualified {
		spec := item.spec
		evaluation := item.evaluation

		dir := filepath.Join(stagingRoot, spec.ID)
		if err := os.Mkdir(dir, 0o700); err != nil {
			return "", 0, fmt.Errorf(
				"create staging directory for %q: %w",
				spec.ID,
				err,
			)
		}

		meta := map[string]any{
			"id":                          spec.ID,
			"category":                    spec.Category,
			"purpose":                     spec.Purpose,
			"objective":                   objective,
			"status":                      "qualified_pending_human_review",
			"evaluation_passed":           true,
			"candidate_source_is_static_template": true,
			"candidate_source_executed_by_stager": false,
			"repository_sourced_code_execution":   false,
			"os_level_sandbox":                    false,
			"source_core":                         "core-one",
			"requires_human_merge":                true,
			"test_file":                           "library_test.go",
			"rvx_protection_required":             true,
			"rvx_probe_passed":                    safety.RVXProbePassed,
			"safety_preflight":                    safety,
			"evaluation":                          evaluation,
			"benchmark_fixture_only":              bench.FixtureOnly,
		}

		if spec.ID == "graph-indexed" {
			meta["offline_vault_fixture_benchmark"] = bench
		}

		if err := writeJSONFile(
			filepath.Join(dir, "mutation.json"),
			meta,
			0o600,
		); err != nil {
			return "", 0, fmt.Errorf(
				"write mutation metadata for %q: %w",
				spec.ID,
				err,
			)
		}

		if err := writeNewFile(
			filepath.Join(dir, "library.go"),
			[]byte(spec.Source),
			0o600,
		); err != nil {
			return "", 0, fmt.Errorf(
				"write candidate source for %q: %w",
				spec.ID,
				err,
			)
		}

		if err := writeNewFile(
			filepath.Join(dir, "library_test.go"),
			[]byte(sharedCandidateTest),
			0o600,
		); err != nil {
			return "", 0, fmt.Errorf(
				"write candidate test template for %q: %w",
				spec.ID,
				err,
			)
		}
	}

	// Do not overwrite an existing batch, even if it appears empty.
	if _, err := os.Lstat(finalRoot); err == nil {
		return "", 0, errors.New("mutation batch destination already exists")
	} else if !os.IsNotExist(err) {
		return "", 0, err
	}

	if err := os.Rename(stagingRoot, finalRoot); err != nil {
		return "", 0, fmt.Errorf("commit staged mutation batch: %w", err)
	}

	cleanup = false
	return batchID, len(qualified), nil
}

func (s *Service) stageEvolution(
	toolName string,
	objective string,
	selected CandidateEvaluation,
	batchID string,
	evaluations []CandidateEvaluation,
	bench graphBenchmark,
) (string, string, error) {
	if s == nil {
		return "", "", errors.New("Core-Two service is required")
	}

	if !validName(toolName) {
		return "", "", errors.New("invalid tool name")
	}
	if err := validateStagingText(objective, maxStagingObjectiveBytes); err != nil {
		return "", "", fmt.Errorf("invalid evolution objective: %w", err)
	}
	if !validBatchID(batchID) {
		return "", "", errors.New("invalid mutation batch ID")
	}
	if !validName(selected.ID) {
		return "", "", errors.New("invalid selected mutation ID")
	}
	if !selected.Passed {
		return "", "", ErrNoQualifiedMutation
	}

	// Confirm that the selected candidate was actually evaluated and passed.
	foundSelected := false
	qualifiedCount := 0

	for _, evaluation := range evaluations {
		if evaluation.Passed {
			qualifiedCount++
		}
		if evaluation.ID == selected.ID && evaluation.Passed {
			foundSelected = true
		}
	}

	if !foundSelected {
		return "", "", errors.New(
			"selected mutation is not present as a passing candidate evaluation",
		)
	}

	if qualifiedCount == 0 {
		return "", "", ErrNoQualifiedMutation
	}

	spec, ok := sourceFor(selected.ID)
	if !ok {
		return "", "", errors.New("selected mutation source disappeared")
	}

	if err := validateCandidateSource(spec); err != nil {
		return "", "", fmt.Errorf("selected mutation failed validation: %w", err)
	}

	// Defense in depth: screen the objective and the chosen source again at
	// the point where the final evolution proposal is assembled.
	allowed, reason := s.guardianDecision(objective)
	if !allowed {
		return "", "", s.rejectAndAudit("evolution_objective", objective, reason)
	}

	combined := objective + "\n" + spec.Purpose + "\n" + spec.Source
	allowed, reason = s.guardianDecision(combined)
	if !allowed {
		return "", "", s.rejectAndAudit(
			"evolution_source",
			spec.Source,
			reason,
		)
	}

	safety, err := checkProposalSafety(s)
	if err != nil {
		return "", "", fmt.Errorf(
			"evolution safety preflight failed: %w",
			err,
		)
	}

	evolutionRoot := filepath.Join(s.CoreRoot, "evolutions")
	if !directoryExists(evolutionRoot) {
		return "", "", errors.New("Core-Two evolution directory is missing or unsafe")
	}

	version, err := nextEvolutionVersion(evolutionRoot)
	if err != nil {
		return "", "", fmt.Errorf("allocate evolution version: %w", err)
	}

	staging := filepath.Join(evolutionRoot, ".staging-"+version)
	finalPath := filepath.Join(evolutionRoot, version)

	if err := os.Mkdir(staging, 0o700); err != nil {
		return "", "", fmt.Errorf("create evolution staging directory: %w", err)
	}

	cleanup := true
	defer func() {
		if cleanup {
			removeOwnedStagingDirectory(evolutionRoot, staging)
		}
	}()

	if err := writeNewFile(
		filepath.Join(staging, "new_library.go"),
		[]byte(spec.Source),
		0o600,
	); err != nil {
		return "", "", fmt.Errorf("write proposed library: %w", err)
	}

	if err := writeNewFile(
		filepath.Join(staging, "rvx_protection.go"),
		[]byte(rvxProposalSource),
		0o600,
	); err != nil {
		return "", "", fmt.Errorf("write RVX protection proposal: %w", err)
	}

	observedInventions := 0
	inventionsWithEvidence := 0

	if s.One == nil {
		return "", "", errors.New("Core-One invention observer is unavailable")
	}

	items, err := s.One.ListInventions()
	if err != nil {
		return "", "", fmt.Errorf("observe Core-One inventions: %w", err)
	}
	observedInventions = len(items)

	for _, item := range items {
		name, _ := item["name"].(string)
		if !validName(name) {
			continue
		}

		raw, readErr := readMindFileWithinRoot(
			s.OneRoot,
			filepath.Join("inventions", name, "evidence.json"),
			maxEvidenceBytes,
		)
		if readErr != nil {
			continue
		}

		var record map[string]any
		if jsonErr := json.Unmarshal(raw, &record); jsonErr == nil && record != nil {
			inventionsWithEvidence++
		}
	}

	libraryInventory := s.coreOneLibraryInventory()

	evidence := map[string]any{
		"schema_version": "usect-two.evolution-evidence.v1",
		"created_at":     time.Now().UTC(),
		"version":        version,
		"tool_name":      toolName,
		"objective":      objective,
		"status":         "await_merge",
		"selected_mutation": selected.ID,
		"mutation_batch":    batchID,
		"mutation_count":    qualifiedCount,
		"candidate_count_evaluated": len(evaluations),
		"candidate_evaluations":     evaluations,
		"benchmark":                 bench,
		"core_one_library_inventory": libraryInventory,
		"learning_feedback_scores":   s.learningScores(),

		"observed_core_one_invention_count": observedInventions,
		"core_one_invention_evidence_record_count": inventionsWithEvidence,
		"historical_core_one_invention_count": inventionsWithEvidence,

		"time_to_invent_ms":   nil,
		"bom_cost_kes":        nil,
		"human_merge_time_ms": nil,
		"fixture_only":        true,

		"safety": map[string]any{
			"core_two_guardian": safety.CoreOneGuardianPassed,
			"core_one_guardian": safety.CoreOneGuardianPassed,
			"core_zero_library_probe": map[string]any{
				"rv_lang_passed": safety.CoreZeroRVLangPassed,
				"radar_passed":   safety.CoreZeroRadarPassed,
				"radar_recommendation": safety.RadarRecommendation,
				"evidence_synthetic": safety.RadarEvidenceSynthetic,
			},
			"core_zero_dedicated_guardian_policy_file_status": safety.CoreZeroPolicyStatus,
			"candidate_source_execution_by_stager": false,
			"repository_sourced_code_executed": false,
			"os_level_sandbox": false,
			"automatic_merge": false,
			"automatic_installation": false,
		},

		"rvx_protection": map[string]any{
			"proposal": "AES-256-GCM authenticated encryption with externally managed key material",
			"runtime_probe_passed": safety.RVXProbePassed,
			"runtime_probe_note": safety.RVXProbeNote,
			"staged_proposal_source_executed": false,
			"baseline_encryption_protection_present": false,
			"candidate_primitive": "AES-256-GCM",
			"external_key_required": true,
			"tamper_detection_tested_by_runtime_probe": safety.RVXProbePassed,
			"staged_source_independently_verified": false,
			"numeric_security_score": nil,
			"uncopyable_forever_claim": false,
		},

		"provenance": map[string]any{
			"fixture_only": true,
			"production_invention_time_verified": false,
			"production_bom_savings_verified": false,
			"human_merge_time_verified": false,
			"source_revisions_recorded": false,
			"independent_reproduction_confirmed": false,
		},
	}

	if err := writeJSONFile(
		filepath.Join(staging, "evidence.json"),
		evidence,
		0o600,
	); err != nil {
		return "", "", fmt.Errorf("write evolution evidence: %w", err)
	}

	improvement := fmt.Sprintf(
		"# Core-Two Improvement Report — %s\n\n"+
			"- **Status:** staged for explicit human review; not activated in Core-One.\n"+
			"- **Selected proposal:** `%s` (`%s`).\n"+
			"- **Mutation batch:** `%s`.\n"+
			"- **Qualified candidates:** %d of %d evaluated.\n"+
			"- **Benchmark fixture:** `%s`, %d nodes, %d edges, %d replay rounds.\n"+
			"- **Recorded graph-phase improvement:** %.2f%% based on the supplied benchmark measurements.\n"+
			"- **Baseline time:** %d ns/round; candidate time: %d ns/round; measured ratio: %.2fx.\n"+
			"- **Scope limitation:** synthetic traversal microbenchmark only; not end-to-end invention time or proof of a production improvement.\n"+
			"- **Observed Core-One invention records:** %d.\n"+
			"- **Core-One inventions with readable JSON evidence records:** %d. This count does not independently validate their provenance.\n"+
			"- **Production invention time, KES BOM cost, and human merge time:** unknown/null.\n"+
			"- **RVX:** the runtime probe result is recorded separately; the staged RVX proposal source has not itself been independently verified.\n"+
			"- **Safety:** candidate screening and integration probes were performed before proposal directories were created. No automatic merge occurred.\n\n"+
			"See `evidence.json` and `AWAIT_MERGE.md` for review requirements.\n",
		version,
		selected.ID,
		selected.Category,
		batchID,
		qualifiedCount,
		len(evaluations),
		bench.FixtureID,
		bench.NodeCount,
		bench.EdgeCount,
		bench.ReplayRounds,
		bench.SpeedupPercent,
		bench.BaselineNS,
		bench.CandidateNS,
		bench.Improvement,
		observedInventions,
		inventionsWithEvidence,
	)

	if err := writeNewFile(
		filepath.Join(staging, "improvement_report.md"),
		[]byte(improvement),
		0o600,
	); err != nil {
		return "", "", fmt.Errorf("write improvement report: %w", err)
	}

	await := fmt.Sprintf(
		"# AWAIT_MERGE — %s\n\n"+
			"This evolution is a review proposal only. It is not activated in Core-One.\n\n"+
			"## Required review\n\n"+
			"1. Review `new_library.go`, `rvx_protection.go`, candidate sources, and `evidence.json` line by line.\n"+
			"2. Re-run applicable tests in isolated CI with a pinned Go version and no production credentials.\n"+
			"3. Verify the exact baseline and candidate revisions. Repeat historical invention benchmarks when sufficient real receipts exist; the current measurement is a synthetic fixture only.\n"+
			"4. Obtain verified supplier quotations before making any KES savings claim.\n"+
			"5. Review the Core-Zero Guardian policy status with the Core-Zero maintainer. An absent policy file is a documented gap, not a successful policy validation.\n"+
			"6. Review RVX key custody, rotation, recovery, nonce handling, and compatibility. The staged RVX source has not been independently executed or certified by this proposal process.\n"+
			"7. Obtain appropriate human review before making Kenya-law, KEBS, or Data Protection compliance claims.\n"+
			"8. Record the authorized owner's explicit decision and the exact approved revision.\n\n"+
			"## Approval boundary\n\n"+
			"- No automatic candidate execution.\n"+
			"- No automatic installation or hardware activation.\n"+
			"- No automatic merge into Core-One or Core-Zero.\n"+
			"- No claim of absolute uncopyability.\n\n"+
			"## Staged paths\n\n"+
			"- `core-two/mutations/%s/`\n"+
			"- `core-two/evolutions/%s/new_library.go`\n"+
			"- `core-two/evolutions/%s/rvx_protection.go`\n"+
			"- `core-two/evolutions/%s/evidence.json`\n"+
			"- `core-two/evolutions/%s/improvement_report.md`\n",
		version,
		batchID,
		version,
		version,
		version,
		version,
	)

	if err := writeNewFile(
		filepath.Join(staging, "AWAIT_MERGE.md"),
		[]byte(await),
		0o600,
	); err != nil {
		return "", "", fmt.Errorf("write merge review instructions: %w", err)
	}

	if _, err := os.Lstat(finalPath); err == nil {
		return "", "", errors.New("evolution destination already exists")
	} else if !os.IsNotExist(err) {
		return "", "", err
	}

	if err := os.Rename(staging, finalPath); err != nil {
		return "", "", fmt.Errorf("commit staged evolution: %w", err)
	}

	cleanup = false

	return version, filepath.ToSlash(filepath.Join(
		"core-two",
		"evolutions",
		version,
		"AWAIT_MERGE.md",
	)), nil
}

func (s *Service) rejectAndAudit(
	stage string,
	source string,
	reason string,
) error {
	if s == nil {
		return fmt.Errorf("%w: service unavailable", ErrGuardianBlocked)
	}

	if strings.TrimSpace(reason) == "" {
		reason = "policy did not authorize this proposal"
	}

	if err := s.logBlocked(stage, source, reason); err != nil {
		return fmt.Errorf(
			"%w: audit logging failed; proposal was not staged: %v",
			ErrGuardianBlocked,
			err,
		)
	}

	return fmt.Errorf(
		"%w at stage %q: %s",
		ErrGuardianBlocked,
		stage,
		reason,
	)
}

func validateStagingText(value string, maximum int) error {
	if !utf8.ValidString(value) {
		return errors.New("text is not valid UTF-8")
	}
	if strings.TrimSpace(value) == "" {
		return errors.New("text must not be empty")
	}
	if len(value) > maximum {
		return fmt.Errorf("text exceeds %d bytes", maximum)
	}
	if strings.ContainsRune(value, '\x00') {
		return errors.New("text contains a NUL byte")
	}

	return nil
}

func validBatchID(batchID string) bool {
	if !strings.HasPrefix(batchID, "batch-") || len(batchID) > 80 {
		return false
	}

	for _, r := range batchID {
		if !(r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			r == '-' || r == '_' || r == '.') {
			return false
		}
	}

	return true
}

// checkProposalSafety records live dependency-probe results and validates the
// optional Core-Zero Guardian policy. A missing Core-Zero policy is reported
// as a gap; an existing unreadable or invalid file blocks staging.
func checkProposalSafety(s *Service) (proposalSafetyEvidence, error) {
	var result proposalSafetyEvidence

	if s == nil {
		return result, errors.New("service is nil")
	}

	result.CandidateSourceExecuted = false
	result.AutomaticMerge = false

	raw, err := readMindFileWithinRoot(
		s.ZeroRoot,
		filepath.Join("guardian", "rules.yaml"),
		maxPolicyBytes,
	)

	switch {
	case os.IsNotExist(err):
		result.CoreZeroPolicyStatus = "missing_policy_gap_reported"

	case err != nil:
		return result, fmt.Errorf(
			"Core-Zero Guardian policy is unreadable or unsafe: %w",
			err,
		)

	default:
		if err := validateZeroGuardianPolicy(raw); err != nil {
			return result, fmt.Errorf(
				"existing Core-Zero Guardian policy is invalid: %w",
				err,
			)
		}
		result.CoreZeroPolicyStatus = "present_and_valid"
	}

	compiled, err := zeroRVX.Compile("scan")
	if err != nil {
		return result, fmt.Errorf("Core-Zero RV Lang probe failed: %w", err)
	}
	if strings.TrimSpace(compiled.Status) == "" {
		return result, errors.New("Core-Zero RV Lang probe returned an empty status")
	}
	result.CoreZeroRVLangPassed = true

	comparison, err := radar.Compare(
		radar.Evidence{
			Name:       "proposal_integration_probe",
			Version:    "v0.1.0",
			Benchmark:  100,
			Source:     "synthetic integration probe",
			EvidenceID: "core-zero-probe-baseline",
		},
		radar.Evidence{
			Name:       "proposal_integration_probe",
			Version:    "v0.2.0",
			Benchmark:  140,
			Source:     "synthetic integration probe",
			EvidenceID: "core-zero-probe-candidate",
		},
	)
	if err != nil {
		return result, fmt.Errorf("Core-Zero Radar probe failed: %w", err)
	}
	result.CoreZeroRadarPassed = true
	result.RadarRecommendation = comparison.Recommendation
	result.RadarEvidenceSynthetic = true

	protect, note := rvx.Probe()
	result.RVXProbePassed = protect
	result.RVXProbeNote = note
	if !protect {
		return result, fmt.Errorf("RVX runtime probe failed: %s", note)
	}

	// The runtime probes above do not execute the staged proposal source.
	result.CoreOneGuardianPassed = true
	return result, nil
}

// removeOwnedStagingDirectory refuses to recursively remove paths that are
// not direct children of their expected root or are not real directories.
func removeOwnedStagingDirectory(root, staging string) {
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return
	}
	stagingAbs, err := filepath.Abs(staging)
	if err != nil {
		return
	}

	if filepath.Dir(stagingAbs) != rootAbs {
		return
	}

	info, err := os.Lstat(stagingAbs)
	if err != nil ||
		info.Mode()&os.ModeSymlink != 0 ||
		!info.IsDir() {
		return
	}

	_ = os.RemoveAll(stagingAbs)
}

const rvxProposalSource = `// Package candidate contains a proposal-only RVX protection helper.
// This file is a review artifact. It is not wired into Core-One.
package candidate

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"io"
)

const (
	RVXVersionV1 = "rvx-aead-v1"
	RVXVersionV2 = "rvx-aead-v2"
	RVXMaxPlaintext = 16 << 20
)

type RVXEnvelope struct {
	Version    string ` + "`json:\"version\"`" + `
	Nonce      string ` + "`json:\"nonce\"`" + `
	Ciphertext string ` + "`json:\"ciphertext\"`" + `
}

func SealRVX(masterKey string, plain []byte) (RVXEnvelope, error) {
	if len(masterKey) < 32 {
		return RVXEnvelope{}, errors.New("external key must be at least 32 bytes")
	}
	if len(plain) > RVXMaxPlaintext {
		return RVXEnvelope{}, errors.New("plaintext exceeds RVX size limit")
	}

	key := deriveRVXKey([]byte(masterKey))
	block, err := aes.NewCipher(key)
	if err != nil {
		return RVXEnvelope{}, errors.New("could not initialize RVX cipher")
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return RVXEnvelope{}, errors.New("could not initialize RVX authentication")
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return RVXEnvelope{}, errors.New("could not generate RVX nonce")
	}

	sealed := gcm.Seal(nil, nonce, plain, []byte(RVXVersionV2))
	return RVXEnvelope{
		Version: RVXVersionV2,
		Nonce: base64.RawStdEncoding.EncodeToString(nonce),
		Ciphertext: base64.RawStdEncoding.EncodeToString(sealed),
	}, nil
}

func OpenRVX(masterKey string, box RVXEnvelope) ([]byte, error) {
	if len(masterKey) < 32 {
		return nil, errors.New("invalid RVX envelope or key")
	}

	var key []byte
	switch box.Version {
	case RVXVersionV1:
		// Legacy format: retain read compatibility for existing v1 envelopes.
		sum := sha256.Sum256([]byte(masterKey))
		key = sum[:]
	case RVXVersionV2:
		key = deriveRVXKey([]byte(masterKey))
	default:
		return nil, errors.New("invalid RVX envelope or key")
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, errors.New("invalid RVX envelope or key")
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, errors.New("invalid RVX envelope or key")
	}

	nonce, err := base64.RawStdEncoding.DecodeString(box.Nonce)
	if err != nil || len(nonce) != gcm.NonceSize() {
		return nil, errors.New("invalid RVX envelope or key")
	}

	ciphertext, err := base64.RawStdEncoding.DecodeString(box.Ciphertext)
	if err != nil || len(ciphertext) > RVXMaxPlaintext+gcm.Overhead() {
		return nil, errors.New("invalid RVX envelope or key")
	}

	// The v1 associated-data value is preserved for compatibility.
	// Both versions authenticate the version label.
	plain, err := gcm.Open(nil, nonce, ciphertext, []byte(box.Version))
	if err != nil {
		return nil, errors.New("RVX authentication failed")
	}
	if len(plain) > RVXMaxPlaintext {
		return nil, errors.New("decrypted RVX content exceeds size limit")
	}

	return plain, nil
}

// deriveRVXKey uses domain-separated HMAC-SHA-256 extraction and expansion.
// This does not increase the entropy of a weak master key. Callers must supply
// a high-entropy external key and manage its storage and rotation securely.
func deriveRVXKey(masterKey []byte) []byte {
	extract := hmac.New(
		sha256.New,
		[]byte("revela-rvx-envelope-v2/extract"),
	)
	_, _ = extract.Write(masterKey)
	prk := extract.Sum(nil)

	expand := hmac.New(sha256.New, prk)
	_, _ = expand.Write([]byte("revela-rvx-envelope-v2/aes-256-gcm"))
	_, _ = expand.Write([]byte{1})
	return expand.Sum(nil)
}
`
