// Package mind is a model-free, proposal-only improvement engine for Core-One.
package mind

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	genesis "revela-genesis.local/core-one/genesis"
	zeroRVX "usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

const Version = "0.1.0-alpha"

var ErrGuardianBlocked = errors.New("Core-Two Guardian blocked this evolution")
var ErrNoQualifiedMutation = errors.New("no mutation passed the evidence and improvement gates")

type Service struct {
	RepoRoot string
	CoreRoot string
	OneRoot  string
	ZeroRoot string
	One      *genesis.Engine
	mu       sync.RWMutex
	events   []map[string]any
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
}

func NewService(repositoryRoot string) (*Service, error) {
	if strings.TrimSpace(repositoryRoot) == "" { return nil, errors.New("repository root is required") }
	abs, err := filepath.Abs(repositoryRoot)
	if err != nil { return nil, err }
	oneRoot := filepath.Join(abs, "core-one")
	zeroRoot := filepath.Join(abs, "core-zero")
	for _, required := range []string{filepath.Join(oneRoot, "go.mod"), filepath.Join(zeroRoot, "go.mod"), filepath.Join(oneRoot, "guardian", "rules.yaml")} {
		if info, e := os.Stat(required); e != nil || info.IsDir() { return nil, fmt.Errorf("required existing core file missing: %s", required) }
	}
	coreRoot := filepath.Join(abs, "core-two")
	for _, dir := range []string{"metrics", "mutations", "evolutions", "guardian", "rvx", "state", "testdata"} {
		if err := os.MkdirAll(filepath.Join(coreRoot, dir), 0o700); err != nil { return nil, err }
	}
	one := &genesis.Engine{RepoRoot: abs, CoreRoot: oneRoot, Guardian: genesis.Guardian{CoreRoot: oneRoot}}
	if _, err := one.ListInventions(); err != nil { return nil, fmt.Errorf("Core-One invention observer failed: %w", err) }
	return &Service{RepoRoot: abs, CoreRoot: coreRoot, OneRoot: oneRoot, ZeroRoot: zeroRoot, One: one}, nil
}

func (s *Service) IntegrationStatus() map[string]any {
	zeroCompile, zeroCompileErr := zeroRVX.Compile("scan")
	_, radarErr := radar.Compare(
		radar.Evidence{Name: "integration_probe", Version: "v0.1.0", Benchmark: 100, Source: "local library probe", EvidenceID: "zero-integration-baseline"},
		radar.Evidence{Name: "integration_probe", Version: "v0.2.0", Benchmark: 140, Source: "local library probe", EvidenceID: "zero-integration-candidate"},
	)
	inventions, oneErr := s.One.ListInventions()
	zeroPolicyPath := filepath.Join(s.ZeroRoot, "guardian", "rules.yaml")
	zeroPolicyRaw, zeroGuardianErr := os.ReadFile(zeroPolicyPath)
	zeroGuardianStatus := "present"
	if os.IsNotExist(zeroGuardianErr) {
		zeroGuardianStatus = "missing_in_current_repository_snapshot; restrictive_core_two_policy_and_core_one_guardian_remain_active"
	} else if zeroGuardianErr != nil {
		zeroGuardianStatus = "unreadable; mutation policy must fail closed"
	} else if err := validateZeroGuardianPolicy(zeroPolicyRaw); err != nil {
		zeroGuardianStatus = "invalid_existing_policy; mutation policy fails closed: " + err.Error()
	}
	status := "integrated_with_reported_policy_gap"
	if zeroCompileErr != nil || radarErr != nil || oneErr != nil || (zeroGuardianErr != nil && !os.IsNotExist(zeroGuardianErr)) || strings.HasPrefix(zeroGuardianStatus, "invalid_existing_policy") { status = "degraded" } else if zeroGuardianStatus == "present" { status = "integrated" }
	return map[string]any{
		"status": status, "core_zero": map[string]any{"exists": directoryExists(s.ZeroRoot), "module": "usect-zero.local/core-zero", "imported_libraries": []string{"usect-zero.local/core-zero/mind", "usect-zero.local/core-zero/radar"}, "rv_lang_probe": zeroCompileErr == nil, "rv_lang_status": zeroCompile.Status, "radar_probe": radarErr == nil, "guardian_policy_file": zeroGuardianStatus, "health_log_path": filepath.Join("core-zero", "audit_log", "events.jsonl")},
		"core_one": map[string]any{"exists": directoryExists(s.OneRoot), "module": "revela-genesis.local/core-one", "imported_libraries": []string{"revela-genesis.local/core-one/genesis"}, "guardian_policy_present": fileExists(filepath.Join(s.OneRoot, "guardian", "rules.yaml")), "observed_invention_count": len(inventions), "invention_log_path": filepath.Join("core-one", "state", "events")},
		"core_two": map[string]any{"version": Version, "model_free": true, "source_execution": false, "automatic_merge": false, "mutation_outputs": "core-two/mutations/", "evolution_outputs": "core-two/evolutions/"},
		"provider": map[string]any{"provider_url_env": "REVELACODE_PROVIDER_URL", "provider_key_env": "REVELACODE_PROVIDER_KEY", "same_credential_names_as_core_one": true, "secret_disclosed": false},
	}
}

func (s *Service) Scan(ctx context.Context) (map[string]any, error) {
	if ctx == nil { ctx = context.Background() }
	select { case <-ctx.Done(): return nil, ctx.Err(); default: }
	inventory, err := s.scanRepositoryInventory()
	if err != nil { return nil, fmt.Errorf("scan repository evidence tree: %w", err) }
	items, err := s.One.ListInventions()
	if err != nil { return nil, fmt.Errorf("list Core-One inventions: %w", err) }
	metrics := make([]ToolMetrics, 0, len(items))
	for _, item := range items {
		name, _ := item["name"].(string)
		if !validName(name) { continue }
		m := s.metricForTool(name)
		if err := writeJSONFile(filepath.Join(s.CoreRoot, "metrics", name+".json"), m, 0o600); err != nil { return nil, err }
		metrics = append(metrics, m)
	}
	times, boms, safety, merges := []float64{}, []float64{}, []float64{}, []float64{}
	for _, m := range metrics {
		if m.TimeToInventMS != nil { times = append(times, *m.TimeToInventMS) }
		if m.BOMCostKES != nil { boms = append(boms, *m.BOMCostKES) }
		if m.SafetyScore != nil { safety = append(safety, *m.SafetyScore) }
		if m.HumanMergeTimeMS != nil { merges = append(merges, *m.HumanMergeTimeMS) }
	}
	var avgTime, avgBOM, avgSafety, avgMerge any
	if len(times)>0 { avgTime=average(times) }; if len(boms)>0 { avgBOM=average(boms) }; if len(safety)>0 { avgSafety=average(safety) }; if len(merges)>0 { avgMerge=average(merges) }
	research := map[string]any{
		"schema_version":"usect-two.research-evidence.v1", "observed_at":time.Now().UTC(),
		"repository_snapshot":map[string]any{"baseline_commit":"40dc1caf07419ad14f771be88fc238baa51d4480","source":"GitHub repository scan before Core-Two branch changes"},
		"integration":s.IntegrationStatus(), "repository_inventory":inventory, "production_invention_count":len(items), "observed_inventions":items,
		"average_time_to_invent_ms":avgTime, "average_bom_cost_kes":avgBOM, "average_safety_score":avgSafety, "average_human_merge_time_ms":avgMerge,
		"data_quality":map[string]any{"historical_time_measurements_available":len(times)>0,"verified_bom_costs_available":len(boms)>0,"zero_guardian_policy_file_present":fileExists(filepath.Join(s.ZeroRoot,"guardian","rules.yaml")),"synthetic_fixture_counted_as_production_tool":false},
		"note":"No invention evidence.json files were present under core-one/inventions in the scanned source snapshot. Production averages remain null until the existing system records the values. The offline_vault fixture is synthetic and is not counted as a Core-One invention.",
	}
	if err:=writeJSONFile(filepath.Join(s.CoreRoot,"research_evidence.json"),research,0o600);err!=nil{return nil,err}
	return map[string]any{"status":"ok","observed_tool_count":len(items),"metrics":metrics,"research_evidence_path":"core-two/research_evidence.json","repository_inventory":inventory,"integration":s.IntegrationStatus()},nil
}

func (s *Service) metricForTool(name string) ToolMetrics {
	m := ToolMetrics{ToolName:name,ObservedAt:time.Now().UTC(),EvidenceStatus:"no_timing_or_cost_measurement_recorded",EndpointUsageObserved:false,GuardianLogObserved:fileExists(filepath.Join(s.OneRoot,"guardian","blocked.log")),ZeroHealingEvidenceObserved:fileExists(filepath.Join(s.ZeroRoot,"audit_log","events.jsonl"))}
	evidencePath:=filepath.Join(s.OneRoot,"inventions",name,"evidence.json")
	if raw,err:=os.ReadFile(evidencePath);err==nil { var obj map[string]any; if json.Unmarshal(raw,&obj)==nil {
		if n,ok:=numberField(obj,"time_to_invent_ms","duration_ms","elapsed_ms");ok {m.TimeToInventMS=&n;m.EvidenceStatus="time_measurement_recorded"}
		if n,ok:=numberField(obj,"bom_cost_kes","estimated_bom_cost_kes");ok {m.BOMCostKES=&n}
		if n,ok:=numberField(obj,"safety_score");ok {m.SafetyScore=&n}
		if n,ok:=numberField(obj,"human_merge_time_ms","merge_time_ms");ok {m.HumanMergeTimeMS=&n}
		if n,ok:=numberField(obj,"merge_score","human_merge_score");ok {m.MergeScore=&n}
	} }
	if m.TimeToInventMS==nil {m.MeasurementNotes=append(m.MeasurementNotes,"Core-One evidence did not record end-to-end invention time; value is unknown, not zero.")}
	if m.BOMCostKES==nil {m.MeasurementNotes=append(m.MeasurementNotes,"No verified BOM cost in KES was recorded; value is unknown, not zero.")}
	m.LibraryFiles=countSourceFiles(filepath.Join(s.OneRoot,"libraries","created",name))
	m.GuardianBlockCount,_=countLogLines(filepath.Join(s.OneRoot,"guardian","blocked.log"),"")
	m.ZeroHealingEvents,_=countLogLines(filepath.Join(s.ZeroRoot,"audit_log","events.jsonl"),"heal|recovery|restore")
	m.EndpointUsageCount,m.EndpointUsageObserved=countEndpointUsage(filepath.Join(s.OneRoot,"state","events","events.jsonl"))
	return m
}
