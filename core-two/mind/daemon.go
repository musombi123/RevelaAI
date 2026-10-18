package mind

import (
	"context"
	"errors"
	"os"
	"strings"
	"time"
)

func selectCandidate(objective string, evals []CandidateEvaluation) (CandidateEvaluation, bool) {
	want := "graph-indexed"
	lower := strings.ToLower(objective)
	switch {
	case strings.Contains(lower, "bom") || strings.Contains(lower, "cost"): want = "bom-cost-ranked"
	case strings.Contains(lower, "hardware") || strings.Contains(lower, "fundi") || strings.Contains(lower, "guide"): want = "hardware-guide-structured"
	case strings.Contains(lower, "rvx") || strings.Contains(lower, "encrypt") || strings.Contains(lower, "protect"): want = "rvx-aead-envelope"
	case strings.Contains(lower, "pollinat") || strings.Contains(lower, "industry"): want = "cross-industry-pollination"
	case strings.Contains(lower, "audit"): want = "tamper-evident-audit-chain"
	case strings.Contains(lower, "input") || strings.Contains(lower, "safety"): want = "bounded-input-guard"
	case strings.Contains(lower, "dedup") || strings.Contains(lower, "evidence"): want = "evidence-hash-dedup"
	case strings.Contains(lower, "path"): want = "repository-path-index"
	case strings.Contains(lower, "cache") || strings.Contains(lower, "spec"): want = "canonical-spec-cache"
	}
	for _,e:=range evals {if e.ID==want&&e.Passed&&e.ImprovementPct>0{return e,true}}
	var best CandidateEvaluation;found:=false;bestScore:=-1.0
	for _,e:=range evals {if !e.Passed||e.ImprovementPct<=0{continue};score:=e.ImprovementPct;if score>200{score=200};if e.ID=="graph-indexed"{score+=1};if score>bestScore{best,bestScore,found=e,score,true}}
	return best,found
}

func (s *Service) RunDaemon(ctx context.Context, interval time.Duration) {
	if interval<=0{interval=24*time.Hour}
	cycle:=func(){if _,err:=s.Scan(ctx);err!=nil{s.publish("mirror_error",map[string]any{"error":err.Error()});return};if strings.EqualFold(strings.TrimSpace(os.Getenv("MIND_AUTO_EVOLVE")),"0")||strings.EqualFold(strings.TrimSpace(os.Getenv("MIND_AUTO_EVOLVE")),"false"){return};if _,err:=s.Evolve(ctx,EvolveRequest{ToolName:"offline_vault_fixture",Objective:"improve offline_vault graph traversal efficiency"});err!=nil&&!errors.Is(err,ErrGuardianBlocked){s.publish("evolution_cycle_error",map[string]any{"error":err.Error()})}}
	cycle();ticker:=time.NewTicker(interval);defer ticker.Stop();for{select{case<-ctx.Done():return;case<-ticker.C:cycle()}}
}
