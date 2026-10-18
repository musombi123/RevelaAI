package mind

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"revela-mind.local/core-two/provider"
	"revela-mind.local/core-two/rvx"
	zeroRVX "usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

func (s *Service) Evolve(ctx context.Context, request EvolveRequest) (EvolveResult, error) {
	if ctx == nil { ctx = context.Background() }
	objective := strings.TrimSpace(request.Objective)
	if objective == "" { objective = "improve offline_vault graph traversal efficiency" }
	toolName := strings.TrimSpace(request.ToolName)
	if toolName == "" { toolName = "offline_vault_fixture" }
	if !validName(toolName) { return EvolveResult{}, errors.New("tool_name must use lowercase letters, digits, underscore, or hyphen") }
	if allowed, reason := s.guardianDecision(objective+"\n"+toolName); !allowed {
		if logErr:=s.logBlocked("pre_mutation",objective+"\n"+toolName,reason);logErr!=nil{return EvolveResult{},fmt.Errorf("Guardian blocked request and audit logging failed: %w",logErr)}
		s.publish("blocked",map[string]any{"tool_name":toolName,"reason":reason,"source_files_created":false})
		return EvolveResult{},ErrGuardianBlocked
	}
	select{case<-ctx.Done():return EvolveResult{},ctx.Err();default:}
	if _,err:=s.Scan(ctx);err!=nil{return EvolveResult{},err}
	evals,bench,err:=evaluateCatalog(ctx);if err!=nil{return EvolveResult{},fmt.Errorf("sandbox evaluation failed: %w",err)}
	selected,ok:=selectCandidate(objective,evals);if !ok{return EvolveResult{},ErrNoQualifiedMutation}
	mutationBatch,mutationCount,err:=s.stageMutationBatch(objective,evals,bench);if err!=nil{return EvolveResult{},err}
	version,awaitPath,err:=s.stageEvolution(toolName,objective,selected,mutationBatch,evals,bench);if err!=nil{_ = os.RemoveAll(filepath.Join(s.CoreRoot,"mutations",mutationBatch));return EvolveResult{},err}
	protectionOK,protectionNote:=rvx.Probe();if !protectionOK{_ = os.RemoveAll(filepath.Join(s.CoreRoot,"evolutions",version));_ = os.RemoveAll(filepath.Join(s.CoreRoot,"mutations",mutationBatch));return EvolveResult{},errors.New("RVX protection self-test failed after staging; candidate discarded")}
	metric:=map[string]any{"tool_name":toolName,"observed_at":time.Now().UTC(),"fixture_only":true,"evidence_status":"synthetic_fixture_replay_not_production_invention","time_to_invent_ms":nil,"bom_cost_kes":nil,"human_merge_time_ms":nil,"graph_traversal_benchmark":bench,"selected_mutation":selected.ID,"improvement_type":selected.ImprovementType,"improvement_percent":selected.ImprovementPct,"production_tool_count":s.productionToolCount()}
	if err:=writeJSONFile(filepath.Join(s.CoreRoot,"metrics",toolName+".json"),metric,0o600);err!=nil{return EvolveResult{},err}
	result:=EvolveResult{Status:"await_merge",Version:version,ToolName:toolName,SelectedMutation:selected.ID,MutationBatch:mutationBatch,MutationCount:mutationCount,CandidateResults:evals,Benchmark:bench,RVXProtection:map[string]any{"passed":protectionOK,"status":protectionNote,"baseline_encryption_protection_present":false,"candidate_primitive":"AES-256-GCM","external_key_required":true,"tamper_detection_tested":true,"numeric_security_score":nil,"score_note":"Control presence is recorded; no ungrounded cryptographic strength score is invented."},ProductionEvidence:map[string]any{"core_one_historical_inventions":s.productionToolCount(),"real_time_to_invent_available":false,"verified_bom_cost_kes_available":false,"synthetic_fixture_only":true},AwaitMergePath:awaitPath,CreatedAt:time.Now().UTC()}
	mesh:=provider.FromEnvironment();if mesh.Configured(){if mesh.NotifyEvolution(ctx,map[string]any{"version":version,"tool_name":toolName,"mutation":selected.ID,"status":"await_merge"})==nil{result.ProviderNotified=true}}
	s.publish("evolution_proposed",map[string]any{"version":version,"tool_name":toolName,"selected_mutation":selected.ID,"status":"await_merge"})
	return result,nil
}

func (s *Service) guardianDecision(text string)(bool,string){
	ownRules,err:=os.ReadFile(filepath.Join(s.CoreRoot,"guardian","rules.yaml"));if err!=nil||validateCoreTwoPolicy(ownRules)!=nil{return false,"Core-Two Guardian policy missing or invalid; fail-closed mode."}
	oneDecision:=s.One.Guardian.Check(text);if !oneDecision.Allowed{return false,"Core-One Guardian: "+oneDecision.Reason}
	lower:=strings.ToLower(text)
	terms:=[]string{"weapon","weapons","weapon search","weapon efficiency","warfare","explosive","bomb","ransomware","credential theft","spyware","covert surveillance","stalk","evade detection","destroy the platform","bypass authentication","disable guardian","disable safety controls","delete audit logs","illegal operation","evade law","bypass law","violate privacy"}
	terms=append(terms,extraGuardianTerms(ownRules)...)
	for _,term:=range terms{if term!=""&&strings.Contains(lower,strings.ToLower(term)){return false,"Core-Two policy prohibits harmful or unauthorized engineering objectives."}}
	zeroPath:=filepath.Join(s.ZeroRoot,"guardian","rules.yaml")
	if raw,readErr:=os.ReadFile(zeroPath);readErr==nil{if err:=validateZeroGuardianPolicy(raw);err!=nil{return false,"Core-Zero Guardian policy exists but is invalid; fail-closed mode: "+err.Error()};policy:=strings.ToLower(string(raw));for _,term:=range []string{"weapon","warfare","explos","malware","credential","privacy","surveillance","destruction","illegal"}{if strings.Contains(policy,term)&&strings.Contains(lower,term){return false,"Core-Zero Guardian blocked the objective."}}}else if !os.IsNotExist(readErr){return false,"Core-Zero Guardian policy cannot be read; fail-closed mode."}}
	if err:=s.zeroLibraryProbe();err!=nil{return false,"Core-Zero integration probe failed; fail-closed mode: "+err.Error()}
	return true,"Core-Two and Core-One Guardian checks passed; Core-Zero library probe passed. If core-zero/guardian/rules.yaml is absent, restrictive fallback remains active and the gap is reported."
}

func extraGuardianTerms(raw []byte)[]string{scanner:=bufio.NewScanner(strings.NewReader(string(raw)));inside:=false;terms:=[]string{};for scanner.Scan(){line:=strings.TrimSpace(scanner.Text());if line=="extra_terms:"{inside=true;continue};if !inside||line==""||strings.HasPrefix(line,"#"){continue};if !strings.HasPrefix(line,"-"){break};term:=strings.Trim(strings.TrimSpace(strings.TrimPrefix(line,"-")),"\"'");if term!=""&&len(term)<=160{terms=append(terms,strings.ToLower(term))}};return terms}

func validateCoreTwoPolicy(raw []byte)error{if len(raw)==0||len(raw)>64*1024{return errors.New("policy empty or outside the 64 KiB size limit")};policy:=strings.ToLower(string(raw));for _,required:=range []string{"mode: fail_closed","core_law:","protect","extra_terms:"}{if !strings.Contains(policy,required){return fmt.Errorf("required policy marker %q is missing",required)}};for _,required:=range []string{"weapon","warfare","explos","malware","credential","privacy","surveillance","illegal","safety controls"}{if !strings.Contains(policy,required){return fmt.Errorf("required safety rule %q is missing",required)}};return nil}

func validateZeroGuardianPolicy(raw []byte)error{if len(raw)==0||len(raw)>64*1024{return errors.New("policy empty or outside the 64 KiB size limit")};policy:=strings.ToLower(string(raw));for _,required:=range []string{"mode: fail_closed","core_law:","protect"}{if !strings.Contains(policy,required){return fmt.Errorf("required policy marker %q is missing",required)}};for _,category:=range []struct{name string; alternatives []string}{{"weapons",[]string{"weapon"}},{"warfare",[]string{"warfare"}},{"explosives",[]string{"explos"}},{"malware and credential theft",[]string{"malware","credential"}},{"privacy",[]string{"privacy"}}}{found:=false;for _,marker:=range category.alternatives{if strings.Contains(policy,marker){found=true;break}};if !found{return fmt.Errorf("required safety category %q is missing",category.name)}};return nil}

func(s *Service)zeroLibraryProbe()error{if _,err:=zeroRVX.Compile("scan");err!=nil{return err};_,err:=radar.Compare(radar.Evidence{Name:"guardian-probe",Version:"v0.1.0",Benchmark:100},radar.Evidence{Name:"guardian-probe",Version:"v0.2.0",Benchmark:140});return err}
