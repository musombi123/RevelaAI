package mind

import (
	"context"
	"errors"
	"math"
	"os"
	"strings"
	"time"
)

const (
	defaultMindDaemonInterval = 24 * time.Hour
	minMindDaemonInterval     = time.Second
	maxMindDaemonInterval     = 30 * 24 * time.Hour
)

// selectCandidate maps the objective to a known static candidate.
//
// It deliberately does not compare percentages across unrelated categories:
// graph speed, cost, checklist coverage, and security-control checks are not
// directly comparable metrics.
func selectCandidate(
	objective string,
	evaluations []CandidateEvaluation,
) (CandidateEvaluation, bool) {
	target := candidateForObjective(objective)

	for _, evaluation := range evaluations {
		if evaluation.ID != target {
			continue
		}

		if !evaluation.Passed || !validSelectionEvaluation(evaluation) {
			return CandidateEvaluation{}, false
		}

		spec, exists := sourceFor(evaluation.ID)
		if !exists || !isExactAllowlistedCandidate(spec) {
			return CandidateEvaluation{}, false
		}

		return evaluation, true
	}

	return CandidateEvaluation{}, false
}

// candidateForObjective applies a deterministic keyword-to-candidate policy.
// More specific categories take precedence when an objective mentions several
// topics. An unclassified objective defaults to graph-indexed.
func candidateForObjective(objective string) string {
	lower := strings.ToLower(strings.TrimSpace(objective))

	rules := []struct {
		candidate string
		keywords  []string
	}{
		{
			candidate: "bom-cost-ranked",
			keywords:  []string{"bom", "cost", "quote", "supplier", "bill of materials"},
		},
		{
			candidate: "hardware-guide-structured",
			keywords:  []string{"hardware", "fundi", "guide", "installation instructions"},
		},
		{
			candidate: "rvx-aead-envelope",
			keywords:  []string{"rvx", "encrypt", "encryption", "artifact protection", "cryptographic"},
		},
		{
			candidate: "cross-industry-pollination",
			keywords:  []string{"pollination", "cross-industry", "cross industry", "industry reuse"},
		},
		{
			candidate: "tamper-evident-audit-chain",
			keywords:  []string{"audit", "tamper-evident", "tamper evident", "audit integrity"},
		},
		{
			candidate: "bounded-input-guard",
			keywords:  []string{"bounded input", "input validation", "input safety", "path traversal"},
		},
		{
			candidate: "evidence-hash-dedup",
			keywords:  []string{"dedup", "deduplicate", "duplicate evidence", "evidence hashing"},
		},
		{
			candidate: "repository-path-index",
			keywords:  []string{"repository path", "path index", "path lookup", "file lookup"},
		},
		{
			candidate: "canonical-spec-cache",
			keywords:  []string{"cache", "canonical spec", "specification fingerprint", "spec fingerprint"},
		},
		{
			candidate: "graph-indexed",
			keywords:  []string{"graph", "traversal", "offline_vault", "dependency graph"},
		},
	}

	for _, rule := range rules {
		for _, keyword := range rule.keywords {
			if strings.Contains(lower, keyword) {
				return rule.candidate
			}
		}
	}

	return "graph-indexed"
}

func validSelectionEvaluation(evaluation CandidateEvaluation) bool {
	values := []float64{
		evaluation.BaselineValue,
		evaluation.CandidateValue,
		evaluation.ImprovementPct,
	}

	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return false
		}
	}

	if strings.TrimSpace(evaluation.ID) == "" ||
		strings.TrimSpace(evaluation.Category) == "" {
		return false
	}

	return true
}

// RunDaemon periodically records evidence and, when explicitly enabled,
// stages a proposal for human review.
//
// MIND_AUTO_EVOLVE is disabled by default. Setting it to "1", "true", "yes",
// or "enabled" enables proposal generation; it never enables automatic merge.
func (s *Service) RunDaemon(ctx context.Context, interval time.Duration) {
	if s == nil {
		return
	}

	if ctx == nil {
		ctx = context.Background()
	}

	if interval <= 0 {
		interval = defaultMindDaemonInterval
	}
	if interval < minMindDaemonInterval {
		interval = minMindDaemonInterval
	}
	if interval > maxMindDaemonInterval {
		interval = maxMindDaemonInterval
	}

	runCycle := func() {
		if ctx.Err() != nil {
			return
		}

		if daemonAutoEvolveEnabled() {
			// Evolve already performs its evidence scan; invoking Scan
			// separately here would duplicate the work.
			_, err := s.Evolve(ctx, EvolveRequest{
				ToolName:  "offline_vault_fixture",
				Objective: "improve offline_vault graph traversal efficiency",
			})

			if err == nil || ctx.Err() != nil {
				return
			}

			if errors.Is(err, ErrGuardianBlocked) {
				s.publish("daemon_evolution_blocked", map[string]any{
					"tool_name":       "offline_vault_fixture",
					"proposal_created": false,
					"automatic_merge":  false,
				})
				return
			}

			s.publish("evolution_cycle_error", map[string]any{
				"operation": "evolve",
				"error":     limitLabel(err.Error(), 300),
			})
			return
		}

		// The ordinary daemon mode is observation-only.
		if _, err := s.Scan(ctx); err != nil && ctx.Err() == nil {
			s.publish("mirror_error", map[string]any{
				"operation": "scan",
				"error":     limitLabel(err.Error(), 300),
			})
		}
	}

	runCycle()

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-ticker.C:
			runCycle()
		}
	}
}

func daemonAutoEvolveEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("MIND_AUTO_EVOLVE"))) {
	case "1", "true", "yes", "enabled":
		return true
	default:
		return false
	}
}
