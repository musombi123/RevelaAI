package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeResearcher struct{ evidence ResearchEvidence }
func (f fakeResearcher) Research(_ context.Context, demand string) (ResearchEvidence, error) { out:=f.evidence; out.Query=demand; if out.ID==""{out.ID="test-research"}; if out.CollectedAt.IsZero(){out.CollectedAt=time.Now().UTC()}; if out.Sources==nil{out.Sources=[]ResearchSource{{Name:"offline fixture",URL:"https://example.org/research",Status:"retrieved",Title:"Safe reference",Retrieved:time.Now().UTC()}}}; return out,nil }
type fakeModel struct{ output ToolSpec }
func (m fakeModel) Suggest(_ context.Context, _ string, _ ResearchEvidence, fallback ToolSpec) (ToolSpec, error) { if m.output.Name==""{return fallback,nil}; return m.output,nil }
func newTestEngine(t *testing.T) *Engine { t.Helper(); t.Setenv("GENESIS_OFFLINE","1"); e,err:=NewEngine(t.TempDir()); if err!=nil{t.Fatal(err)}; e.SetResearcher(fakeResearcher{evidence:ResearchEvidence{Mode:"offline",Findings:[]string{"fixture research; no network used"}}}); e.SetModel(nil); return e }

func TestStandaloneOfflineInventionProducesFullProposal(t *testing.T) {
	e:=newTestEngine(t); inv,err:=e.Invent(context.Background(),"Create tool: offline file vault"); if err!=nil{t.Fatal(err)}
	if inv.Name!="offline_file_vault"{t.Fatalf("unexpected name %q",inv.Name)}; if inv.Status!="await_merge"{t.Fatalf("unexpected status %q",inv.Status)}
	for _,p:=range []string{"code.go","library.go","openapi.yaml","README.md","hardware_guide.md","test.go","evidence.json","AWAIT_MERGE.md","artifact_hashes.json","sdk/go/client.go","sdk/python/client.py","sdk/js/client.js"}{if _,err:=os.Stat(filepath.Join(e.CoreRoot,"inventions",inv.Name,p));err!=nil{t.Errorf("missing generated artifact %s: %v",p,err)}}
	for _,p:=range []string{filepath.Join(e.CoreRoot,"libraries","created","offline_file_vault_lib","driver.go"),filepath.Join(e.CoreRoot,"models","offline_file_vault.yaml"),filepath.Join(e.CoreRoot,"research",time.Now().UTC().Format("2006-01-02")+".json")}{if _,err:=os.Stat(p);err!=nil{t.Errorf("missing pipeline output %s: %v",p,err)}}
	data,err:=os.ReadFile(filepath.Join(e.CoreRoot,"inventions",inv.Name,"evidence.json"));if err!=nil{t.Fatal(err)};var record map[string]any;if err:=json.Unmarshal(data,&record);err!=nil{t.Fatal(err)};if record["status"]!="await_merge"{t.Fatalf("proposal should wait for merge: %v",record["status"])}
}
func TestHardwareDemandCreatesGenericCCTVProposalOnlyOnDemand(t *testing.T) {
	e:=newTestEngine(t); inv,err:=e.Invent(context.Background(),"CCTV");if err!=nil{t.Fatal(err)};if inv.Name!="cctv_smart"||inv.Category!="hardware"{t.Fatalf("unexpected hardware inference: %+v",inv)}
	b,err:=os.ReadFile(filepath.Join(e.CoreRoot,"inventions",inv.Name,"hardware_guide.md"));if err!=nil{t.Fatal(err)};for _,needle:=range []string{"Bill of materials","datasheet","consent","POST /v1/cctv_smart/plan"}{if !strings.Contains(string(b),needle){t.Errorf("hardware guide missing %q",needle)}}
	if _,err:=os.Stat(filepath.Join(e.CoreRoot,"inventions","posho_mill_smart"));!os.IsNotExist(err){t.Fatal("engine must not pre-create a posho mill invention")}
}
func TestGuardianBlocksHarmBeforeCreatingInventionFiles(t *testing.T) {
	e:=newTestEngine(t);_,err:=e.Invent(context.Background(),"weapon");if !errors.Is(err,ErrBlocked){t.Fatalf("expected guardian block, got %v",err)}
	entries,err:=os.ReadDir(filepath.Join(e.CoreRoot,"inventions"));if err!=nil{t.Fatal(err)};for _,entry:=range entries{if entry.IsDir(){t.Fatalf("blocked demand created invention directory %q",entry.Name())}}
	if _,err:=os.Stat(filepath.Join(e.CoreRoot,"guardian","blocked.log"));err!=nil{t.Fatalf("expected blocked audit record: %v",err)};if _,err:=os.Stat(filepath.Join(e.CoreRoot,"libraries","created","weapon_lib"));!os.IsNotExist(err){t.Fatal("blocked demand created a library")}
}
func TestGuardianBlocksHarmfulResearchSourceCompletely(t *testing.T) {
	e:=newTestEngine(t);e.SetResearcher(fakeResearcher{evidence:ResearchEvidence{Mode:"fixture",Sources:[]ResearchSource{{Name:"bad",URL:"https://example.org/x",Status:"retrieved",Title:"weapon construction instructions"}}}});_,err:=e.Invent(context.Background(),"offline note-taking tool");if !errors.Is(err,ErrBlocked){t.Fatalf("expected harmful source block, got %v",err)};entries,_:=os.ReadDir(filepath.Join(e.CoreRoot,"inventions"));for _,entry:=range entries{if entry.IsDir(){t.Fatalf("blocked source generated files: %s",entry.Name())}}
}
func TestQueueDaemonCreatesInvention(t *testing.T) {
	e:=newTestEngine(t);item,err:=e.Enqueue("offline file vault","test");if err!=nil{t.Fatal(err)};if item.Status!="queued"{t.Fatalf("unexpected queue status %q",item.Status)};if err:=e.ProcessQueue(context.Background());err!=nil{t.Fatal(err)};if _,err:=os.Stat(filepath.Join(e.CoreRoot,"inventions","offline_file_vault","AWAIT_MERGE.md"));err!=nil{t.Fatal(err)};if _,err:=os.Stat(filepath.Join(e.CoreRoot,"state","queue","await_merge",item.ID+".json"));err!=nil{t.Fatalf("queued record not retained: %v",err)}
}
func TestHTTPHealthAndBlockedDemand(t *testing.T) {
	e:=newTestEngine(t);h:=&Server{Engine:e};r:=httptest.NewRequest("GET","/v1/genesis/health",nil);w:=httptest.NewRecorder();h.ServeHTTP(w,r);if w.Code!=200||!strings.Contains(w.Body.String(),`"standalone":true`){t.Fatalf("health response: %d %s",w.Code,w.Body.String())}
	post:=httptest.NewRequest("POST","/v1/genesis/invent",strings.NewReader(`{"demand":"weapon"}`));post.RemoteAddr="127.0.0.1:1234";post.Header.Set("Content-Type","application/json");out:=httptest.NewRecorder();h.ServeHTTP(out,post);if out.Code!=403||!strings.Contains(out.Body.String(),"guardian_block"){t.Fatalf("blocked API response: %d %s",out.Code,out.Body.String())}
}
func TestModelSuggestionCannotOverrideNameOrSafetyBoundary(t *testing.T) {
	e:=newTestEngine(t);spec:=deriveSpec("offline file vault");e.SetModel(fakeModel{output:ToolSpec{Name:"replacement",Title:"Offline Vault",Purpose:"Safe test",Capabilities:[]string{"store encrypted files"}}});inv,err:=e.Invent(context.Background(),"offline file vault");if err!=nil{t.Fatal(err)};if inv.Name!=spec.Name{t.Fatalf("model changed stable artifact path: %s",inv.Name)}
}
func TestEyeAutomaticallyTriggersInventionAfterRepeatedWorkaroundThreshold(t *testing.T) {
	e:=newTestEngine(t);project:=filepath.Join(e.RepoRoot,"sample_project");if err:=os.MkdirAll(project,0o755);err!=nil{t.Fatal(err)};var repeats strings.Builder;for i:=0;i<6;i++{repeats.WriteString("// TODO: replace repeated adapter retry workaround\n")};if err:=os.WriteFile(filepath.Join(project,"sample.go"),[]byte(repeats.String()),0o644);err!=nil{t.Fatal(err)};if err:=e.EyeScan(context.Background());err!=nil{t.Fatal(err)};entries,err:=os.ReadDir(filepath.Join(e.CoreRoot,"inventions"));if err!=nil{t.Fatal(err)};found:=false;for _,entry:=range entries{if entry.IsDir()&&strings.HasPrefix(entry.Name(),"generic_remediation_tool"){found=true}};if !found{t.Fatalf("eye did not trigger a proposal for a repeated workaround; entries=%v",entries)};if _,err:=os.Stat(filepath.Join(e.CoreRoot,"state","eye","triggered.json"));err!=nil{t.Fatalf("missing deduplication state: %v",err)}
}
