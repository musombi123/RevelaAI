package mind

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	toolTelemetryFileLimit int64 = 2 << 20
	toolTelemetryLineLimit       = 8 << 10
	toolTelemetryRotations       = 3
	minimumCanarySamples         = 30
)

var (
	toolTelemetryMu sync.Mutex
	toolNamePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,63}$`)
	versionHashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
	errorClassPattern = regexp.MustCompile(`^[a-z0-9_-]{1,48}$`)
)

// ToolTelemetryEvent contains operational metadata only: it intentionally has
// no request body, prompt, user ID, arguments, source, or arbitrary error text.
type ToolTelemetryEvent struct {
	ToolName    string    `json:"tool_name"`
	VersionHash string    `json:"version_hash"`
	Success     bool      `json:"success"`
	LatencyMS   int64     `json:"latency_ms"`
	ErrorClass  string    `json:"error_class,omitempty"`
	Timestamp   time.Time `json:"timestamp"`
	SampleKind     string    `json:"sample_kind,omitempty"`
	EvidenceOrigin string    `json:"evidence_origin"`
}

type ToolVersionMetrics struct {
	ToolName          string    `json:"tool_name"`
	VersionHash       string    `json:"version_hash"`
	SampleCount       int       `json:"sample_count"`
	RuntimeSamples    int       `json:"runtime_samples"`
	ReplaySamples     int       `json:"replay_samples"`
	SuccessCount      int       `json:"success_count"`
	FailureCount      int       `json:"failure_count"`
	ErrorRate         float64   `json:"error_rate"`
	P95LatencyMS      float64   `json:"p95_latency_ms"`
	LastEventAt       time.Time `json:"last_event_at"`
	Provenance         string    `json:"provenance"`
	SyntheticFixture   bool      `json:"synthetic_fixture"`
	ProductionVerified bool      `json:"production_verified"`
}

type CanaryStats struct {
	VersionHash    string    `json:"version_hash"`
	SampleCount    int       `json:"sample_count"`
	RuntimeSamples int       `json:"runtime_samples"`
	ReplaySamples  int       `json:"replay_samples"`
	SuccessCount   int       `json:"success_count"`
	FailureCount   int       `json:"failure_count"`
	ErrorRate      float64   `json:"error_rate"`
	P95LatencyMS   float64   `json:"p95_latency_ms"`
	LastEventAt    time.Time `json:"last_event_at"`
	SyntheticFixture bool    `json:"synthetic_fixture"`
	ProductionVerified bool `json:"production_verified"`
}

type CanaryDecision struct {
	Decision                 string      `json:"decision"`
	Reason                   string      `json:"reason"`
	MinimumSampleSize        int         `json:"minimum_sample_size"`
	Baseline                 CanaryStats `json:"baseline"`
	Candidate                CanaryStats `json:"candidate"`
	Score                    float64     `json:"score"`
	ScoreAvailable           bool        `json:"score_available"`
	RiskTier                 int         `json:"risk_tier"`
	AutomaticMerge           bool        `json:"automatic_merge"`
	AutoPromotionRecommended bool        `json:"auto_promotion_recommended"`
	ProductionVerified       bool        `json:"production_verified"`
	SyntheticFixture         bool        `json:"synthetic_fixture"`
}

type FoundryCandidate struct {
	CandidateID         string `json:"candidate_id"`
	SourceCore          string `json:"source_core"`
	ToolName            string `json:"tool_name"`
	Objective            string `json:"objective"`
	BaselineVersionHash  string `json:"baseline_version_hash"`
	CandidateVersionHash string `json:"candidate_version_hash"`
	SourceSHA256         string `json:"source_sha256"`
	RiskTier             int    `json:"risk_tier"`
	SandboxTested        bool   `json:"sandbox_tested"`
	SandboxEvidenceRef   string `json:"sandbox_evidence_ref"`
}

// CandidateSource is an extension point for candidates submitted by Core-One
// Foundry. Mind accepts hashes and sandbox evidence only; it neither writes nor
// executes candidate code.
type CandidateSource interface {
	ValidateCandidate(context.Context, FoundryCandidate) error
}

type CoreOneFoundrySource struct{}

func (CoreOneFoundrySource) ValidateCandidate(ctx context.Context, candidate FoundryCandidate) error {
	if err := ctx.Err(); err != nil { return err }
	if candidate.SourceCore != "core-one-foundry" { return errors.New("candidate source must be Core-One Foundry") }
	if !candidate.SandboxTested { return errors.New("candidate must already pass Core-One Foundry sandbox tests") }
	if !toolNamePattern.MatchString(candidate.CandidateID) || !toolNamePattern.MatchString(candidate.ToolName) || !safeMindToolName(candidate.ToolName) {
		return errors.New("candidate identifier or tool name is invalid")
	}
	if !versionHashPattern.MatchString(candidate.BaselineVersionHash) || !versionHashPattern.MatchString(candidate.CandidateVersionHash) || !versionHashPattern.MatchString(candidate.SourceSHA256) {
		return errors.New("candidate version and source hashes must be lowercase SHA-256 hex")
	}
	if candidate.BaselineVersionHash == candidate.CandidateVersionHash { return errors.New("candidate and baseline version hashes must differ") }
	if candidate.RiskTier != 1 && candidate.RiskTier != 2 { return errors.New("risk_tier must be 1 or 2") }
	if len(strings.TrimSpace(candidate.Objective)) < 3 || len(candidate.Objective) > 500 || strings.TrimSpace(candidate.Objective) != candidate.Objective {
		return errors.New("objective must contain 3–500 characters and have no surrounding whitespace")
	}
	if err := validateLearningEvidenceRef(candidate.SandboxEvidenceRef); err != nil { return fmt.Errorf("invalid sandbox_evidence_ref: %w", err) }
	return nil
}

type CandidateScoreResult struct {
	Status               string         `json:"status"`
	CandidateID          string         `json:"candidate_id"`
	ToolName             string         `json:"tool_name"`
	CandidateVersionHash string         `json:"candidate_version_hash"`
	SourceSHA256         string         `json:"source_sha256"`
	SandboxEvidenceRef   string         `json:"sandbox_evidence_ref"`
	GuardianPassed       bool           `json:"guardian_passed"`
	CoreOneGuardianPassed bool          `json:"core_one_guardian_passed"`
	Scored               bool           `json:"scored"`
	Score                float64        `json:"score"`
	RankingContextScore  float64        `json:"ranking_context_score"`
	Canary               CanaryDecision `json:"canary"`
	EvidenceRecordedAt   time.Time      `json:"evidence_recorded_at"`
	EvidencePath         string         `json:"evidence_path"`
	SyntheticFixture      bool           `json:"synthetic_fixture"`
	ProductionVerified   bool           `json:"production_verified"`
	AutomaticMerge       bool           `json:"automatic_merge"`
	PromotionExecuted    bool           `json:"promotion_executed"`
	RollbackExecuted     bool           `json:"rollback_executed"`
}

func validateToolTelemetryEvent(event ToolTelemetryEvent, rejectFuture bool) error {
	if !toolNamePattern.MatchString(event.ToolName) || !safeMindToolName(event.ToolName) { return errors.New("tool_name is invalid") }
	if !versionHashPattern.MatchString(event.VersionHash) { return errors.New("version_hash must be lowercase SHA-256 hex") }
	if event.LatencyMS < 0 || event.LatencyMS > 3_600_000 { return errors.New("latency_ms must be between 0 and 3600000") }
	kind := event.SampleKind
	if kind == "" { kind = "runtime" }
	if kind != "runtime" && kind != "replay" { return errors.New("sample_kind must be runtime or replay") }
	if event.EvidenceOrigin != "tool_runner" && event.EvidenceOrigin != "replay_harness" && event.EvidenceOrigin != "synthetic_fixture" {
		return errors.New("evidence_origin must be tool_runner, replay_harness, or synthetic_fixture")
	}
	if kind == "runtime" && event.EvidenceOrigin == "replay_harness" { return errors.New("runtime samples cannot claim replay_harness provenance") }
	if kind == "replay" && event.EvidenceOrigin == "tool_runner" { return errors.New("replay samples cannot claim tool_runner provenance") }
	if event.Success {
		if strings.TrimSpace(event.ErrorClass) != "" { return errors.New("successful events must not include an error_class") }
	} else if !errorClassPattern.MatchString(event.ErrorClass) {
		return errors.New("failed events require a short error_class, not an error message")
	}
	if event.Timestamp.IsZero() { return errors.New("timestamp is required") }
	if rejectFuture && event.Timestamp.After(time.Now().UTC().Add(5*time.Minute)) { return errors.New("timestamp is too far in the future") }
	return nil
}

// RecordToolTelemetry stores a validated tool-runner event in bounded, rotating
// Core-Two storage. Storage/validation errors are surfaced to the caller.
func (s *Service) RecordToolTelemetry(event ToolTelemetryEvent) error {
	if s == nil { return errors.New("Core-Two service is required") }
	if err := validateToolTelemetryEvent(event, true); err != nil { return err }
	if event.SampleKind == "" { event.SampleKind = "runtime" }
	event.Timestamp = event.Timestamp.UTC()
	raw, err := json.Marshal(event)
	if err != nil { return errors.New("could not encode tool telemetry") }
	line := append(raw, '\n')
	if int64(len(line)) > toolTelemetryLineLimit { return errors.New("tool telemetry event is oversized") }

	toolTelemetryMu.Lock()
	defer toolTelemetryMu.Unlock()
	dir := filepath.Join(s.CoreRoot, "metrics")
	if err := ensureMindDirectory(dir); err != nil { return fmt.Errorf("telemetry storage unavailable: %w", err) }
	path := filepath.Join(dir, "tool-telemetry.jsonl")
	info, err := os.Lstat(path)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { return errors.New("telemetry storage is not a regular file") }
		if info.Size()+int64(len(line)) > toolTelemetryFileLimit {
			if err := rotateToolTelemetry(path); err != nil { return fmt.Errorf("rotate telemetry storage: %w", err) }
		}
	} else if !os.IsNotExist(err) { return fmt.Errorf("inspect telemetry storage: %w", err) }

	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil { return fmt.Errorf("open telemetry storage: %w", err) }
	defer file.Close()
	opened, err := file.Stat()
	if err != nil { return err }
	info, err = os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || !os.SameFile(opened, info) { return errors.New("telemetry storage changed during open") }
	if err := file.Chmod(0o600); err != nil { return err }
	n, err := file.Write(line)
	if err != nil { return err }
	if n != len(line) { return io.ErrShortWrite }
	return nil
}

func rotateToolTelemetry(path string) error {
	oldest := fmt.Sprintf("%s.%d", path, toolTelemetryRotations)
	if info, err := os.Lstat(oldest); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { return errors.New("rotated telemetry file is unsafe") }
		if err := os.Remove(oldest); err != nil { return err }
	} else if !os.IsNotExist(err) { return err }
	for i := toolTelemetryRotations-1; i >= 1; i-- {
		from, to := fmt.Sprintf("%s.%d", path, i), fmt.Sprintf("%s.%d", path, i+1)
		if info, err := os.Lstat(from); err == nil {
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { return errors.New("rotated telemetry file is unsafe") }
			if err := os.Rename(from, to); err != nil { return err }
		} else if !os.IsNotExist(err) { return err }
	}
	return os.Rename(path, path+".1")
}

func (s *Service) readToolTelemetry() ([]ToolTelemetryEvent, error) {
	if s == nil { return nil, errors.New("Core-Two service is required") }
	toolTelemetryMu.Lock()
	defer toolTelemetryMu.Unlock()
	path := filepath.Join(s.CoreRoot, "metrics", "tool-telemetry.jsonl")
	events := make([]ToolTelemetryEvent, 0)
	for i := toolTelemetryRotations; i >= 0; i-- {
		current := path
		if i > 0 { current = fmt.Sprintf("%s.%d", path, i) }
		file, err := openMindRegularFile(current)
		if os.IsNotExist(err) { continue }
		if err != nil { return nil, fmt.Errorf("telemetry history is unavailable or unsafe: %w", err) }
		info, err := file.Stat()
		if err != nil { file.Close(); return nil, err }
		if info.Size() > toolTelemetryFileLimit { file.Close(); return nil, errors.New("telemetry history exceeds the file-size limit") }
		if info.Size() > 0 {
			var last [1]byte
			n, readErr := file.ReadAt(last[:], info.Size()-1)
			if (readErr != nil && !errors.Is(readErr, io.EOF)) || n != 1 || last[0] != '\n' {
				file.Close(); return nil, errors.New("telemetry history has an incomplete final record")
			}
		}
		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 4096), toolTelemetryLineLimit)
		lineNo := 0
		for scanner.Scan() {
			lineNo++
			line := strings.TrimSpace(scanner.Text())
			if line == "" { file.Close(); return nil, fmt.Errorf("empty telemetry line in %s", filepath.Base(current)) }
			var item ToolTelemetryEvent
			if err := json.Unmarshal([]byte(line), &item); err != nil { file.Close(); return nil, fmt.Errorf("invalid telemetry JSON in %s line %d", filepath.Base(current), lineNo) }
			if err := validateToolTelemetryEvent(item, false); err != nil { file.Close(); return nil, fmt.Errorf("invalid telemetry record in %s line %d: %w", filepath.Base(current), lineNo, err) }
			if item.SampleKind == "" { item.SampleKind = "runtime" }
			events = append(events, item)
			if len(events) > 100_000 { file.Close(); return nil, errors.New("telemetry history exceeds the event count limit") }
		}
		scanErr := scanner.Err()
		closeErr := file.Close()
		if scanErr != nil { return nil, fmt.Errorf("scan telemetry history: %w", scanErr) }
		if closeErr != nil { return nil, closeErr }
	}
	sort.SliceStable(events, func(i, j int) bool { return events[i].Timestamp.Before(events[j].Timestamp) })
	return events, nil
}

func aggregateToolTelemetry(events []ToolTelemetryEvent) []ToolVersionMetrics {
	groups := make(map[string][]ToolTelemetryEvent)
	for _, item := range events { groups[item.ToolName+"\x00"+item.VersionHash] = append(groups[item.ToolName+"\x00"+item.VersionHash], item) }
	result := make([]ToolVersionMetrics, 0, len(groups))
	for _, group := range groups {
		stats := summarizeTelemetry(group)
		result = append(result, ToolVersionMetrics{
			ToolName: group[0].ToolName, VersionHash: stats.VersionHash,
			SampleCount: stats.SampleCount, RuntimeSamples: stats.RuntimeSamples, ReplaySamples: stats.ReplaySamples,
			SuccessCount: stats.SuccessCount, FailureCount: stats.FailureCount,
			ErrorRate: stats.ErrorRate, P95LatencyMS: stats.P95LatencyMS, LastEventAt: stats.LastEventAt,
			Provenance: telemetryProvenance(group), SyntheticFixture: stats.SyntheticFixture, ProductionVerified: false,
		})
	}
	sort.Slice(result, func(i,j int) bool { if result[i].ToolName == result[j].ToolName { return result[i].VersionHash < result[j].VersionHash }; return result[i].ToolName < result[j].ToolName })
	return result
}

func telemetryProvenance(events []ToolTelemetryEvent) string {
	if len(events) == 0 {
		return "not_observed"
	}
	for _, event := range events {
		if event.EvidenceOrigin == "synthetic_fixture" { return "synthetic_fixture" }
	}
	return "declared_tool_runner_and_replay_harness"
}

func summarizeTelemetry(events []ToolTelemetryEvent) CanaryStats {
	stats := CanaryStats{}
	latencies := make([]int, 0, len(events))
	for _, event := range events {
		if stats.VersionHash == "" { stats.VersionHash = event.VersionHash }
		stats.SampleCount++
		if event.SampleKind == "replay" { stats.ReplaySamples++ } else { stats.RuntimeSamples++ }
		if event.Success { stats.SuccessCount++ } else { stats.FailureCount++ }
		if event.Timestamp.After(stats.LastEventAt) { stats.LastEventAt = event.Timestamp }
		if event.EvidenceOrigin == "synthetic_fixture" { stats.SyntheticFixture = true }
		latencies = append(latencies, int(event.LatencyMS))
	}
	if stats.SampleCount > 0 { stats.ErrorRate = float64(stats.FailureCount)/float64(stats.SampleCount) }
	sort.Ints(latencies)
	if len(latencies)>0 {
		idx := int(math.Ceil(0.95*float64(len(latencies))))-1
		if idx < 0 { idx=0 }
		if idx >= len(latencies) { idx=len(latencies)-1 }
		stats.P95LatencyMS = float64(latencies[idx])
	}
	return stats
}

// evaluateCanary makes recommendations from submitted runtime and replay
// telemetry; it does not promote, roll back, merge, or actuate anything.
func evaluateCanary(baselineEvents, candidateEvents []ToolTelemetryEvent, minSamples, riskTier int) CanaryDecision {
	if minSamples < 1 { minSamples = minimumCanarySamples }
	if minSamples > 10_000 { minSamples = 10_000 }
	base, candidate := summarizeTelemetry(baselineEvents), summarizeTelemetry(candidateEvents)
	out := CanaryDecision{
		Decision: "hold", Reason: "Insufficient evidence for a canary decision.",
		MinimumSampleSize: minSamples, Baseline: base, Candidate: candidate, RiskTier: riskTier,
		AutomaticMerge: false, AutoPromotionRecommended: false, ProductionVerified: false, SyntheticFixture: base.SyntheticFixture || candidate.SyntheticFixture,
	}
	out.ScoreAvailable = base.SampleCount >= minSamples && candidate.SampleCount >= minSamples
	if out.ScoreAvailable {
		relativeLatencyRegression := math.Max(0, (candidate.P95LatencyMS-base.P95LatencyMS)/math.Max(1,base.P95LatencyMS))
		score := 100 - candidate.ErrorRate*100 - relativeLatencyRegression*20
		if score < 0 { score=0 }; if score > 100 { score=100 }
		out.Score = math.Round(score*100)/100
	}
	switch {
	case base.SampleCount < minSamples || candidate.SampleCount < minSamples:
		out.Reason = fmt.Sprintf("Sample size below minimum: baseline %d/%d, candidate %d/%d.", base.SampleCount,minSamples,candidate.SampleCount,minSamples)
	case candidate.ErrorRate > base.ErrorRate+1e-9:
		out.Decision = "rollback"
		out.Reason = fmt.Sprintf("Candidate error rate rose from %.4f to %.4f.",base.ErrorRate,candidate.ErrorRate)
	case candidate.P95LatencyMS > math.Max(1,base.P95LatencyMS)*1.10:
		out.Decision = "rollback"
		out.Reason = fmt.Sprintf("Candidate p95 latency regressed from %.2f ms to %.2f ms (>10%%).",base.P95LatencyMS,candidate.P95LatencyMS)
	case base.ReplaySamples == 0 || candidate.ReplaySamples == 0:
		out.Reason = "Promotion is held until recorded replay telemetry exists for both baseline and candidate."
	case riskTier >= 2:
		out.Reason = "Tier 2 changes are never recommended for automatic promotion and require explicit human review."
	case out.SyntheticFixture:
		out.Reason = "Canary decision is held because one or more samples are explicitly synthetic fixtures, not deployment evidence."
	default:
		out.Decision = "promote"
		out.Reason = "Sample size is sufficient; error rate and p95 latency did not regress; runtime and replay telemetry are present."
		out.AutoPromotionRecommended = true
	}
	return out
}

func (s *Service) ToolTelemetrySnapshot() map[string]any {
	events, err := s.readToolTelemetry()
	if err != nil { return map[string]any{"status":"unavailable","reason":"telemetry_history_invalid","provenance":"unavailable","synthetic_fixture":false,"production_verified":false} }
	tools := make(map[string][]ToolVersionMetrics)
	for _, metric := range aggregateToolTelemetry(events) { tools[metric.ToolName] = append(tools[metric.ToolName], metric) }
	status := "observed"
	if len(events)==0 { status="not_observed" }
	synthetic := false
	for _, event := range events { if event.EvidenceOrigin == "synthetic_fixture" { synthetic = true; break } }
	return map[string]any{"status":status,"tools":tools,"event_count":len(events),"provenance":telemetryProvenance(events),"synthetic_fixture":synthetic,"production_verified":false}
}

func (s *Service) ScoreFoundryCandidate(ctx context.Context, candidate FoundryCandidate, source CandidateSource) (CandidateScoreResult, error) {
	result := CandidateScoreResult{
		Status:"blocked", CandidateID:candidate.CandidateID, ToolName:candidate.ToolName,
		CandidateVersionHash:candidate.CandidateVersionHash, SourceSHA256:candidate.SourceSHA256,
		SandboxEvidenceRef:candidate.SandboxEvidenceRef, SyntheticFixture:false, ProductionVerified:false,
		AutomaticMerge:false, PromotionExecuted:false, RollbackExecuted:false,
	}
	if s==nil { return result, errors.New("Core-Two service is required") }
	if ctx==nil { ctx=context.Background() }
	if source==nil { return result, errors.New("candidate source is required; fail-closed") }
	if err:=source.ValidateCandidate(ctx,candidate); err!=nil { return result,err }
	screeningText:=candidate.CandidateID+"\n"+candidate.ToolName+"\n"+candidate.Objective+"\n"+candidate.SourceSHA256
	allowed,reason:=s.guardianDecision(screeningText)
	if !allowed {
		if err:=s.logBlocked("foundry_candidate",screeningText,reason); err!=nil { return result,fmt.Errorf("%w: candidate block audit failed: %v",ErrGuardianBlocked,err) }
		s.publish("candidate_blocked",map[string]any{"candidate_id":candidate.CandidateID,"tool_name":candidate.ToolName,"scored":false})
		return result,ErrGuardianBlocked
	}
	if err:=ctx.Err(); err!=nil { return result,err }
	events,err:=s.readToolTelemetry()
	if err!=nil { return result,fmt.Errorf("candidate scoring telemetry unavailable; fail-closed: %w",err) }
	filter:=func(version string) []ToolTelemetryEvent {
		out:=make([]ToolTelemetryEvent,0)
		for _,event:=range events { if event.ToolName==candidate.ToolName && event.VersionHash==version { out=append(out,event) } }
		return out
	}
	decision:=evaluateCanary(filter(candidate.BaselineVersionHash),filter(candidate.CandidateVersionHash),minimumCanarySamples,candidate.RiskTier)
	result.Status=decision.Decision
	result.GuardianPassed=true
	result.CoreOneGuardianPassed=true
	result.Scored=decision.ScoreAvailable
	result.Score=decision.Score
	result.SyntheticFixture=decision.SyntheticFixture
	result.ProductionVerified=decision.ProductionVerified
	result.Canary=decision
	result.EvidenceRecordedAt=time.Now().UTC()
	result.EvidencePath=filepath.ToSlash(filepath.Join("core-two","state","candidates",candidate.CandidateID+".json"))
	if scores:=s.learningScores(); scores!=nil { result.RankingContextScore=scores[candidate.CandidateID] }
	if err:=s.storeCandidateEvidence(candidate,result); err!=nil { return CandidateScoreResult{},fmt.Errorf("store candidate decision evidence: %w",err) }
	if err:=s.recordCanaryOutcome(candidate,decision); err!=nil { return CandidateScoreResult{},fmt.Errorf("record canary ranking outcome: %w",err) }
	s.publish("candidate_scored",map[string]any{"candidate_id":candidate.CandidateID,"tool_name":candidate.ToolName,"decision":decision.Decision,"score_available":decision.ScoreAvailable,"automatic_merge":false})
	return result,nil
}

func (s *Service) storeCandidateEvidence(candidate FoundryCandidate, result CandidateScoreResult) error {
	dir:=filepath.Join(s.CoreRoot,"state","candidates")
	if err:=ensureMindDirectory(dir); err!=nil { return err }
	raw,err:=json.MarshalIndent(map[string]any{"candidate":candidate,"result":result},"","  ")
	if err!=nil { return err }
	path:=filepath.Join(dir,candidate.CandidateID+".json")
	file,err:=os.OpenFile(path,os.O_WRONLY|os.O_CREATE|os.O_EXCL,0o600)
	if err!=nil { if os.IsExist(err) { return errors.New("candidate_id already exists; use a new immutable candidate id") }; return err }
	if _,err:=file.Write(append(raw,'\n')); err!=nil { file.Close(); return err }
	if err:=file.Sync(); err!=nil { file.Close(); return err }
	return file.Close()
}
