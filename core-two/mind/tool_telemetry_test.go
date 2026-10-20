package mind

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func telemetryEvents(tool, hash string, count, failures int, includeReplay bool) []ToolTelemetryEvent {
	events := make([]ToolTelemetryEvent, 0, count)
	for i := 0; i < count; i++ {
		kind := "runtime"
		if includeReplay && i == count-1 {
			kind = "replay"
		}
		event := ToolTelemetryEvent{
			ToolName: tool,
			VersionHash: hash,
			Success: i >= failures,
			LatencyMS: int64(80 + (i % 5)),
			Timestamp: time.Now().UTC().Add(-time.Duration(count-i) * time.Second),
			SampleKind: kind,
		}
		if !event.Success {
			event.ErrorClass = "tool_error"
		}
		events = append(events, event)
	}
	return events
}

func TestTelemetryEndpointRejectsUnauthenticatedWrites(t *testing.T) {
	_, service := newTestRepository(t)
	t.Setenv("MIND_ADMIN_TOKEN", "test-only-token")
	payload := ToolTelemetryEvent{
		ToolName: "sample_tool",
		VersionHash: strings.Repeat("a", 64),
		Success: true,
		LatencyMS: 12,
		Timestamp: time.Now().UTC(),
		SampleKind: "runtime",
	}
	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "/v1/mind/telemetry/events", strings.NewReader(string(body)))
	response := httptest.NewRecorder()
	service.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("expected unauthenticated telemetry write to return 401, got %d: %s", response.Code, response.Body.String())
	}
	if _, err := os.Stat(filepath.Join(service.CoreRoot, "metrics", "tool-telemetry.jsonl")); !os.IsNotExist(err) {
		t.Fatalf("unauthenticated event should not reach telemetry storage, stat err=%v", err)
	}
}

func TestTelemetryEndpointAcceptsAuthenticatedMetadataOnly(t *testing.T) {
	_, service := newTestRepository(t)
	t.Setenv("MIND_ADMIN_TOKEN", "test-only-token")
	payload := ToolTelemetryEvent{
		ToolName: "sample_tool",
		VersionHash: strings.Repeat("a", 64),
		Success: false,
		LatencyMS: 42,
		ErrorClass: "timeout",
		Timestamp: time.Now().UTC(),
		SampleKind: "runtime",
	}
	body, err := json.Marshal(payload)
	if err != nil { t.Fatal(err) }
	request := httptest.NewRequest(http.MethodPost, "/v1/mind/telemetry/events", strings.NewReader(string(body)))
	request.Header.Set("X-Mind-Token", "test-only-token")
	response := httptest.NewRecorder()
	service.ServeHTTP(response, request)
	if response.Code != http.StatusCreated {
		t.Fatalf("expected authenticated telemetry write to return 201, got %d: %s", response.Code, response.Body.String())
	}
	raw, err := os.ReadFile(filepath.Join(service.CoreRoot, "metrics", "tool-telemetry.jsonl"))
	if err != nil { t.Fatal(err) }
	if strings.Contains(string(raw), "prompt") || strings.Contains(string(raw), "user_content") {
		t.Fatalf("telemetry must not store user content: %s", raw)
	}
}

func TestCanaryHoldsWhenSampleSizeIsTooSmall(t *testing.T) {
	baseline := telemetryEvents("sample_tool", strings.Repeat("a", 64), 5, 0, true)
	candidate := telemetryEvents("sample_tool", strings.Repeat("b", 64), 4, 0, true)
	decision := evaluateCanary(baseline, candidate, 30, 1)
	if decision.Decision != "hold" {
		t.Fatalf("expected hold for too-small sample, got %+v", decision)
	}
	if decision.Baseline.SampleCount != 5 || decision.Candidate.SampleCount != 4 || decision.MinimumSampleSize != 30 {
		t.Fatalf("decision must include actual sample numbers: %+v", decision)
	}
	if decision.AutoPromotionRecommended || decision.AutomaticMerge {
		t.Fatalf("small sample must never recommend auto-promotion: %+v", decision)
	}
}

func TestCanaryRecommendsRollbackWhenErrorRateRises(t *testing.T) {
	baseline := telemetryEvents("sample_tool", strings.Repeat("a", 64), 30, 0, true)
	candidate := telemetryEvents("sample_tool", strings.Repeat("b", 64), 30, 3, true)
	decision := evaluateCanary(baseline, candidate, 30, 1)
	if decision.Decision != "rollback" {
		t.Fatalf("expected rollback when error rate rises, got %+v", decision)
	}
	if decision.Baseline.ErrorRate != 0 || decision.Candidate.ErrorRate <= decision.Baseline.ErrorRate {
		t.Fatalf("rollback must include error-rate evidence: %+v", decision)
	}
	if decision.AutomaticMerge || decision.AutoPromotionRecommended {
		t.Fatalf("Mind must recommend only and not auto-promote a rollback: %+v", decision)
	}
}

func TestGuardianFailingCandidateIsNeverScored(t *testing.T) {
	root, service := newTestRepository(t)
	candidate := FoundryCandidate{
		CandidateID: "candidate_blocked_1",
		SourceCore: "core-one-foundry",
		ToolName: "sample_tool",
		Objective: "improve weapon search capability",
		BaselineVersionHash: strings.Repeat("a", 64),
		CandidateVersionHash: strings.Repeat("b", 64),
		SourceSHA256: strings.Repeat("c", 64),
		RiskTier: 1,
		SandboxTested: true,
		SandboxEvidenceRef: "sandbox/run-42",
	}
	result, err := service.ScoreFoundryCandidate(context.Background(), candidate, CoreOneFoundrySource{})
	if !errors.Is(err, ErrGuardianBlocked) {
		t.Fatalf("expected Guardian block before scoring, got result=%+v err=%v", result, err)
	}
	if result.Scored || result.GuardianPassed {
		t.Fatalf("blocked candidate must never be scored: %+v", result)
	}
	if _, statErr := os.Stat(filepath.Join(root, "core-two", "state", "candidates", candidate.CandidateID+".json")); !os.IsNotExist(statErr) {
		t.Fatalf("Guardian-blocked candidate must not create scoring evidence, stat err=%v", statErr)
	}
}

func TestTierTwoNeverRecommendedForAutomaticPromotion(t *testing.T) {
	baseline := telemetryEvents("sample_tool", strings.Repeat("a", 64), 30, 0, true)
	candidate := telemetryEvents("sample_tool", strings.Repeat("b", 64), 30, 0, true)
	decision := evaluateCanary(baseline, candidate, 30, 2)
	if decision.Decision != "hold" {
		t.Fatalf("Tier 2 must remain on hold even with clean measurements, got %+v", decision)
	}
	if decision.AutoPromotionRecommended || decision.AutomaticMerge {
		t.Fatalf("Tier 2 must never be automatically promoted or merged: %+v", decision)
	}
}

func TestCanaryAndHumanFeedbackUseIndependentRankingEntries(t *testing.T) {
	_, service := newTestRepository(t)
	candidate := FoundryCandidate{CandidateID:"candidate_rank_1", ToolName:"sample_tool"}
	decision := CanaryDecision{Decision:"promote", Reason:"Recorded sample and replay checks passed.", AutomaticMerge:false}
	if err := service.recordCanaryOutcome(candidate, decision); err != nil {
		t.Fatal(err)
	}
	summary, err := service.learningSummary()
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, entry := range summary.Mutations {
		if entry.Mutation == candidate.CandidateID {
			found = true
			if entry.CanaryPromote != 1 || entry.HumanDecisions != 0 {
				t.Fatalf("unexpected canary ranking entry: %+v", entry)
			}
		}
	}
	if !found {
		t.Fatal("expected canary outcome to influence ranking")
	}
}
