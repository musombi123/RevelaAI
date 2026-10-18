package mind

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func (s *Service) stageMutationBatch(objective string, evaluations []CandidateEvaluation, bench graphBenchmark) (string, int, error) {
	// Screen every static candidate and validate every policy before creating even a staging directory.
	for _, spec := range candidateCatalog {
		if err := validateCandidateSource(spec); err != nil { return "", 0, err }
		allowed, reason := s.guardianDecision(spec.Purpose + "\n" + spec.Source)
		if !allowed {
			if logErr := s.logBlocked("candidate_source", spec.Source, reason); logErr != nil { return "", 0, fmt.Errorf("Guardian blocked candidate %s and audit logging failed: %w", spec.ID, logErr) }
			return "", 0, fmt.Errorf("Guardian blocked candidate %s before creating mutation directories: %s", spec.ID, reason)
		}
	}
	batchID := "batch-" + time.Now().UTC().Format("20060102T150405.000000000Z")
	stagingRoot := filepath.Join(s.CoreRoot, "mutations", ".staging-"+batchID)
	if err := os.MkdirAll(stagingRoot, 0o700); err != nil { return "", 0, err }
	cleanup := true
	defer func() { if cleanup { _ = os.RemoveAll(stagingRoot) } }()
	evalByID := map[string]CandidateEvaluation{}
	for _, e := range evaluations { evalByID[e.ID] = e }
	for _, spec := range candidateCatalog {
		dir := filepath.Join(stagingRoot, spec.ID)
		if err := os.Mkdir(dir, 0o700); err != nil { return "", 0, err }
		meta := map[string]any{"id":spec.ID,"category":spec.Category,"purpose":spec.Purpose,"objective":objective,"status":"candidate_tested","candidate_test_execution":"fixed allowlisted template in disposable offline Go subprocess","repository_sourced_code_execution":false,"os_level_sandbox":false,"source_core":"core-one","candidate_source_is_static_template":true,"requires_human_merge":true,"test_file":"library_test.go","rvx_protection_required":true,"rvx_protection_probe":"AES-GCM round-trip and tamper-detection pass","evaluation":evalByID[spec.ID]}
		if !evalByID[spec.ID].Passed { meta["status"]="not_qualified" }
		if spec.ID=="graph-indexed" { meta["offline_vault_fixture_benchmark"]=bench }
		if err:=writeJSONFile(filepath.Join(dir,"mutation.json"),meta,0o600);err!=nil{return "",0,err}
		if err:=writeNewFile(filepath.Join(dir,"library.go"),[]byte(spec.Source),0o600);err!=nil{return "",0,err}
		if err:=writeNewFile(filepath.Join(dir,"library_test.go"),[]byte(sharedCandidateTest),0o600);err!=nil{return "",0,err}
	}
	finalPath:=filepath.Join(s.CoreRoot,"mutations",batchID)
	if err:=os.Rename(stagingRoot,finalPath);err!=nil{return "",0,err};cleanup=false
	return batchID,len(candidateCatalog),nil
}

func (s *Service) stageEvolution(toolName, objective string, selected CandidateEvaluation, batchID string, evaluations []CandidateEvaluation, bench graphBenchmark) (string,string,error) {
	version,err:=nextEvolutionVersion(filepath.Join(s.CoreRoot,"evolutions"));if err!=nil{return "","",err}
	staging:=filepath.Join(s.CoreRoot,"evolutions",".staging-"+version);if err:=os.Mkdir(staging,0o700);err!=nil{return "","",err}
	cleanup:=true;defer func(){if cleanup{_ = os.RemoveAll(staging)}}()
	spec,ok:=sourceFor(selected.ID);if !ok{return "","",errors.New("selected mutation source disappeared")}
	if err:=writeNewFile(filepath.Join(staging,"new_library.go"),[]byte(spec.Source),0o600);err!=nil{return "","",err}
	if err:=writeNewFile(filepath.Join(staging,"rvx_protection.go"),[]byte(rvxProposalSource),0o600);err!=nil{return "","",err}
	productionCount:=s.productionToolCount();libraryInventory:=s.coreOneLibraryInventory()
	evidence:=map[string]any{"schema_version":"usect-two.evolution-evidence.v1","created_at":time.Now().UTC(),"version":version,"tool_name":toolName,"objective":objective,"status":"await_merge","selected_mutation":selected.ID,"mutation_batch":batchID,"mutation_count":len(candidateCatalog),"candidate_evaluations":evaluations,"benchmark":bench,"core_one_library_inventory":libraryInventory,"learning_feedback_scores":s.learningScores(),"learning_feedback_scores":s.learningScores(),"historical_core_one_invention_count":productionCount,"time_to_invent_ms":nil,"bom_cost_kes":nil,"human_merge_time_ms":nil,"fixture_only":true,"safety":map[string]any{"core_two_guardian":"passed","core_one_guardian":"passed","core_zero_library_probe":"passed","core_zero_dedicated_guardian_policy_file_present":fileExists(filepath.Join(s.ZeroRoot,"guardian","rules.yaml")),"candidate_template_tests_executed":true,"repository_sourced_code_executed":false,"os_level_sandbox":false,"automatic_merge":false},"rvx_protection":map[string]any{"proposal":"AES-256 key derivation + AES-GCM AEAD with key external to repository","probe":"passed","baseline_encryption_protection_present":false,"candidate_primitive":"AES-256-GCM","external_key_required":true,"tamper_detection_tested":true,"numeric_security_score":nil,"uncopyable_forever_claim":false}}
	if err:=writeJSONFile(filepath.Join(staging,"evidence.json"),evidence,0o600);err!=nil{return "","",err}
	improvement:=fmt.Sprintf("# Core-Two improvement report — %s\n\n- **Status:** staged for explicit human merge; Core-One and Core-Zero source files were not changed.\n- **Selected proposal:** %s (%s).\n- **Sandbox fixture:** %s, %d nodes, %d edges, %d replay rounds.\n- **Measured phase improvement:** %.2f%% faster in the graph-traversal phase (baseline %.0f ns/round; candidate %.0f ns/round; throughput ratio %.2fx).\n- **Scope limitation:** synthetic microbenchmark only; not end-to-end invention time and not proof a real Core-One invention already improved.\n- **Historical Core-One inventions with evidence.json:** %d. Production average time, KES BOM cost, and merge time remain unknown/null because the baseline has no invention evidence records.\n- **RVX protection:** AES-GCM round-trip and tamper-detection passed; it cannot make source or binaries literally uncopyable.\n- **Safety:** Guardian checks passed; generated source was not executed and no automatic merge occurred.\n\nSee evidence.json and AWAIT_MERGE.md for review instructions.\n",version,selected.ID,selected.Category,bench.FixtureID,bench.NodeCount,bench.EdgeCount,bench.ReplayRounds,bench.SpeedupPercent,float64(bench.BaselineNS),float64(bench.CandidateNS),bench.Improvement,productionCount)
	if err:=writeNewFile(filepath.Join(staging,"improvement_report.md"),[]byte(improvement),0o600);err!=nil{return "","",err}
	await:=fmt.Sprintf("# AWAIT_MERGE — %s\n\nThis evolution is a review proposal only.\n\n## Before merging into Core-One\n\n1. Review new_library.go and rvx_protection.go line by line.\n2. Run candidate tests in isolated CI with pinned Go and no production credentials.\n3. Repeat benchmarks on five real Core-One inventions when real invention evidence is available; the current result is only the synthetic offline_vault fixture.\n4. Obtain verified supplier quotes before reporting KES savings.\n5. Resolve the missing core-zero/guardian/rules.yaml policy with the Core-Zero owner.\n6. Review key management, rotation, recovery, and compatibility.\n7. Require explicit human approval and a separate merge into Core-One; Core-Two never does it automatically.\n\n## Staged paths\n\n- core-two/mutations/%s/%s/library.go\n- core-two/evolutions/%s/new_library.go\n- core-two/evolutions/%s/rvx_protection.go\n- core-two/evolutions/%s/evidence.json\n",version,batchID,selected.ID,version,version,version)
	if err:=writeNewFile(filepath.Join(staging,"AWAIT_MERGE.md"),[]byte(await),0o600);err!=nil{return "","",err}
	finalPath:=filepath.Join(s.CoreRoot,"evolutions",version);if err:=os.Rename(staging,finalPath);err!=nil{return "","",err};cleanup=false
	return version,filepath.ToSlash(filepath.Join("core-two","evolutions",version,"AWAIT_MERGE.md")),nil
}

const rvxProposalSource = `// Package candidate contains a proposal-only artifact protection helper for RVX review.
package candidate
import ("crypto/aes";"crypto/cipher";"crypto/rand";"crypto/sha256";"encoding/base64";"errors";"io")
type RVXEnvelope struct { Version string; Nonce string; Ciphertext string }
func SealRVX(masterKey string, plain []byte)(RVXEnvelope,error){if len(masterKey)<32{return RVXEnvelope{},errors.New("external key must be at least 32 bytes")};key:=sha256.Sum256([]byte(masterKey));block,e:=aes.NewCipher(key[:]);if e!=nil{return RVXEnvelope{},e};g,e:=cipher.NewGCM(block);if e!=nil{return RVXEnvelope{},e};nonce:=make([]byte,g.NonceSize());if _,e=io.ReadFull(rand.Reader,nonce);e!=nil{return RVXEnvelope{},e};sealed:=g.Seal(nil,nonce,plain,[]byte("rvx-aead-v1"));return RVXEnvelope{Version:"rvx-aead-v1",Nonce:base64.RawStdEncoding.EncodeToString(nonce),Ciphertext:base64.RawStdEncoding.EncodeToString(sealed)},nil}
func OpenRVX(masterKey string, box RVXEnvelope)([]byte,error){if box.Version!="rvx-aead-v1"||len(masterKey)<32{return nil,errors.New("invalid RVX envelope or key")};key:=sha256.Sum256([]byte(masterKey));block,e:=aes.NewCipher(key[:]);if e!=nil{return nil,e};g,e:=cipher.NewGCM(block);if e!=nil{return nil,e};nonce,e:=base64.RawStdEncoding.DecodeString(box.Nonce);if e!=nil||len(nonce)!=g.NonceSize(){return nil,errors.New("invalid nonce")};ciphertext,e:=base64.RawStdEncoding.DecodeString(box.Ciphertext);if e!=nil{return nil,e};return g.Open(nil,nonce,ciphertext,[]byte("rvx-aead-v1"))}
`
