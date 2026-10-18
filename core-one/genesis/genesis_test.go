package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"os/exec"
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
	for _,p:=range []string{"code.go","library.go","openapi.yaml","README.md","hardware_guide.md","test.go","evidence.json","capability_plan.json","AWAIT_MERGE.md","artifact_hashes.json","sdk/go/client.go","sdk/python/client.py","sdk/js/client.js"}{if _,err:=os.Stat(filepath.Join(e.CoreRoot,"inventions",inv.Name,p));err!=nil{t.Errorf("missing generated artifact %s: %v",p,err)}}
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


func TestOfflineResearchHonorsCanceledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := (&WebResearcher{Offline: true}).Research(ctx, "offline file vault")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected canceled research to stop immediately, got %v", err)
	}
}

func TestModelCannotDowngradeHardwareClassification(t *testing.T) {
	e := newTestEngine(t)
	candidate := deriveSpec("CCTV")
	candidate.Category = "software"
	candidate.Industry = "general"
	candidate.NeedsHardwareGuide = false
	candidate.Name = "replacement"
	candidate.Title = "Authorized camera system"
	candidate.Purpose = "A privacy-aware, consent-based camera management proposal."
	e.SetModel(fakeModel{output: candidate})
	inv, err := e.Invent(context.Background(), "CCTV")
	if err != nil {
		t.Fatal(err)
	}
	if inv.Name != "cctv_smart" || inv.Category != "hardware" {
		t.Fatalf("model changed deterministic identity/classification: %+v", inv)
	}
	if _, err := os.Stat(filepath.Join(e.CoreRoot, "inventions", inv.Name, "hardware_guide.md")); err != nil {
		t.Fatalf("model incorrectly removed required hardware guide: %v", err)
	}
}

func TestResearchFindingIsGuardianScreened(t *testing.T) {
	e := newTestEngine(t)
	e.SetResearcher(fakeResearcher{evidence: ResearchEvidence{
		Mode: "fixture",
		Findings: []string{"Malware construction instructions found in untrusted research."},
		Sources: []ResearchSource{{Name: "safe index", URL: "https://example.org", Status: "retrieved", Title: "index"}},
	}})
	_, err := e.Invent(context.Background(), "offline research notebook")
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("expected research finding to be blocked, got %v", err)
	}
	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && entry.Name() != ".staging-" {
			t.Fatalf("blocked finding left invention artifact %s", entry.Name())
		}
	}
}

func TestQueueRecoversInterruptedClaim(t *testing.T) {
	e := newTestEngine(t)
	item, err := e.Enqueue("offline file vault", "recovery-test")
	if err != nil {
		t.Fatal(err)
	}
	pending := filepath.Join(e.CoreRoot, "state", "queue", "pending", item.ID+".json")
	processingDir := filepath.Join(e.CoreRoot, "state", "queue", "processing")
	if err := os.MkdirAll(processingDir, 0o700); err != nil {
		t.Fatal(err)
	}
	processing := filepath.Join(processingDir, item.ID+".json")
	if err := os.Rename(pending, processing); err != nil {
		t.Fatal(err)
	}
	item.Status = "processing"
	item.Error = ""
	raw, err := json.Marshal(item)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(processing, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := e.ProcessQueue(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(e.CoreRoot, "state", "queue", "await_merge", item.ID+".json")); err != nil {
		t.Fatalf("interrupted queue item did not recover to await_merge: %v", err)
	}
	if _, err := os.Stat(processing); !os.IsNotExist(err) {
		t.Fatalf("processing claim was not cleaned up: %v", err)
	}
}

func TestGeneratedPackagesCompileAndCompose(t *testing.T) {
	e := newTestEngine(t)
	module := []byte("module revela-genesis.local/core-one\n\ngo 1.23\n")
	if err := os.WriteFile(filepath.Join(e.CoreRoot, "go.mod"), module, 0o644); err != nil {
		t.Fatal(err)
	}
	for _, demand := range []string{"Create tool: offline file vault", "offline second file vault"} {
		if _, err := e.Invent(context.Background(), demand); err != nil {
			t.Fatalf("generate %q: %v", demand, err)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "go", "test", "./...")
	cmd.Dir = e.CoreRoot
	cmd.Env = append(os.Environ(), "GOWORK=off")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("generated Go packages did not compile/test: %v\n%s", err, out)
	}
}

func TestRemoteMutationRequiresConfiguredToken(t *testing.T) {
	t.Setenv("GENESIS_ADMIN_TOKEN", "long-test-token")
	e := newTestEngine(t)
	r := httptest.NewRequest("POST", "/v1/genesis/invent", strings.NewReader(`{"demand":"offline file vault"}`))
	r.RemoteAddr = "203.0.113.20:3456"
	w := httptest.NewRecorder()
	(&Server{Engine: e}).ServeHTTP(w, r)
	if w.Code != 401 || !strings.Contains(w.Body.String(), "genesis_auth_required") {
		t.Fatalf("unauthorized remote mutation was not denied: %d %s", w.Code, w.Body.String())
	}
}


func TestGuardianPolicyFailsClosedWhenMissing(t *testing.T) {
	e := newTestEngine(t)
	rules := filepath.Join(e.CoreRoot, "guardian", "rules.yaml")
	if err := os.Remove(rules); err != nil {
		t.Fatal(err)
	}
	decision := e.Guardian.Check("offline file vault")
	if decision.Allowed || decision.Code != "guardian_policy_unavailable" {
		t.Fatalf("missing policy did not fail closed: %+v", decision)
	}
	if _, err := e.Invent(context.Background(), "offline file vault"); !errors.Is(err, ErrBlocked) {
		t.Fatalf("invention should be blocked when policy is unavailable, got %v", err)
	}
	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf("missing Guardian policy allowed an invention directory: %s", entry.Name())
		}
	}
}

func TestOperationalStatusReportsCoreSafetyState(t *testing.T) {
	e := newTestEngine(t)
	item, err := e.Enqueue("offline file vault", "status-test")
	if err != nil {
		t.Fatal(err)
	}
	status, err := e.OperationalStatus()
	if err != nil {
		t.Fatal(err)
	}
	if status["status"] != "ok" || status["generated_code_execution"] != false || status["automatic_merge"] != false {
		t.Fatalf("unexpected status snapshot: %#v", status)
	}
	queue, ok := status["queue"].(map[string]int)
	if !ok || queue["pending"] != 1 {
		t.Fatalf("pending queue count incorrect for %s: %#v", item.ID, status["queue"])
	}
}

func TestCanceledQueueWorkReturnsToPending(t *testing.T) {
	e := newTestEngine(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	e.SetResearcher(cancelingResearcher{cancel: cancel})
	item, err := e.Enqueue("offline file vault", "cancel-test")
	if err != nil {
		t.Fatal(err)
	}
	err = e.ProcessQueue(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected canceled queue cycle, got %v", err)
	}
	pending := filepath.Join(e.CoreRoot, "state", "queue", "pending", item.ID+".json")
	if _, err := os.Stat(pending); err != nil {
		t.Fatalf("canceled work was not retained for retry: %v", err)
	}
}

type cancelingResearcher struct { cancel context.CancelFunc }
func (r cancelingResearcher) Research(ctx context.Context, _ string) (ResearchEvidence, error) {
	r.cancel()
	return ResearchEvidence{}, ctx.Err()
}


func TestCapabilityPlannerBuildsGraphAndFlagsUnresolvedRequirements(t *testing.T) {
	e := newTestEngine(t)
	spec := deriveSpec("Create tool: offline payment controller with motor")
	plan, err := BuildCapabilityPlan(spec, ResearchEvidence{
		Mode: "offline",
		Sources: []ResearchSource{{Name: "fixture", URL: "https://example.org/spec", Status: "retrieved", Title: "Safe engineering reference"}},
	}, e.CoreRoot)
	if err != nil {
		t.Fatal(err)
	}
	if plan.Invention != spec.Name || !plan.HumanApprovalNeeded || plan.ExecutionPolicy != "proposal_only" {
		t.Fatalf("unexpected capability plan envelope: %+v", plan)
	}
	required := map[string]bool{}
	for _, req := range plan.Requirements {
		required[req.Capability] = true
	}
	for _, want := range []string{
		"offline operation",
		"transaction idempotency and reconciliation",
		"hardware safety and fail-safe control",
		"hardware integration and datasheet verification",
	} {
		if !required[want] {
			t.Errorf("planner omitted inferred requirement %q; requirements=%v", want, required)
		}
	}
	if plan.Coverage.Required != len(plan.Requirements) || plan.Coverage.NativeCoverage < 0 || plan.Coverage.NativeCoverage > 100 {
		t.Fatalf("invalid coverage totals: %+v", plan.Coverage)
	}
	if plan.Coverage.Unresolved == 0 || plan.Status != "await_merge_with_implementation_gaps" {
		t.Fatalf("domain-specific gaps must be explicitly reported: status=%s coverage=%+v", plan.Status, plan.Coverage)
	}
	nodes := map[string]bool{}
	for _, node := range plan.Nodes {
		if nodes[node.ID] {
			t.Errorf("duplicate capability graph node ID %q", node.ID)
		}
		nodes[node.ID] = true
	}
	if len(plan.Edges) == 0 || len(plan.AcceptanceChecks) == 0 || len(plan.UnresolvedRisks) == 0 {
		t.Fatalf("plan should include graph edges, acceptance checks and risks: %+v", plan)
	}
}

func TestCapabilityPlannerFindsReusableLibrariesButDoesNotTrustThem(t *testing.T) {
	e := newTestEngine(t)
	libDir := filepath.Join(e.CoreRoot, "libraries", "created", "transaction_idempotency_lib")
	if err := os.MkdirAll(libDir, 0o700); err != nil {
		t.Fatal(err)
	}
	meta := libraryMetadata{
		Name: "transaction_idempotency_lib",
		Category: "software",
		Industry: "commerce",
		Capabilities: []string{"validate structured input", "record traceable evidence", "transaction idempotency and reconciliation"},
		Dependencies: []string{},
	}
	if err := writeJSON(filepath.Join(libDir, "library.json"), meta); err != nil {
		t.Fatal(err)
	}
	spec := deriveSpec("Create tool: offline payment provider connector")
	plan, err := BuildCapabilityPlan(spec, ResearchEvidence{Mode: "offline"}, e.CoreRoot)
	if err != nil {
		t.Fatal(err)
	}
	foundCandidate := false
	for _, candidate := range plan.ReusableCandidates {
		if candidate.Name == meta.Name {
			foundCandidate = candidate.Status == "candidate_unverified"
		}
	}
	if !foundCandidate {
		t.Fatalf("expected transaction library to be surfaced as an unverified candidate: %+v", plan.ReusableCandidates)
	}
	foundRequirement := false
	for _, req := range plan.Requirements {
		if req.Capability == "transaction idempotency and reconciliation" {
			foundRequirement = true
			if req.Status != "reuse_candidate_unverified" {
				t.Fatalf("candidate metadata must not be reported as verified coverage: %+v", req)
			}
		}
	}
	if !foundRequirement {
		t.Fatal("payment demand did not create a transaction-idempotency requirement")
	}
}

func TestCapabilityPlanIsStagedAndExposedByHTTP(t *testing.T) {
	t.Setenv("GENESIS_ADMIN_TOKEN", "")
	e := newTestEngine(t)
	inv, err := e.Invent(context.Background(), "Create tool: offline file vault")
	if err != nil {
		t.Fatal(err)
	}
	if inv.CapabilityPlanPath == "" || inv.CapabilityCoverage.Required == 0 {
		t.Fatalf("invention response omitted capability plan summary: %+v", inv)
	}
	planPath := filepath.Join(e.CoreRoot, "inventions", inv.Name, "capability_plan.json")
	if _, err := os.Stat(planPath); err != nil {
		t.Fatalf("capability plan artifact missing: %v", err)
	}
	r := httptest.NewRequest("GET", "/v1/genesis/tools/"+inv.Name+"/capability_plan", nil)
	r.RemoteAddr = "127.0.0.1:1234"
	w := httptest.NewRecorder()
	(&Server{Engine: e}).ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "\"capability_plan\"") {
		t.Fatalf("capability plan endpoint failed: %d %s", w.Code, w.Body.String())
	}
}


func TestGuardianScreensUntrustedLibraryMetadataInCapabilityPlan(t *testing.T) {
	e := newTestEngine(t)
	libDir := filepath.Join(e.CoreRoot, "libraries", "created", "untrusted_catalog_entry")
	if err := os.MkdirAll(libDir, 0o700); err != nil {
		t.Fatal(err)
	}
	meta := libraryMetadata{
		Name: "untrusted_catalog_entry",
		Category: "software",
		Industry: "general",
		Capabilities: []string{"weapon design", "validate structured input", "record traceable evidence"},
		Dependencies: []string{},
	}
	if err := writeJSON(filepath.Join(libDir, "library.json"), meta); err != nil {
		t.Fatal(err)
	}
	_, err := e.Invent(context.Background(), "Create tool: offline file vault")
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("unsafe reusable-library metadata should block the proposal: %v", err)
	}
	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf("Guardian allowed invention generation from unsafe capability metadata: %s", entry.Name())
		}
	}
	if _, err := os.Stat(filepath.Join(e.CoreRoot, "guardian", "blocked.log")); err != nil {
		t.Fatalf("expected a blocked-plan audit entry: %v", err)
	}
}


func TestModelEnrichmentCannotDeleteCoreCapabilityRequirements(t *testing.T) {
	base := deriveSpec("Create tool: offline file vault")
	proposed := ToolSpec{
		Name: "overridden_name",
		Category: "software",
		Industry: "general",
		Capabilities: []string{"invented optional capability"},
		Inputs: []string{"extra optional input"},
		Outputs: []string{"extra optional output"},
		Safeguards: []string{"extra optional safeguard"},
	}
	merged := overlayModelMetadata(base, proposed)
	assertContainsAll := func(label string, required, actual []string) {
		t.Helper()
		present := map[string]bool{}
		for _, item := range actual {
			present[strings.ToLower(item)] = true
		}
		for _, item := range required {
			if !present[strings.ToLower(item)] {
				t.Errorf("model enrichment deleted required %s entry %q; actual=%v", label, item, actual)
			}
		}
	}
	assertContainsAll("capability", base.Capabilities, merged.Capabilities)
	assertContainsAll("input", base.Inputs, merged.Inputs)
	assertContainsAll("output", base.Outputs, merged.Outputs)
	assertContainsAll("safeguard", base.Safeguards, merged.Safeguards)
	if !containsAny(strings.ToLower(strings.Join(merged.Capabilities, " ")), "invented optional capability") {
		t.Fatal("safe model enrichment was not appended to the baseline")
	}
	if merged.Name != base.Name || merged.Category != base.Category || merged.Industry != base.Industry || merged.NeedsHardwareGuide != base.NeedsHardwareGuide {
		t.Fatalf("model enrichment changed deterministic identity or classification: %+v", merged)
	}
}
