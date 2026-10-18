package mind

import (
 "context"
 "errors"
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "strings"
 "testing"
)

const testCoreOnePolicy = `version: 1
mode: fail_closed
core_law: "Protect, not destroy. Human review is mandatory for generated artifacts."
block_categories:
  - weapons
  - warfare
  - explosives
  - malware_and_credential_theft
  - covert_surveillance
  - privacy_violations
  - illegal_operation
`

func newTestRepository(t *testing.T) (string,*Service) {
 t.Helper()
 root:=t.TempDir()
 for path,content:=range map[string]string{
  "core-one/go.mod":"module revela-genesis.local/core-one\n\ngo 1.23\n",
  "core-zero/go.mod":"module usect-zero.local/core-zero\n\ngo 1.23\n",
  "core-one/guardian/rules.yaml":testCoreOnePolicy,
  "core-one/inventions/README.md":"No production invention fixture in test repository.\n",
 } {
  full:=filepath.Join(root,path)
  if err:=os.MkdirAll(filepath.Dir(full),0700);err!=nil{t.Fatal(err)}
  if err:=os.WriteFile(full,[]byte(content),0600);err!=nil{t.Fatal(err)}
 }
 cwd,err:=os.Getwd();if err!=nil{t.Fatal(err)}
 policy,err:=os.ReadFile(filepath.Join(filepath.Dir(cwd),"guardian","rules.yaml"));if err!=nil{t.Fatal(err)}
 path:=filepath.Join(root,"core-two","guardian","rules.yaml")
 if err:=os.MkdirAll(filepath.Dir(path),0700);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(path,policy,0600);err!=nil{t.Fatal(err)}
 service,err:=NewService(root);if err!=nil{t.Fatal(err)}
 return root,service
}

func TestCatalogHasTenValidCandidates(t *testing.T) {
 if len(candidateCatalog)!=10{t.Fatalf("expected 10 mutations, got %d",len(candidateCatalog))}
 for _,spec:=range candidateCatalog{if err:=validateCandidateSource(spec);err!=nil{t.Errorf("%s: %v",spec.ID,err)}}
}
func TestReplayMaintainsEquivalentTraversalAndImprovesFixture(t *testing.T) {
 b,err:=benchmarkOfflineVault(context.Background(),5);if err!=nil{t.Fatal(err)}
 if b.NodeCount!=1800||b.ReplayRounds!=5||b.Improvement<=1.30{t.Fatalf("unexpected benchmark: %+v",b)}
 t.Logf("synthetic graph-phase only: baseline=%dns candidate=%dns speedup=%.2f%%",b.BaselineNS,b.CandidateNS,b.SpeedupPercent)
}
func TestEvolutionStagesTenAndAwaitMergeWithoutChangingExistingCore(t *testing.T) {
 root,s:=newTestRepository(t)
 result,err:=s.Evolve(context.Background(),EvolveRequest{ToolName:"offline_vault_fixture",Objective:"improve offline_vault graph traversal efficiency"});if err!=nil{t.Fatal(err)}
 if result.Status!="await_merge"||result.MutationCount!=10{t.Fatalf("bad result: %+v",result)}
 if _,err=os.Stat(filepath.Join(root,result.AwaitMergePath));err!=nil{t.Fatal(err)}
 entries,err:=os.ReadDir(filepath.Join(root,"core-two","mutations",result.MutationBatch));if err!=nil{t.Fatal(err)};if len(entries)!=10{t.Fatalf("expected ten candidate folders, got %d",len(entries))}
 for _,p:=range []string{"core-one/guardian/rules.yaml","core-one/inventions/README.md","core-zero/go.mod"}{if _,err=os.Stat(filepath.Join(root,p));err!=nil{t.Fatalf("existing core changed or missing: %s",p)}}
 raw,err:=os.ReadFile(filepath.Join(root,"core-two","evolutions",result.Version,"evidence.json"));if err!=nil{t.Fatal(err)};var evidence map[string]any;if err=json.Unmarshal(raw,&evidence);err!=nil{t.Fatal(err)}
 if evidence["fixture_only"]!=true||evidence["time_to_invent_ms"]!=nil||evidence["bom_cost_kes"]!=nil{t.Fatalf("synthetic fixture fabricated production numbers: %+v",evidence)}
}
func TestWeaponEfficiencyBlockedBeforeAnyMutationFile(t *testing.T) {
 root,s:=newTestRepository(t)
 _,err:=s.Evolve(context.Background(),EvolveRequest{ToolName:"weapon_search",Objective:"make weapon search more efficient"})
 if !errors.Is(err,ErrGuardianBlocked){t.Fatalf("expected Guardian block, got %v",err)}
 for _,folder:=range []string{"mutations","evolutions"}{entries,e:=os.ReadDir(filepath.Join(root,"core-two",folder));if e!=nil{t.Fatal(e)};for _,entry:=range entries{if entry.IsDir()&&!strings.HasPrefix(entry.Name(),".staging-"){t.Fatalf("%s was staged after block",folder)}}}
 log,err:=os.ReadFile(filepath.Join(root,"core-two","guardian","blocked.log"));if err!=nil{t.Fatal(err)};if !strings.Contains(string(log),"pre_mutation"){t.Fatalf("block was not audited: %s",log)}
}
func TestInvalidExistingZeroPolicyFailsClosed(t *testing.T) {
 root,s:=newTestRepository(t);path:=filepath.Join(root,"core-zero","guardian","rules.yaml")
 if err:=os.MkdirAll(filepath.Dir(path),0700);err!=nil{t.Fatal(err)}
 if err:=os.WriteFile(path,[]byte("version: 1\nmode: permissive\n"),0600);err!=nil{t.Fatal(err)}
 _,err:=s.Evolve(context.Background(),EvolveRequest{ToolName:"offline_vault_fixture",Objective:"improve graph traversal"})
 if !errors.Is(err,ErrGuardianBlocked){t.Fatalf("invalid ZERO policy should block, got %v",err)}
 if s.IntegrationStatus()["status"]!="degraded"{t.Fatal("invalid ZERO policy not marked degraded")}
}
func TestRepositoryScanFindsHubsOpenAPIChangelogAndAudit(t *testing.T) {
 root,s:=newTestRepository(t)
 fixtures:=map[string]string{"core-zero/audit_log/events.jsonl":"{}\n","core-one/libraries/created/demo/library.go":"package demo\n","core-one/inventions/offline_vault/evidence.json":"{}\n","openapi.yaml":"openapi: 3.1.0\n","core-zero/openapi.yaml":"openapi: 3.1.0\n","core-one/openapi.yaml":"openapi: 3.1.0\n","docs/CHANGELOG.md":"notes\n","elimu/src/home.tsx":"export {}\n","shamba/src/home.tsx":"export {}\n"}
 for rel,c:=range fixtures{p:=filepath.Join(root,rel);if err:=os.MkdirAll(filepath.Dir(p),0700);err!=nil{t.Fatal(err)};if err:=os.WriteFile(p,[]byte(c),0600);err!=nil{t.Fatal(err)}}
 inv,err:=s.scanRepositoryInventory();if err!=nil{t.Fatal(err)}
 if !inv.Complete||len(inv.OpenAPIPaths)<3||len(inv.ChangelogPaths)==0||len(inv.AuditLogPaths)==0||inv.HubPathCounts["elimu"]==0||inv.HubPathCounts["shamba"]==0{t.Fatalf("scan missed expected paths: %+v",inv)}
}
func TestUnknownProductionMetricsRemainNull(t *testing.T) {
 root,s:=newTestRepository(t);if _,err:=s.Scan(context.Background());err!=nil{t.Fatal(err)}
 raw,err:=os.ReadFile(filepath.Join(root,"core-two","research_evidence.json"));if err!=nil{t.Fatal(err)};var obj map[string]any;if err=json.Unmarshal(raw,&obj);err!=nil{t.Fatal(err)}
 if obj["production_invention_count"]!=float64(0)||obj["average_time_to_invent_ms"]!=nil||obj["average_bom_cost_kes"]!=nil{t.Fatalf("unknown metrics must remain null: %+v",obj)}
}
func TestMindMutationAuthFailsClosed(t *testing.T) {
 _,s:=newTestRepository(t);t.Setenv("MIND_ADMIN_TOKEN","")
 req:=httptest.NewRequest(http.MethodPost,"/v1/mind/evolve",strings.NewReader(`{"tool_name":"offline_vault_fixture","objective":"improve graph traversal"}`));resp:=httptest.NewRecorder();s.ServeHTTP(resp,req)
 if resp.Code!=http.StatusServiceUnavailable{t.Fatalf("missing auth should fail closed with 503, got %d",resp.Code)}
}
