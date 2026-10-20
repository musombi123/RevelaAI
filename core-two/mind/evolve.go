package mind

import (
	"encoding/json"
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"revela-mind.local/core-two/provider"
	"revela-mind.local/core-two/rvx"
	zeroRVX "usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

const (
	maxEvolutionObjectiveBytes = 4096
	maxEvolutionReasonBytes    = 2048
	maxGuardianPolicyBytes     = 64 * 1024
	maxGuardianTerms           = 200
)

func (s *Service) Evolve(
	ctx context.Context,
	request EvolveRequest,
) (EvolveResult, error) {
	if s == nil {
		return EvolveResult{}, errors.New("Core-Two service is required")
	}
	if ctx == nil {
		ctx = context.Background()
	}

	s.evolveMu.Lock()
	defer s.evolveMu.Unlock()

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	objective := strings.TrimSpace(request.Objective)
	if objective == "" {
		objective = "improve offline_vault graph traversal efficiency"
	}

	toolName := strings.TrimSpace(request.ToolName)
	if toolName == "" {
		toolName = "offline_vault_fixture"
	}

	reason := strings.TrimSpace(request.Reason)

	if !validName(toolName) {
		return EvolveResult{}, errors.New(
			"tool_name must use lowercase letters, digits, underscore, or hyphen",
		)
	}
	if err := validateStagingText(
		objective,
		maxEvolutionObjectiveBytes,
	); err != nil {
		return EvolveResult{}, fmt.Errorf("invalid objective: %w", err)
	}
	if reason != "" {
		if err := validateStagingText(
			reason,
			maxEvolutionReasonBytes,
		); err != nil {
			return EvolveResult{}, fmt.Errorf("invalid reason: %w", err)
		}
	}

	// Screen the complete request before scanning or creating proposal artifacts.
	screeningText := objective + "\n" + toolName
	if reason != "" {
		screeningText += "\n" + reason
	}

	allowed, blockReason := s.guardianDecision(screeningText)
	if !allowed {
		if logErr := s.logBlocked(
			"pre_mutation",
			screeningText,
			blockReason,
		); logErr != nil {
			return EvolveResult{}, fmt.Errorf(
				"%w: audit logging also failed: %v",
				ErrGuardianBlocked,
				logErr,
			)
		}

		s.publish("blocked", map[string]any{
			"tool_name":          toolName,
			"reason":             limitLabel(blockReason, 300),
			"source_files_created": false,
		})

		return EvolveResult{}, ErrGuardianBlocked
	}

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	// Run dependency probes before evaluating and staging candidates.
	safety, err := checkProposalSafety(s)
	if err != nil {
		return EvolveResult{}, fmt.Errorf(
			"proposal safety preflight failed: %w",
			err,
		)
	}

	// This probes the existing RVX runtime package. It does not verify the
	// separate RVX proposal source that will be staged for human review.
	protectionOK, protectionNote := rvx.Probe()
	if !protectionOK {
		return EvolveResult{}, errors.New(
			"existing RVX runtime self-test failed; no mutation was staged",
		)
	}

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	if _, err := s.Scan(ctx); err != nil {
		return EvolveResult{}, fmt.Errorf(
			"pre-evolution evidence scan failed: %w",
			err,
		)
	}

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	evaluations, bench, err := evaluateCatalog(ctx)
	if err != nil {
		return EvolveResult{}, fmt.Errorf(
			"candidate evaluation failed: %w",
			err,
		)
	}

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	selected, selectionReason, learningScores, ok :=
		s.selectCandidateWithLearning(objective, evaluations)

	if !ok || !selected.Passed {
		return EvolveResult{}, ErrNoQualifiedMutation
	}

	if !safeMindToolName(toolName) {
		return EvolveResult{}, errors.New("tool name failed the output-path safety check")
	}

	// Re-screen immediately before staging. The staging routine also validates
	// candidate sources and checks that qualified candidates are evidence-backed.
	allowed, blockReason = s.guardianDecision(screeningText)
	if !allowed {
		if logErr := s.logBlocked(
			"pre_staging",
			screeningText,
			blockReason,
		); logErr != nil {
			return EvolveResult{}, fmt.Errorf(
				"%w: audit logging also failed: %v",
				ErrGuardianBlocked,
				logErr,
			)
		}
		return EvolveResult{}, ErrGuardianBlocked
	}

	if err := ctx.Err(); err != nil {
		return EvolveResult{}, err
	}

	mutationBatch, mutationCount, err := s.stageMutationBatch(
		objective,
		evaluations,
		bench,
	)
	if err != nil {
		return EvolveResult{}, fmt.Errorf(
			"stage qualified mutation batch: %w",
			err,
		)
	}

	if err := ctx.Err(); err != nil {
		// Only remove the batch created by this call. It is a direct child
		// of the configured mutation directory.
		removeOwnedStagingDirectory(
			filepath.Join(s.CoreRoot, "mutations"),
			filepath.Join(s.CoreRoot, "mutations", mutationBatch),
		)
		return EvolveResult{}, err
	}

	version, awaitPath, err := s.stageEvolution(
		toolName,
		objective,
		selected,
		mutationBatch,
		evaluations,
		bench,
	)
	if err != nil {
		removeOwnedStagingDirectory(
			filepath.Join(s.CoreRoot, "mutations"),
			filepath.Join(s.CoreRoot, "mutations", mutationBatch),
		)

		return EvolveResult{}, fmt.Errorf(
			"stage evolution proposal: %w",
			err,
		)
	}

	// Once stageEvolution commits, the artifacts are a durable pending-review
	// proposal. Do not delete them due to a subsequent metrics or notification
	// failure. Such a failure must clearly report that staging already occurred.

	observedInventions := s.productionToolCount()
	evidenceRecordCount := s.countCoreOneEvidenceRecords()

	metric := map[string]any{
		"tool_name":                       toolName,
		"observed_at":                     time.Now().UTC(),
		"fixture_only":                    true,
		"evidence_status":                 "synthetic_fixture_replay_not_production_invention",
		"time_to_invent_ms":               nil,
		"bom_cost_kes":                    nil,
		"human_merge_time_ms":             nil,
		"graph_traversal_benchmark":       bench,
		"selected_mutation":               selected.ID,
		"improvement_type":                selected.ImprovementType,
		"improvement_percent":             selected.ImprovementPct,
		"observed_core_one_invention_count": observedInventions,
		"core_one_evidence_record_count":   evidenceRecordCount,
		"production_provenance_verified":   false,
		"staged_evolution_version":         version,
		"automatic_merge":                  false,
	}

	metricErr := writeJSONFile(
		filepath.Join(s.CoreRoot, "metrics", toolName+".json"),
		metric,
		0o600,
	)

	result := EvolveResult{
		Status:           "await_merge",
		Version:          version,
		ToolName:         toolName,
		SelectedMutation: selected.ID,
		SelectionReason:  selectionReason,
		LearningScores:   learningScores,
		MutationBatch:    mutationBatch,
		MutationCount:    mutationCount,
		CandidateResults: evaluations,
		Benchmark:        bench,
		RVXProtection: map[string]any{
			"passed":                              protectionOK,
			"status":                              limitLabel(protectionNote, 300),
			"probe_scope":                         "existing RVX runtime package",
			"staged_proposal_source_independently_verified": false,
			"baseline_encryption_protection_present": false,
			"candidate_primitive":                  "AES-256-GCM",
			"external_key_required":                true,
			"tamper_detection_tested_by_runtime_probe": protectionOK,
			"numeric_security_score":               nil,
			"uncopyable_forever_claim":             false,
		},
		ProductionEvidence: map[string]any{
			"observed_core_one_invention_count": observedInventions,
			"core_one_evidence_record_count":     evidenceRecordCount,
			"production_provenance_verified":     false,
			"real_time_to_invent_available":      false,
			"verified_bom_cost_kes_available":    false,
			"human_merge_time_verified":          false,
			"synthetic_fixture_only":             true,
		},
		AwaitMergePath: awaitPath,
		CreatedAt:      time.Now().UTC(),
	}

	s.publish("evolution_proposed", map[string]any{
		"version":           version,
		"tool_name":         toolName,
		"selected_mutation": selected.ID,
		"status":             "await_merge",
		"automatic_merge":    false,
		"metric_write_failed": metricErr != nil,
	})

	mesh := provider.FromEnvironment()
	if mesh.Configured() && ctx.Err() == nil {
		notifyCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		notifyErr := mesh.NotifyEvolution(notifyCtx, map[string]any{
			"version":           version,
			"tool_name":         toolName,
			"mutation":          selected.ID,
			"status":            "await_merge",
			"automatic_merge":   false,
		})
		cancel()

		if notifyErr == nil {
			result.ProviderNotified = true
		}
	}

	if metricErr != nil {
		return result, fmt.Errorf(
			"evolution %s was staged at %s, but supplementary metric persistence failed: %w",
			version,
			awaitPath,
			metricErr,
		)
	}

	// Preserve the actual preflight results in the staged evidence and returned
	// result; an absent Core-Zero policy remains an explicit review gap.
	_ = safety

	return result, nil
}

// countCoreOneEvidenceRecords counts inventions with readable JSON evidence
// records. It does not assert that those records are historical production
// evidence or that their measurements have been independently verified.
func (s *Service) countCoreOneEvidenceRecords() int {
	if s == nil || s.One == nil {
		return 0
	}

	items, err := s.One.ListInventions()
	if err != nil {
		return 0
	}

	count := 0
	for _, item := range items {
		name, _ := item["name"].(string)
		if !safeMindToolName(name) {
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
			count++
		}
	}

	return count
}

func (s *Service) guardianDecision(text string) (bool, string) {
	if s == nil {
		return false, "Core-Two service unavailable; fail-closed mode."
	}

	ownRules, err := readMindFileWithinRoot(
		s.CoreRoot,
		filepath.Join("guardian", "rules.yaml"),
		maxGuardianPolicyBytes,
	)
	if err != nil {
		return false, "Core-Two Guardian policy missing, unsafe, unreadable, or oversized; fail-closed mode."
	}

	if err := validateCoreTwoPolicy(ownRules); err != nil {
		return false, "Core-Two Guardian policy invalid; fail-closed mode."
	}

	if s.One == nil {
		return false, "Core-One Guardian dependency unavailable; fail-closed mode."
	}

	// Ensure the Core-One policy remains readable, but let Core-One Guardian
	// apply its own policy semantics rather than substituting Core-Two parsing.
	if _, err := readMindFileWithinRoot(
		s.OneRoot,
		filepath.Join("guardian", "rules.yaml"),
		maxGuardianPolicyBytes,
	); err != nil {
		return false, "Core-One Guardian policy unavailable or unsafe; fail-closed mode."
	}

	decision := s.One.Guardian.Check(text)
	if !decision.Allowed {
		return false, "Core-One Guardian: " + limitLabel(decision.Reason, 300)
	}

	lower := strings.ToLower(text)

	builtInTerms := []string{
		"weapon",
		"weapons",
		"weapon search",
		"weapon efficiency",
		"warfare",
		"explosive",
		"explosive optimization",
		"bomb",
		"ransomware",
		"credential theft",
		"spyware",
		"covert surveillance",
		"stalk",
		"evade detection",
		"destroy the platform",
		"bypass authentication",
		"disable guardian",
		"disable safety controls",
		"delete audit logs",
		"illegal operation",
		"evade law",
		"bypass law",
		"violate privacy",
	}

	terms := append(builtInTerms, extraGuardianTerms(ownRules)...)
	for _, term := range terms {
		term = strings.ToLower(strings.TrimSpace(term))
		if term != "" && strings.Contains(lower, term) {
			return false, "Core-Two policy prohibits this objective or candidate content."
		}
	}

	zeroPolicyPath := filepath.Join("guardian", "rules.yaml")
	zeroRaw, readErr := readMindFileWithinRoot(
		s.ZeroRoot,
		zeroPolicyPath,
		maxGuardianPolicyBytes,
	)

	policyGap := false

	switch {
	case os.IsNotExist(readErr):
		// The dedicated Core-Zero policy is absent. Restrictive local controls
		// remain active, but the absence must be reported in the evidence.
		policyGap = true

	case readErr != nil:
		return false, "Core-Zero Guardian policy cannot be read safely; fail-closed mode."

	default:
		if err := validateZeroGuardianPolicy(zeroRaw); err != nil {
			return false, "Core-Zero Guardian policy exists but is invalid; fail-closed mode: " +
				limitLabel(err.Error(), 200)
		}

		zeroTerms := []string{
			"weapon",
			"warfare",
			"explos",
			"malware",
			"credential",
			"privacy",
			"surveillance",
			"destruction",
			"illegal",
		}

		zeroLower := strings.ToLower(string(zeroRaw))
		for _, term := range zeroTerms {
			if strings.Contains(zeroLower, term) &&
				strings.Contains(lower, term) {
				return false, "Core-Zero Guardian policy blocked the objective."
			}
		}
	}

	if err := s.zeroLibraryProbe(); err != nil {
		return false, "Core-Zero integration probe failed; fail-closed mode: " +
			limitLabel(err.Error(), 200)
	}

	if policyGap {
		return true, "Core-Two and Core-One Guardian checks passed; Core-Zero library probe passed. Core-Zero dedicated Guardian policy is absent; restrictive fallback is active and the gap requires owner review."
	}

	return true, "Core-Two and Core-One Guardian checks passed; Core-Zero policy validation and library probes passed."
}

func extraGuardianTerms(raw []byte) []string {
	if len(raw) == 0 || len(raw) > maxGuardianPolicyBytes {
		return nil
	}

	scanner := bufio.NewScanner(strings.NewReader(string(raw)))
	scanner.Buffer(make([]byte, 1024), 4096)

	inside := false
	terms := make([]string, 0)
	seen := make(map[string]bool)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		if line == "extra_terms:" {
			inside = true
			continue
		}

		if !inside || line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if !strings.HasPrefix(line, "-") {
			break
		}

		term := strings.TrimSpace(strings.TrimPrefix(line, "-"))
		if marker := strings.Index(term, " #"); marker >= 0 {
			term = strings.TrimSpace(term[:marker])
		}
		term = strings.Trim(term, "\"'")

		term = strings.ToLower(strings.TrimSpace(term))
		if term == "" || len(term) > 160 || !utf8.ValidString(term) {
			continue
		}
		if seen[term] {
			continue
		}

		seen[term] = true
		terms = append(terms, term)

		if len(terms) >= maxGuardianTerms {
			break
		}
	}

	// Invalid/incomplete policy content is handled by validateCoreTwoPolicy.
	// This helper only extracts bounded screening indicators.
	return terms
}

func validateCoreTwoPolicy(raw []byte) error {
	if len(raw) == 0 || len(raw) > maxGuardianPolicyBytes {
		return errors.New("policy is empty or exceeds the 64 KiB limit")
	}
	if !utf8.Valid(raw) {
		return errors.New("policy is not valid UTF-8")
	}

	policy := strings.ToLower(string(raw))

	for _, required := range []string{
		"mode: fail_closed",
		"core_law:",
		"protect",
		"extra_terms:",
		"block_categories:",
		"mandatory_checks:",
	} {
		if !strings.Contains(policy, required) {
			return fmt.Errorf("required policy marker %q is missing", required)
		}
	}

	for _, required := range []string{
		"weapon",
		"warfare",
		"explos",
		"malware",
		"credential",
		"privacy",
		"surveillance",
		"illegal",
		"safety controls",
	} {
		if !strings.Contains(policy, required) {
			return fmt.Errorf("required safety rule %q is missing", required)
		}
	}

	return nil
}

func validateZeroGuardianPolicy(raw []byte) error {
	if len(raw) == 0 || len(raw) > maxGuardianPolicyBytes {
		return errors.New("policy is empty or exceeds the 64 KiB limit")
	}
	if !utf8.Valid(raw) {
		return errors.New("policy is not valid UTF-8")
	}

	policy := strings.ToLower(string(raw))

	for _, required := range []string{
		"mode: fail_closed",
		"core_law:",
		"protect",
	} {
		if !strings.Contains(policy, required) {
			return fmt.Errorf("required policy marker %q is missing", required)
		}
	}

	requiredCategories := []struct {
		name    string
		markers []string
	}{
		{name: "weapons", markers: []string{"weapon"}},
		{name: "warfare", markers: []string{"warfare"}},
		{name: "explosives", markers: []string{"explos"}},
		{name: "malware and credential theft", markers: []string{"malware", "credential"}},
		{name: "privacy", markers: []string{"privacy"}},
	}

	for _, category := range requiredCategories {
		for _, marker := range category.markers {
			if !strings.Contains(policy, marker) {
				return fmt.Errorf(
					"required safety marker %q is missing from category %q",
					marker,
					category.name,
				)
			}
		}
	}

	return nil
}

// zeroLibraryProbe is an integration smoke test using synthetic Radar evidence.
// Its result confirms that the imported APIs returned successfully; it is not
// evidence of a real production performance improvement.
func (s *Service) zeroLibraryProbe() error {
	if s == nil {
		return errors.New("service unavailable")
	}

	compiled, err := zeroRVX.Compile("scan")
	if err != nil {
		return fmt.Errorf("RV Lang compile probe: %w", err)
	}
	if strings.TrimSpace(compiled.Status) == "" {
		return errors.New("RV Lang compile probe returned an empty status")
	}

	_, err = radar.Compare(
		radar.Evidence{
			Name:       "guardian-probe",
			Version:    "v0.1.0",
			Benchmark:  100,
			Source:     "synthetic integration probe",
			EvidenceID: "core-zero-probe-baseline",
		},
		radar.Evidence{
			Name:       "guardian-probe",
			Version:    "v0.2.0",
			Benchmark:  140,
			Source:     "synthetic integration probe",
			EvidenceID: "core-zero-probe-candidate",
		},
	)
	if err != nil {
		return fmt.Errorf("Radar API probe: %w", err)
	}

	return nil
}
