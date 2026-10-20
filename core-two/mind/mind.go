// Package mind is a model-free, proposal-only improvement engine for Core-One.
package mind

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	genesis "revela-genesis.local/core-one/genesis"
	zeroRVX "usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

const (
	Version = "0.1.0-alpha"

	maxPolicyBytes  int64 = 256 * 1024
	maxEvidenceBytes int64 = 1024 * 1024
)

var (
	ErrGuardianBlocked = errors.New(
		"Core-Two Guardian blocked this evolution",
	)
	ErrNoQualifiedMutation = errors.New(
		"no mutation passed the evidence and improvement gates",
	)
)

type Service struct {
	RepoRoot string
	CoreRoot string
	OneRoot  string
	ZeroRoot string

	One *genesis.Engine

	mu         sync.RWMutex
	scanMu     sync.Mutex
	evolveMu   sync.Mutex
	mirrorMu   sync.Mutex
	learningMu sync.Mutex

	events []map[string]any
}

type EvolveRequest struct {
	ToolName  string `json:"tool_name"`
	Objective string `json:"objective"`
	Reason    string `json:"reason,omitempty"`
}

type EvolveResult struct {
	Status             string                `json:"status"`
	Version            string                `json:"version"`
	ToolName           string                `json:"tool_name"`
	SelectedMutation   string                `json:"selected_mutation"`
	SelectionReason    string                `json:"selection_reason"`
	LearningScores     map[string]float64    `json:"learning_scores"`
	MutationBatch      string                `json:"mutation_batch"`
	MutationCount      int                   `json:"mutation_count"`
	CandidateResults   []CandidateEvaluation `json:"candidate_results"`
	Benchmark          graphBenchmark        `json:"benchmark"`
	RVXProtection      map[string]any        `json:"rvx_protection"`
	ProductionEvidence map[string]any        `json:"production_evidence"`
	AwaitMergePath     string                `json:"await_merge_path"`
	ProviderNotified   bool                  `json:"provider_notified"`
	CreatedAt          time.Time             `json:"created_at"`
}

type ToolMetrics struct {
	ToolName                    string    `json:"tool_name"`
	ObservedAt                  time.Time `json:"observed_at"`
	EvidenceStatus              string    `json:"evidence_status"`
	TimeToInventMS              *float64  `json:"time_to_invent_ms"`
	BOMCostKES                  *float64  `json:"bom_cost_kes"`
	SafetyScore                 *float64  `json:"safety_score"`
	HumanMergeTimeMS            *float64  `json:"human_merge_time_ms"`
	MergeScore                  *float64  `json:"merge_score"`
	EndpointUsageCount          int       `json:"endpoint_usage_count"`
	EndpointUsageObserved       bool      `json:"endpoint_usage_observed"`
	LibraryFiles                int       `json:"library_files"`
	GuardianBlockCount          int       `json:"guardian_block_count"`
	GuardianLogObserved         bool      `json:"guardian_log_observed"`
	ZeroHealingEvents           int       `json:"zero_healing_events"`
	ZeroHealingEvidenceObserved bool      `json:"zero_healing_evidence_observed"`
	MeasurementNotes            []string  `json:"measurement_notes"`

	// These fields distinguish finding an evidence file from verifying
	// that its measurements genuinely represent production activity.
	EvidenceRecordObserved     bool   `json:"evidence_record_observed"`
	EvidenceProvenance         string `json:"evidence_provenance"`
	ProductionEvidenceVerified bool   `json:"production_evidence_verified"`
}

// NewService initializes Core-Two without altering Core-One or Core-Zero.
//
// Existing required files are inspected before Core-Two's output directories
// are created. The Core-Zero Guardian policy may be absent, but any existing
// invalid or unsafe policy is reported by IntegrationStatus.
func NewService(repositoryRoot string) (*Service, error) {
	if strings.TrimSpace(repositoryRoot) == "" {
		return nil, errors.New("repository root is required")
	}

	abs, err := filepath.Abs(repositoryRoot)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root: %w", err)
	}

	rootInfo, err := os.Lstat(abs)
	if err != nil {
		return nil, fmt.Errorf("inspect repository root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return nil, errors.New(
			"repository root must be an existing non-symlink directory",
		)
	}

	// Canonicalize the location to avoid accidentally deriving different
	// repository paths from relative paths or symbolic ancestors.
	abs, err = filepath.EvalSymlinks(abs)
	if err != nil {
		return nil, fmt.Errorf("canonicalize repository root: %w", err)
	}

	oneRoot := filepath.Join(abs, "core-one")
	zeroRoot := filepath.Join(abs, "core-zero")

	if err := requireMindDirectory(oneRoot); err != nil {
		return nil, fmt.Errorf("Core-One directory: %w", err)
	}
	if err := requireMindDirectory(zeroRoot); err != nil {
		return nil, fmt.Errorf("Core-Zero directory: %w", err)
	}

	// Only Core-One's Guardian policy is a mandatory construction dependency.
	// Core-Zero's policy gap is reported separately and must not be concealed.
	for _, required := range []struct {
		root     string
		relative string
	}{
		{oneRoot, "go.mod"},
		{zeroRoot, "go.mod"},
		{oneRoot, filepath.Join("guardian", "rules.yaml")},
	} {
		if _, err := readMindFileWithinRoot(
			required.root,
			required.relative,
			maxPolicyBytes,
		); err != nil {
			return nil, fmt.Errorf(
				"required Core-One/Core-Zero file unavailable or unsafe: %s: %w",
				filepath.Join(required.root, required.relative),
				err,
			)
		}
	}

	one := &genesis.Engine{
		RepoRoot: abs,
		CoreRoot: oneRoot,
		Guardian: genesis.Guardian{
			CoreRoot: oneRoot,
		},
	}

	if _, err := one.ListInventions(); err != nil {
		return nil, fmt.Errorf(
			"Core-One invention observer failed: %w",
			err,
		)
	}

	coreRoot := filepath.Join(abs, "core-two")
	if err := ensureMindDirectory(coreRoot); err != nil {
		return nil, fmt.Errorf("initialize Core-Two directory: %w", err)
	}

	for _, dir := range []string{
		"metrics",
		"mutations",
		"evolutions",
		"guardian",
		"rvx",
		"state",
		"testdata",
	} {
		if err := ensureMindDirectory(filepath.Join(coreRoot, dir)); err != nil {
			return nil, fmt.Errorf(
				"initialize Core-Two directory %q: %w",
				dir,
				err,
			)
		}
	}

	return &Service{
		RepoRoot: abs,
		CoreRoot: coreRoot,
		OneRoot:  oneRoot,
		ZeroRoot: zeroRoot,
		One:      one,
	}, nil
}

// IntegrationStatus describes the observed integration state of Core-One,
// Core-Zero, and Core-Two.
//
// Probe results indicate whether the called APIs returned successfully;
// they do not certify production readiness, safety, or legal compliance.
func (s *Service) IntegrationStatus() map[string]any {
	if s == nil {
		return map[string]any{
			"status": "degraded",
			"error":  "service is nil",
		}
	}

	zeroCompile, zeroCompileErr := zeroRVX.Compile("scan")

	_, radarErr := radar.Compare(
		radar.Evidence{
			Name:       "integration_probe",
			Version:    "v0.1.0",
			Benchmark:  100,
			Source:     "synthetic local library probe",
			EvidenceID: "zero-integration-baseline",
		},
		radar.Evidence{
			Name:       "integration_probe",
			Version:    "v0.2.0",
			Benchmark:  140,
			Source:     "synthetic local library probe",
			EvidenceID: "zero-integration-candidate",
		},
	)

	var inventions []map[string]any
	var oneErr error

	if s.One == nil {
		oneErr = errors.New("Core-One engine is unavailable")
	} else {
		inventions, oneErr = s.One.ListInventions()
	}

	zeroPolicyRaw, zeroGuardianErr := readMindFileWithinRoot(
		s.ZeroRoot,
		filepath.Join("guardian", "rules.yaml"),
		maxPolicyBytes,
	)

	zeroGuardianStatus := "present"
	zeroGuardianMissing := false
	zeroGuardianInvalid := false

	switch {
	case os.IsNotExist(zeroGuardianErr):
		zeroGuardianMissing = true
		zeroGuardianStatus =
			"missing_in_current_repository_snapshot; " +
				"restrictive_Core_Two_controls_and_Core_One_Guardian_required"

	case zeroGuardianErr != nil:
		zeroGuardianInvalid = true
		zeroGuardianStatus =
			"unreadable_or_unsafe_existing_policy; mutation_policy_must_fail_closed"

	case validateZeroGuardianPolicy(zeroPolicyRaw) != nil:
		zeroGuardianInvalid = true
		zeroGuardianStatus =
			"invalid_existing_policy; mutation_policy_must_fail_closed"
	}

	status := "integrated"

	switch {
	case zeroCompileErr != nil,
		radarErr != nil,
		oneErr != nil,
		zeroGuardianInvalid:
		status = "degraded"

	case zeroGuardianMissing:
		status = "integrated_with_reported_policy_gap"
	}

	rvLangStatus := ""
	if zeroCompileErr == nil {
		rvLangStatus = zeroCompile.Status
	}

	return map[string]any{
		"status": status,
		"core_zero": map[string]any{
			"exists":             directoryExists(s.ZeroRoot),
			"module":             "usect-zero.local/core-zero",
			"imported_libraries": []string{
				"usect-zero.local/core-zero/mind",
				"usect-zero.local/core-zero/radar",
			},
			"rv_lang_probe":        zeroCompileErr == nil,
			"rv_lang_status":       rvLangStatus,
			"radar_probe":          radarErr == nil,
			"guardian_policy_file": zeroGuardianStatus,
			"guardian_policy_missing": zeroGuardianMissing,
			"guardian_policy_invalid": zeroGuardianInvalid,
			"health_log_path": filepath.Join(
				"core-zero",
				"audit_log",
				"events.jsonl",
			),
		},
		"core_one": map[string]any{
			"exists":             directoryExists(s.OneRoot),
			"module":             "revela-genesis.local/core-one",
			"imported_libraries": []string{
				"revela-genesis.local/core-one/genesis",
			},
			"guardian_policy_present": mindRegularFileWithinRoot(
				s.OneRoot,
				filepath.Join("guardian", "rules.yaml"),
			),
			"observed_invention_count": len(inventions),
			"invention_log_path": filepath.Join(
				"core-one",
				"state",
				"events",
			),
		},
		"core_two": map[string]any{
			"version":            Version,
			"model_free":         true,
			"source_execution":   false,
			"automatic_merge":    false,
			"automatic_installation": false,
			"mutation_outputs":   "core-two/mutations/",
			"evolution_outputs":  "core-two/evolutions/",
		},
		"provider": map[string]any{
			"provider_url_env":             "REVELACODE_PROVIDER_URL",
			"provider_key_env":             "REVELACODE_PROVIDER_KEY",
			"same_credential_names_as_core_one": true,
			"secret_disclosed":             false,
		},
	}
}

// Scan records an inventory and operational evidence snapshot.
//
// Raw measurements found in evidence files are not automatically classified
// as verified production evidence. Production averages remain null unless a
// separate trusted verification process establishes their provenance.
func (s *Service) Scan(ctx context.Context) (map[string]any, error) {
	if s == nil {
		return nil, errors.New("service is nil")
	}

	if ctx == nil {
		ctx = context.Background()
	}

	s.scanMu.Lock()
	defer s.scanMu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	inventory, err := s.scanRepositoryInventory()
	if err != nil {
		return nil, fmt.Errorf("scan repository evidence tree: %w", err)
	}

	mirror, err := s.observeMirror(ctx)
	if err != nil {
		return nil, fmt.Errorf(
			"mirror Core-Zero/Core-One operational evidence: %w",
			err,
		)
	}

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	if s.One == nil {
		return nil, errors.New("Core-One engine is unavailable")
	}

	items, err := s.One.ListInventions()
	if err != nil {
		return nil, fmt.Errorf("list Core-One inventions: %w", err)
	}

	metrics := make([]ToolMetrics, 0, len(items))

	for _, item := range items {
		if err := ctx.Err(); err != nil {
			return nil, err
		}

		name, _ := item["name"].(string)
		if !safeMindToolName(name) {
			continue
		}

		metric := s.metricForTool(name)
		metrics = append(metrics, metric)
	}

	// Recorded measurements are summarized separately from production metrics.
	recordedTimes := make([]float64, 0, len(metrics))
	recordedBOMs := make([]float64, 0, len(metrics))
	recordedSafety := make([]float64, 0, len(metrics))
	recordedMerges := make([]float64, 0, len(metrics))

	verifiedTimes := make([]float64, 0, len(metrics))
	verifiedBOMs := make([]float64, 0, len(metrics))
	verifiedSafety := make([]float64, 0, len(metrics))
	verifiedMerges := make([]float64, 0, len(metrics))

	verifiedProductionRecordCount := 0

	for _, metric := range metrics {
		if metric.TimeToInventMS != nil {
			recordedTimes = append(recordedTimes, *metric.TimeToInventMS)
		}
		if metric.BOMCostKES != nil {
			recordedBOMs = append(recordedBOMs, *metric.BOMCostKES)
		}
		if metric.SafetyScore != nil {
			recordedSafety = append(recordedSafety, *metric.SafetyScore)
		}
		if metric.HumanMergeTimeMS != nil {
			recordedMerges = append(recordedMerges, *metric.HumanMergeTimeMS)
		}

		if !metric.ProductionEvidenceVerified {
			continue
		}

		verifiedProductionRecordCount++

		if metric.TimeToInventMS != nil {
			verifiedTimes = append(verifiedTimes, *metric.TimeToInventMS)
		}
		if metric.BOMCostKES != nil {
			verifiedBOMs = append(verifiedBOMs, *metric.BOMCostKES)
		}
		if metric.SafetyScore != nil {
			verifiedSafety = append(verifiedSafety, *metric.SafetyScore)
		}
		if metric.HumanMergeTimeMS != nil {
			verifiedMerges = append(verifiedMerges, *metric.HumanMergeTimeMS)
		}
	}

	recordedAverages := map[string]any{
		"time_to_invent_ms":   optionalAverage(recordedTimes),
		"bom_cost_kes":        optionalAverage(recordedBOMs),
		"safety_score":        optionalAverage(recordedSafety),
		"human_merge_time_ms": optionalAverage(recordedMerges),
		"provenance_verified": false,
	}

	productionAverages := map[string]any{
		"time_to_invent_ms":   optionalAverage(verifiedTimes),
		"bom_cost_kes":        optionalAverage(verifiedBOMs),
		"safety_score":        optionalAverage(verifiedSafety),
		"human_merge_time_ms": optionalAverage(verifiedMerges),
		"verified_record_count": verifiedProductionRecordCount,
	}

	integration := s.IntegrationStatus()

	research := map[string]any{
		"schema_version": "usect-two.research-evidence.v1",
		"observed_at":    time.Now().UTC(),

		"repository_snapshot": map[string]any{
			"baseline_commit": "40dc1caf07419ad14f771be88fc238baa51d4480",
			"source": "GitHub repository scan before Core-Two branch changes",
			"baseline_commit_independently_verified": false,
		},

		"integration":          integration,
		"repository_inventory": inventory,
		"mirror":               mirror,

		// This is the observed count returned by Core-One's invention
		// observer. It is not automatically treated as a verified count
		// of historical production inventions.
		"observed_core_one_invention_count": len(items),
		"production_invention_count":        nil,

		"recorded_measurement_averages": recordedAverages,
		"production_averages":           productionAverages,

		// Retain the legacy output keys for compatibility, but do not
		// populate them from evidence whose production provenance has
		// not been independently verified.
		"average_time_to_invent_ms":   nil,
		"average_bom_cost_kes":        nil,
		"average_safety_score":        nil,
		"average_human_merge_time_ms": nil,

		"observed_inventions": items,

		"data_quality": map[string]any{
			"historical_time_measurements_available": len(recordedTimes) > 0,
			"verified_production_time_measurements_available": len(verifiedTimes) > 0,
			"recorded_bom_costs_available": len(recordedBOMs) > 0,
			"verified_production_bom_costs_available": len(verifiedBOMs) > 0,
			"verified_production_evidence_records": verifiedProductionRecordCount,
			"zero_guardian_policy_file_present": mindRegularFileWithinRoot(
				s.ZeroRoot,
				filepath.Join("guardian", "rules.yaml"),
			),
			"synthetic_fixture_counted_as_production_tool": false,
			"production_provenance_verifier_implemented_here": false,
		},

		"note": "Core-One inventory observations and measurement fields found " +
			"in evidence files are recorded separately. An evidence file alone " +
			"does not establish production provenance. Production averages " +
			"remain null unless a separate trusted verification process " +
			"validates the provenance and scope of the measurements.",
	}

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	if err := writeJSONFile(
		filepath.Join(s.CoreRoot, "metrics", "mirror.json"),
		mirror,
		0o600,
	); err != nil {
		return nil, fmt.Errorf("write mirror evidence: %w", err)
	}

	for _, metric := range metrics {
		if err := ctx.Err(); err != nil {
			return nil, err
		}

		if !safeMindToolName(metric.ToolName) {
			continue
		}

		path := filepath.Join(
			s.CoreRoot,
			"metrics",
			metric.ToolName+".json",
		)

		if err := writeJSONFile(path, metric, 0o600); err != nil {
			return nil, fmt.Errorf(
				"write metrics for %q: %w",
				metric.ToolName,
				err,
			)
		}
	}

	if err := writeJSONFile(
		filepath.Join(s.CoreRoot, "research_evidence.json"),
		research,
		0o600,
	); err != nil {
		return nil, fmt.Errorf("write research evidence: %w", err)
	}

	return map[string]any{
		"status":             "ok",
		"observed_tool_count": len(items),
		"metrics":            metrics,
		"tool_telemetry":      s.ToolTelemetrySnapshot(),
		"research_evidence_path": filepath.Join(
			"core-two",
			"research_evidence.json",
		),
		"repository_inventory": inventory,
		"mirror":               mirror,
		"integration":          integration,
	}, nil
}

// metricForTool observes telemetry and existing evidence without treating
// missing measurements as zero or promoting unverified records to production.
func (s *Service) metricForTool(name string) ToolMetrics {
	now := time.Now().UTC()

	m := ToolMetrics{
		ToolName:                    name,
		ObservedAt:                  now,
		EvidenceStatus:              "no_measurement_record_found",
		EndpointUsageObserved:       false,
		GuardianLogObserved:         false,
		ZeroHealingEvidenceObserved: false,
		EvidenceRecordObserved:      false,
		EvidenceProvenance:          "unverified",
		ProductionEvidenceVerified:  false,
		MeasurementNotes:            make([]string, 0, 6),
	}

	if s == nil || !safeMindToolName(name) {
		m.EvidenceStatus = "invalid_tool_or_service"
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"Tool name or service was invalid; no tool-specific evidence was read.",
		)
		return m
	}

	evidencePath := filepath.Join("inventions", name, "evidence.json")

	raw, err := readMindFileWithinRoot(
		s.OneRoot,
		evidencePath,
		maxEvidenceBytes,
	)

	switch {
	case os.IsNotExist(err):
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"No Core-One evidence.json record was found for this tool.",
		)

	case err != nil:
		m.EvidenceStatus = "evidence_file_unreadable_or_unsafe"
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"The evidence file could not be safely read or exceeded the size limit.",
		)

	default:
		m.EvidenceRecordObserved = true

		var obj map[string]any
		if decodeErr := json.Unmarshal(raw, &obj); decodeErr != nil || obj == nil {
			m.EvidenceStatus = "evidence_file_invalid"
			m.MeasurementNotes = append(
				m.MeasurementNotes,
				"The evidence file was not a valid JSON object.",
			)
		} else {
			m.EvidenceProvenance = declaredEvidenceProvenance(obj)

			m.TimeToInventMS = readEvidenceMeasurement(
				obj,
				& m.MeasurementNotes,
				"time_to_invent_ms",
				"duration_ms",
				"elapsed_ms",
			)

			m.BOMCostKES = readEvidenceMeasurement(
				obj,
				& m.MeasurementNotes,
				"bom_cost_kes",
				"estimated_bom_cost_kes",
			)

			m.SafetyScore = readEvidenceMeasurement(
				obj,
				& m.MeasurementNotes,
				"safety_score",
			)

			m.HumanMergeTimeMS = readEvidenceMeasurement(
				obj,
				& m.MeasurementNotes,
				"human_merge_time_ms",
				"merge_time_ms",
			)

			m.MergeScore = readEvidenceMeasurement(
				obj,
				& m.MeasurementNotes,
				"merge_score",
				"human_merge_score",
			)

			if hasAnyMeasurement(m) {
				m.EvidenceStatus = "recorded_measurements_unverified_provenance"
			} else {
				m.EvidenceStatus = "evidence_record_observed_no_usable_measurements"
			}
		}
	}

	if m.TimeToInventMS == nil {
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"End-to-end invention time is unknown, not zero.",
		)
	}

	if m.BOMCostKES == nil {
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"No verified BOM cost in KES was established; the value remains unknown.",
		)
	}

	if m.SafetyScore == nil {
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"No usable recorded safety score was found.",
		)
	}

	if m.HumanMergeTimeMS == nil {
		m.MeasurementNotes = append(
			m.MeasurementNotes,
			"Human review and merge time is unknown, not zero.",
		)
	}

	// A provenance label inside a JSON file is metadata, not independent
	// verification. No code in this function marks the record as verified.
	m.ProductionEvidenceVerified = false

	m.LibraryFiles = countSourceFiles(
		filepath.Join(s.OneRoot, "libraries", "created", name),
	)

	if mindRegularFileWithinRoot(s.OneRoot, filepath.Join("guardian", "blocked.log")) {
		count, countErr := countLogLines(
			filepath.Join(s.OneRoot, "guardian", "blocked.log"),
			"",
		)
		if countErr == nil {
			m.GuardianBlockCount = count
			m.GuardianLogObserved = true
		}
	}

	if mindRegularFileWithinRoot(
		s.ZeroRoot,
		filepath.Join("audit_log", "events.jsonl"),
	) {
		count, countErr := countLogLines(
			filepath.Join(s.ZeroRoot, "audit_log", "events.jsonl"),
			"heal|recovery|restore",
		)
		if countErr == nil {
			m.ZeroHealingEvents = count
			m.ZeroHealingEvidenceObserved = true
		}
	}

	telemetryRelative := filepath.Join("state", "http_metrics.jsonl")

	if mindRegularFileWithinRoot(s.CoreRoot, telemetryRelative) {
		count, observed := countToolEndpointUsage(
			filepath.Join(s.CoreRoot, telemetryRelative),
			name,
		)
		m.EndpointUsageCount = count
		m.EndpointUsageObserved = observed
	}

	return m
}

func hasAnyMeasurement(m ToolMetrics) bool {
	return m.TimeToInventMS != nil ||
		m.BOMCostKES != nil ||
		m.SafetyScore != nil ||
		m.HumanMergeTimeMS != nil ||
		m.MergeScore != nil
}

// readEvidenceMeasurement reads an optional non-negative finite number.
// Invalid values are ignored and documented rather than silently accepted.
func readEvidenceMeasurement(
	obj map[string]any,
	notes *[]string,
	fields ...string,
) *float64 {
	value, ok := numberField(obj, fields...)
	if !ok {
		return nil
	}

	if math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
		*notes = append(
			*notes,
			fmt.Sprintf(
				"Measurement %q was invalid or negative and was ignored.",
				fields[0],
			),
		)
		return nil
	}

	return &value
}

func declaredEvidenceProvenance(obj map[string]any) string {
	if fixtureOnly, ok := obj["fixture_only"].(bool); ok && fixtureOnly {
		return "declared_synthetic_fixture"
	}

	if synthetic, ok := obj["synthetic"].(bool); ok && synthetic {
		return "declared_synthetic"
	}

	if status, ok := obj["evidence_status"].(string); ok {
		if strings.Contains(strings.ToLower(status), "synthetic") ||
			strings.Contains(strings.ToLower(status), "fixture") {
			return "declared_synthetic_fixture"
		}
	}

	return "unverified"
}

func optionalAverage(values []float64) any {
	if len(values) == 0 {
		return nil
	}

	return average(values)
}

func safeMindToolName(name string) bool {
	if name == "" || name == "." || name == ".." || len(name) > 80 {
		return false
	}

	if !validName(name) {
		return false
	}

	for _, r := range name {
		if !((r >= 'a' && r <= 'z') ||
			(r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') ||
			r == '_' || r == '-' || r == '.') {
			return false
		}
	}

	return true
}

func requireMindDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}

	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("path must be a non-symlink directory")
	}

	return nil
}

// ensureMindDirectory creates a single directory and refuses to follow a
// symbolic link at the target path. Parent directories must already exist.
func ensureMindDirectory(path string) error {
	info, err := os.Lstat(path)

	switch {
	case err == nil:
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return errors.New("existing path is not a safe directory")
		}
		return nil

	case !os.IsNotExist(err):
		return err
	}

	if err := os.Mkdir(path, 0o700); err != nil {
		// A concurrent creator may have won the race. Validate the final path.
		if !os.IsExist(err) {
			return err
		}
	}

	return requireMindDirectory(path)
}

// mindPathWithinRoot validates a relative path, rejects symbolic links at
// every component, and returns the final regular-file path and metadata.
func mindPathWithinRoot(
	root string,
	relative string,
) (string, os.FileInfo, error) {
	if strings.TrimSpace(root) == "" || strings.TrimSpace(relative) == "" {
		return "", nil, errors.New("root and relative path are required")
	}

	if filepath.IsAbs(relative) || filepath.VolumeName(relative) != "" {
		return "", nil, errors.New("absolute paths are not allowed")
	}

	clean := filepath.Clean(relative)
	if clean == "." ||
		clean == ".." ||
		strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
		return "", nil, errors.New("path traversal is not allowed")
	}

	rootInfo, err := os.Lstat(root)
	if err != nil {
		return "", nil, err
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return "", nil, errors.New("root must be a non-symlink directory")
	}

	parts := strings.Split(clean, string(os.PathSeparator))
	current := root

	for i, part := range parts {
		if part == "" || part == "." || part == ".." {
			return "", nil, errors.New("unsafe path component")
		}

		current = filepath.Join(current, part)

		info, err := os.Lstat(current)
		if err != nil {
			return "", nil, err
		}

		if info.Mode()&os.ModeSymlink != 0 {
			return "", nil, errors.New("symbolic-link path component rejected")
		}

		if i < len(parts)-1 {
			if !info.IsDir() {
				return "", nil, errors.New("intermediate path component is not a directory")
			}
			continue
		}

		if !info.Mode().IsRegular() {
			return "", nil, errors.New("target must be a regular file")
		}

		return current, info, nil
	}

	return "", nil, errors.New("invalid empty path")
}

func readMindFileWithinRoot(
	root string,
	relative string,
	maxBytes int64,
) ([]byte, error) {
	if maxBytes <= 0 {
		return nil, errors.New("maximum file size must be positive")
	}

	path, pathInfo, err := mindPathWithinRoot(root, relative)
	if err != nil {
		return nil, err
	}

	if pathInfo.Size() > maxBytes {
		return nil, fmt.Errorf(
			"file exceeds maximum permitted size of %d bytes",
			maxBytes,
		)
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	openedInfo, err := file.Stat()
	if err != nil {
		return nil, err
	}

	currentInfo, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}

	if currentInfo.Mode()&os.ModeSymlink != 0 ||
		!currentInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, currentInfo) {
		return nil, errors.New("file changed during safe-open validation")
	}

	raw, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
	if err != nil {
		return nil, err
	}

	if int64(len(raw)) > maxBytes {
		return nil, fmt.Errorf(
			"file exceeds maximum permitted size of %d bytes",
			maxBytes,
		)
	}

	return raw, nil
}

func mindRegularFileWithinRoot(root, relative string) bool {
	_, _, err := mindPathWithinRoot(root, relative)
	return err == nil
}
