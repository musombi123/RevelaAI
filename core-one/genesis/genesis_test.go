package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeResearcher struct {
	evidence ResearchEvidence
}

func (f fakeResearcher) Research(
	_ context.Context,
	demand string,
) (ResearchEvidence, error) {
	out := f.evidence
	out.Query = demand

	if out.ID == "" {
		out.ID = "test-research"
	}
	if out.CollectedAt.IsZero() {
		out.CollectedAt = time.Now().UTC()
	}
	if out.Sources == nil {
		out.Sources = []ResearchSource{
			{
				Name:      "offline fixture",
				URL:       "https://example.org/research",
				Status:    "retrieved",
				Title:     "Safe reference",
				Retrieved: time.Now().UTC(),
			},
		}
	}

	return out, nil
}

type fakeModel struct {
	output ToolSpec
}

func (m fakeModel) Suggest(
	_ context.Context,
	_ string,
	_ ResearchEvidence,
	fallback ToolSpec,
) (ToolSpec, error) {
	if m.output.Name == "" {
		return fallback, nil
	}
	return m.output, nil
}

type cancelingResearcher struct {
	cancel context.CancelFunc
}

func (r cancelingResearcher) Research(
	ctx context.Context,
	_ string,
) (ResearchEvidence, error) {
	r.cancel()
	return ResearchEvidence{}, ctx.Err()
}

func newTestEngine(t *testing.T) *Engine {
	t.Helper()

	t.Setenv("GENESIS_OFFLINE", "1")

	e, err := NewEngine(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}

	e.SetResearcher(fakeResearcher{
		evidence: ResearchEvidence{
			Mode:     "offline",
			Findings: []string{"fixture research; no network used"},
		},
	})
	e.SetModel(nil)

	return e
}

func assertFileExists(t *testing.T, path string) {
	t.Helper()

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("expected file %q: %v", path, err)
	}
	if !info.Mode().IsRegular() {
		t.Fatalf("expected regular file %q, got mode %s", path, info.Mode())
	}
}

func assertFileNotExists(t *testing.T, path string) {
	t.Helper()

	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatalf("expected %q not to exist, got error %v", path, err)
	}
}

func readJSONMap(t *testing.T, path string) map[string]any {
	t.Helper()

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	var result map[string]any
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatalf("decode JSON %s: %v", path, err)
	}

	return result
}

func TestStandaloneOfflineInventionProducesFullProposal(t *testing.T) {
	e := newTestEngine(t)

	inv, err := e.Invent(
		context.Background(),
		"Create tool: offline file vault",
	)
	if err != nil {
		t.Fatal(err)
	}

	if inv.Name != "offline_file_vault" {
		t.Fatalf("unexpected name %q", inv.Name)
	}
	if inv.Status != "await_merge" {
		t.Fatalf("unexpected status %q", inv.Status)
	}
	if inv.CapabilityCoverage.Required == 0 {
		t.Fatal("expected capability requirements to be included")
	}

	for _, relative := range []string{
		"code.go",
		"library.go",
		"openapi.yaml",
		"README.md",
		"hardware_guide.md",
		"test.go",
		"tool_manifest.json",
		"evidence.json",
		"capability_plan.json",
		"expansion_plan.json",
		"AWAIT_MERGE.md",
		"artifact_hashes.json",
		"sdk/go/client.go",
		"sdk/python/client.py",
		"sdk/js/client.js",
	} {
		assertFileExists(
			t,
			filepath.Join(e.CoreRoot, "inventions", inv.Name, relative),
		)
	}

	for _, path := range []string{
		filepath.Join(
			e.CoreRoot,
			"libraries",
			"created",
			"offline_file_vault_lib",
			"driver.go",
		),
		filepath.Join(
			e.CoreRoot,
			"models",
			"offline_file_vault.yaml",
		),
		filepath.Join(
			e.CoreRoot,
			"research",
			time.Now().UTC().Format("2006-01-02")+".json",
		),
	} {
		assertFileExists(t, path)
	}

	record := readJSONMap(
		t,
		filepath.Join(e.CoreRoot, "inventions", inv.Name, "evidence.json"),
	)
	if record["status"] != "await_merge" {
		t.Fatalf("proposal should wait for merge: %v", record["status"])
	}

	if record["execution"] != "not_executed" {
		t.Fatalf("proposal must not claim execution: %v", record["execution"])
	}
}

func TestExpandedForgeCreatesImplementationAndReviewArtifacts(t *testing.T) {
	e := newTestEngine(t)

	inv, err := e.Invent(
		context.Background(),
		"Create tool: offline file vault",
	)
	if err != nil {
		t.Fatal(err)
	}

	root := filepath.Join(e.CoreRoot, "inventions", inv.Name)

	for _, relative := range []string{
		"implementation_plan.json",
		"acceptance_matrix.json",
		"dependency_review.json",
		"security_review.md",
		"worldwide_context.json",
	} {
		assertFileExists(t, filepath.Join(root, relative))
	}

	implementation := readJSONMap(
		t,
		filepath.Join(root, "implementation_plan.json"),
	)
	if implementation["production_approved"] != false {
		t.Fatalf(
			"implementation plan must not claim production approval: %#v",
			implementation["production_approved"],
		)
	}
	if implementation["tests_executed_by_generator"] != false {
		t.Fatalf(
			"implementation plan must not claim tests ran: %#v",
			implementation["tests_executed_by_generator"],
		)
	}

	matrix := readJSONMap(
		t,
		filepath.Join(root, "acceptance_matrix.json"),
	)
	if matrix["status"] != "pending" {
		t.Fatalf("acceptance matrix must start pending: %v", matrix["status"])
	}

	summary, ok := matrix["summary"].(map[string]any)
	if !ok {
		t.Fatal("acceptance matrix summary is missing")
	}
	if summary["passed"] != float64(0) {
		t.Fatalf("new acceptance matrix cannot report passed checks: %#v", summary)
	}
	if summary["tests_executed"] != false {
		t.Fatalf("new acceptance matrix must not claim executed tests: %#v", summary)
	}

	securityReview, err := os.ReadFile(filepath.Join(root, "security_review.md"))
	if err != nil {
		t.Fatal(err)
	}

	for _, expected := range []string{
		"pending_review",
		"Production approval",
		"Threat-model checklist",
		"rollback",
	} {
		if !strings.Contains(string(securityReview), expected) {
			t.Errorf("security review missing %q", expected)
		}
	}
}

func TestWorldwideContextDoesNotClaimLiveVerification(t *testing.T) {
	e := newTestEngine(t)

	inv, err := e.Invent(
		context.Background(),
		"Create tool: offline file vault",
	)
	if err != nil {
		t.Fatal(err)
	}

	worldwide := readJSONMap(
		t,
		filepath.Join(
			e.CoreRoot,
			"inventions",
			inv.Name,
			"worldwide_context.json",
		),
	)

	if worldwide["live_prices_verified"] != false {
		t.Fatalf("worldwide profile must not claim live prices: %#v", worldwide)
	}
	if worldwide["live_stock_verified"] != false {
		t.Fatalf("worldwide profile must not claim verified stock: %#v", worldwide)
	}
	if worldwide["legal_compliance_verified"] != false {
		t.Fatalf("worldwide profile must not claim legal compliance: %#v", worldwide)
	}
	if worldwide["electrical_site_verified"] != false {
		t.Fatalf("worldwide profile must not claim site verification: %#v", worldwide)
	}
}

func TestHardwareDemandCreatesGenericCCTVProposalOnlyOnDemand(t *testing.T) {
	e := newTestEngine(t)

	inv, err := e.Invent(context.Background(), "CCTV")
	if err != nil {
		t.Fatal(err)
	}

	if inv.Name != "cctv_smart" || inv.Category != "hardware" {
		t.Fatalf("unexpected hardware inference: %+v", inv)
	}

	guide, err := os.ReadFile(
		filepath.Join(e.CoreRoot, "inventions", inv.Name, "hardware_guide.md"),
	)
	if err != nil {
		t.Fatal(err)
	}

	for _, needle := range []string{
		"Bill of materials",
		"datasheet",
		"consent",
		"POST /v1/cctv_smart/plan",
	} {
		if !strings.Contains(string(guide), needle) {
			t.Errorf("hardware guide missing %q", needle)
		}
	}

	assertFileNotExists(
		t,
		filepath.Join(e.CoreRoot, "inventions", "posho_mill_smart"),
	)
}

func TestDeriveSpecClassifiesHybridDemand(t *testing.T) {
	spec := deriveSpec(
		"Create tool: website for a warehouse sensor controller",
	)

	if spec.Category != "hybrid" {
		t.Fatalf("expected hybrid classification, got %q", spec.Category)
	}
	if !spec.NeedsHardwareGuide {
		t.Fatal("hybrid hardware demand must retain its hardware guide")
	}
	if spec.Industry != "logistics" {
		t.Fatalf("expected logistics classification, got %q", spec.Industry)
	}
	if !validResourceName(spec.Name) {
		t.Fatalf("invalid derived resource name %q", spec.Name)
	}
}

func TestDeriveSpecPreservesStableGenericSoftwareClassification(t *testing.T) {
	spec := deriveSpec("Create tool: offline file vault")

	if spec.Name != "offline_file_vault" {
		t.Fatalf("unexpected stable name %q", spec.Name)
	}
	if spec.Category != "software" {
		t.Fatalf("unexpected category %q", spec.Category)
	}
	if spec.NeedsHardwareGuide {
		t.Fatal("software-only demand must not require a hardware guide")
	}

	if len(spec.Safeguards) == 0 {
		t.Fatal("baseline safeguards must be generated")
	}
}

func TestGuardianBlocksHarmBeforeCreatingInventionFiles(t *testing.T) {
	e := newTestEngine(t)

	_, err := e.Invent(context.Background(), "weapon")
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("expected Guardian block, got %v", err)
	}

	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf("blocked demand created invention directory %q", entry.Name())
		}
	}

	assertFileExists(
		t,
		filepath.Join(e.CoreRoot, "guardian", "blocked.log"),
	)

	assertFileNotExists(
		t,
		filepath.Join(e.CoreRoot, "libraries", "created", "weapon_lib"),
	)
}

func TestGuardianBlocksHarmfulResearchSourceCompletely(t *testing.T) {
	e := newTestEngine(t)

	e.SetResearcher(fakeResearcher{
		evidence: ResearchEvidence{
			Mode: "fixture",
			Sources: []ResearchSource{
				{
					Name:   "bad",
					URL:    "https://example.org/x",
					Status: "retrieved",
					Title:  "weapon construction instructions",
				},
			},
		},
	})

	_, err := e.Invent(
		context.Background(),
		"offline note-taking tool",
	)
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("expected harmful source block, got %v", err)
	}

	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf("blocked source generated files: %s", entry.Name())
		}
	}
}

func TestResearchFindingIsGuardianScreened(t *testing.T) {
	e := newTestEngine(t)

	e.SetResearcher(fakeResearcher{
		evidence: ResearchEvidence{
			Mode: "fixture",
			Findings: []string{
				"Malware construction instructions found in untrusted research.",
			},
			Sources: []ResearchSource{
				{
					Name:   "safe index",
					URL:    "https://example.org",
					Status: "retrieved",
					Title:  "index",
				},
			},
		},
	})

	_, err := e.Invent(
		context.Background(),
		"offline research notebook",
	)
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf("expected research finding to be blocked, got %v", err)
	}

	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf("blocked finding left invention artifact %s", entry.Name())
		}
	}
}

func TestQueueDaemonCreatesInvention(t *testing.T) {
	e := newTestEngine(t)

	item, err := e.Enqueue("offline file vault", "test")
	if err != nil {
		t.Fatal(err)
	}
	if item.Status != "queued" {
		t.Fatalf("unexpected queue status %q", item.Status)
	}

	if err := e.ProcessQueue(context.Background()); err != nil {
		t.Fatal(err)
	}

	assertFileExists(
		t,
		filepath.Join(
			e.CoreRoot,
			"inventions",
			"offline_file_vault",
			"AWAIT_MERGE.md",
		),
	)

	assertFileExists(
		t,
		filepath.Join(
			e.CoreRoot,
			"state",
			"queue",
			"await_merge",
			item.ID+".json",
		),
	)
}

func TestQueueRejectsMalformedRecord(t *testing.T) {
	e := newTestEngine(t)

	pending := filepath.Join(e.CoreRoot, "state", "queue", "pending")
	if err := os.MkdirAll(pending, 0o700); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(pending, "demand-invalid.json")
	if err := os.WriteFile(path, []byte(`{"id":""}`), 0o600); err != nil {
		t.Fatal(err)
	}

	err := e.ProcessQueue(context.Background())
	if err == nil {
		t.Fatal("expected malformed queue record to be reported")
	}

	failed, readErr := os.ReadDir(
		filepath.Join(e.CoreRoot, "state", "queue", "failed"),
	)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if len(failed) == 0 {
		t.Fatal("malformed queue record was not quarantined")
	}

	assertFileNotExists(t, path)
}

func TestQueueRejectsOversizedRecord(t *testing.T) {
	e := newTestEngine(t)

	pending := filepath.Join(e.CoreRoot, "state", "queue", "pending")
	if err := os.MkdirAll(pending, 0o700); err != nil {
		t.Fatal(err)
	}

	path := filepath.Join(pending, "demand-oversized.json")
	data := strings.Repeat("x", maxQueueRecordBytes+1)

	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}

	err := e.ProcessQueue(context.Background())
	if err == nil {
		t.Fatal("expected oversized queue entry to be reported")
	}

	failed, readErr := os.ReadDir(
		filepath.Join(e.CoreRoot, "state", "queue", "failed"),
	)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if len(failed) == 0 {
		t.Fatal("oversized queue entry was not quarantined")
	}
}

func TestHTTPHealthAndBlockedDemand(t *testing.T) {
	e := newTestEngine(t)
	h := &Server{Engine: e}

	r := httptest.NewRequest(
		"GET",
		"/v1/genesis/health",
		nil,
	)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)

	if w.Code != 200 ||
		!strings.Contains(w.Body.String(), `"standalone":true`) ||
		!strings.Contains(w.Body.String(), `"signing_key_configured":`) {
		t.Fatalf("health response: %d %s", w.Code, w.Body.String())
	}

	post := httptest.NewRequest(
		"POST",
		"/v1/genesis/invent",
		strings.NewReader(`{"demand":"weapon"}`),
	)
	post.RemoteAddr = "127.0.0.1:1234"
	post.Header.Set("Content-Type", "application/json")

	out := httptest.NewRecorder()
	h.ServeHTTP(out, post)

	if out.Code != 403 ||
		!strings.Contains(out.Body.String(), "guardian_block") {
		t.Fatalf(
			"blocked API response: %d %s",
			out.Code,
			out.Body.String(),
		)
	}
}

func TestModelSuggestionCannotOverrideNameOrSafetyBoundary(t *testing.T) {
	e := newTestEngine(t)
	spec := deriveSpec("offline file vault")

	e.SetModel(fakeModel{
		output: ToolSpec{
			Name:         "replacement",
			Title:        "Offline Vault",
			Purpose:      "Safe test",
			Capabilities: []string{"store encrypted files"},
		},
	})

	inv, err := e.Invent(context.Background(), "offline file vault")
	if err != nil {
		t.Fatal(err)
	}

	if inv.Name != spec.Name {
		t.Fatalf("model changed stable artifact path: %s", inv.Name)
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

	assertFileExists(
		t,
		filepath.Join(
			e.CoreRoot,
			"inventions",
			inv.Name,
			"hardware_guide.md",
		),
	)
}

func TestEyeAutomaticallyTriggersInventionAfterRepeatedWorkaroundThreshold(t *testing.T) {
	e := newTestEngine(t)

	// Eye's improved fingerprint counts distinct files, not repeated lines
	// in one file. Create the same signature in six separate source files.
	project := filepath.Join(e.RepoRoot, "sample_project")
	if err := os.MkdirAll(project, 0o755); err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 6; i++ {
		path := filepath.Join(project, "sample_"+string(rune('a'+i))+".go")
		content := []byte(
			"package sample\n\n" +
				"// TODO: replace repeated adapter retry workaround\n" +
				"func Example() {}\n",
		)

		if err := os.WriteFile(path, content, 0o644); err != nil {
			t.Fatal(err)
		}
	}

	if err := e.EyeScan(context.Background()); err != nil {
		t.Fatal(err)
	}

	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}

	found := false
	for _, entry := range entries {
		if entry.IsDir() &&
			strings.HasPrefix(entry.Name(), "generic_remediation_tool") {
			found = true
		}
	}
	if !found {
		t.Fatalf(
			"Eye did not trigger a proposal for a repeated workaround; entries=%v",
			entries,
		)
	}

	assertFileExists(
		t,
		filepath.Join(e.CoreRoot, "state", "eye", "triggered.json"),
	)
}

func TestOfflineResearchHonorsCanceledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := (&WebResearcher{Offline: true}).Research(
		ctx,
		"offline file vault",
	)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected canceled research to stop immediately, got %v", err)
	}
}

func TestQueueRecoversInterruptedClaim(t *testing.T) {
	e := newTestEngine(t)

	item, err := e.Enqueue("offline file vault", "recovery-test")
	if err != nil {
		t.Fatal(err)
	}

	pending := filepath.Join(
		e.CoreRoot,
		"state",
		"queue",
		"pending",
		item.ID+".json",
	)
	processingDir := filepath.Join(
		e.CoreRoot,
		"state",
		"queue",
		"processing",
	)

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

	assertFileExists(
		t,
		filepath.Join(
			e.CoreRoot,
			"state",
			"queue",
			"await_merge",
			item.ID+".json",
		),
	)

	assertFileNotExists(t, processing)
}

func TestGeneratedPackagesCompileAndCompose(t *testing.T) {
	e := newTestEngine(t)

	module := []byte("module revela-genesis.local/core-one\n\ngo 1.23\n")
	if err := os.WriteFile(filepath.Join(e.CoreRoot, "go.mod"), module, 0o644); err != nil {
		t.Fatal(err)
	}

	for _, demand := range []string{
		"Create tool: offline file vault",
		"offline second file vault",
	} {
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

	r := httptest.NewRequest(
		"POST",
		"/v1/genesis/invent",
		strings.NewReader(`{"demand":"offline file vault"}`),
	)
	r.RemoteAddr = "203.0.113.20:3456"

	w := httptest.NewRecorder()
	(&Server{Engine: e}).ServeHTTP(w, r)

	if w.Code != 401 ||
		!strings.Contains(w.Body.String(), "genesis_auth_required") {
		t.Fatalf(
			"unauthorized remote mutation was not denied: %d %s",
			w.Code,
			w.Body.String(),
		)
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
			t.Fatalf(
				"missing Guardian policy allowed an invention directory: %s",
				entry.Name(),
			)
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

	if status["status"] != "ok" ||
		status["generated_code_execution"] != false ||
		status["automatic_merge"] != false {
		t.Fatalf("unexpected status snapshot: %#v", status)
	}

	queue, ok := status["queue"].(map[string]int)
	if !ok || queue["pending"] != 1 {
		t.Fatalf(
			"pending queue count incorrect for %s: %#v",
			item.ID,
			status["queue"],
		)
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

	pending := filepath.Join(
		e.CoreRoot,
		"state",
		"queue",
		"pending",
		item.ID+".json",
	)
	assertFileExists(t, pending)
}

func TestCapabilityPlannerBuildsGraphAndFlagsUnresolvedRequirements(t *testing.T) {
	e := newTestEngine(t)

	spec := deriveSpec("Create tool: offline payment controller with motor")

	plan, err := BuildCapabilityPlan(
		spec,
		ResearchEvidence{
			Mode: "offline",
			Sources: []ResearchSource{
				{
					Name:   "fixture",
					URL:    "https://example.org/spec",
					Status: "retrieved",
					Title:  "Safe engineering reference",
				},
			},
		},
		e.CoreRoot,
	)
	if err != nil {
		t.Fatal(err)
	}

	if plan.Invention != spec.Name ||
		!plan.HumanApprovalNeeded ||
		plan.ExecutionPolicy != "proposal_only" {
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
			t.Errorf(
				"planner omitted inferred requirement %q; requirements=%v",
				want,
				required,
			)
		}
	}

	if plan.Coverage.Required != len(plan.Requirements) ||
		plan.Coverage.NativeCoverage < 0 ||
		plan.Coverage.NativeCoverage > 100 {
		t.Fatalf("invalid coverage totals: %+v", plan.Coverage)
	}

	if plan.Coverage.Unresolved == 0 ||
		plan.Status != "await_merge_with_implementation_gaps" {
		t.Fatalf(
			"domain-specific gaps must be explicitly reported: status=%s coverage=%+v",
			plan.Status,
			plan.Coverage,
		)
	}

	nodes := map[string]bool{}
	for _, node := range plan.Nodes {
		if nodes[node.ID] {
			t.Errorf("duplicate capability graph node ID %q", node.ID)
		}
		nodes[node.ID] = true
	}

	if len(plan.Edges) == 0 ||
		len(plan.AcceptanceChecks) == 0 ||
		len(plan.UnresolvedRisks) == 0 {
		t.Fatalf(
			"plan should include graph edges, acceptance checks and risks: %+v",
			plan,
		)
	}
}

func TestCapabilityCoverageDoesNotClaimVerifiedImplementations(t *testing.T) {
	e := newTestEngine(t)

	spec := deriveSpec("Create tool: offline file vault")
	plan, err := BuildCapabilityPlan(
		spec,
		ResearchEvidence{Mode: "offline"},
		e.CoreRoot,
	)
	if err != nil {
		t.Fatal(err)
	}

	if plan.Coverage.VerifiedImplementationCount != 0 {
		t.Fatalf(
			"planner must not claim verified implementations: %+v",
			plan.Coverage,
		)
	}

	if plan.Coverage.Required !=
		plan.Coverage.NativeContracts+
			plan.Coverage.LibraryCandidates+
			plan.Coverage.Unresolved {
		t.Fatalf("coverage categories do not reconcile: %+v", plan.Coverage)
	}

	if plan.SchemaVersion == "" || plan.PlanID == "" {
		t.Fatalf("capability plan is missing schema/version identity: %+v", plan)
	}
}

func TestCapabilityPlannerFindsReusableLibrariesButDoesNotTrustThem(t *testing.T) {
	e := newTestEngine(t)

	libDir := filepath.Join(
		e.CoreRoot,
		"libraries",
		"created",
		"transaction_idempotency_lib",
	)
	if err := os.MkdirAll(libDir, 0o700); err != nil {
		t.Fatal(err)
	}

	meta := libraryMetadata{
		Name:         "transaction_idempotency_lib",
		Category:     "software",
		Industry:     "commerce",
		Capabilities: []string{
			"validate structured input",
			"record traceable evidence",
			"transaction idempotency and reconciliation",
		},
		Dependencies: []string{},
	}

	if err := writeJSON(filepath.Join(libDir, "library.json"), meta); err != nil {
		t.Fatal(err)
	}

	spec := deriveSpec("Create tool: offline payment provider connector")

	plan, err := BuildCapabilityPlan(
		spec,
		ResearchEvidence{Mode: "offline"},
		e.CoreRoot,
	)
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
		t.Fatalf(
			"expected transaction library to be surfaced as an unverified candidate: %+v",
			plan.ReusableCandidates,
		)
	}

	foundRequirement := false
	for _, req := range plan.Requirements {
		if req.Capability == "transaction idempotency and reconciliation" {
			foundRequirement = true
			if req.Status != "reuse_candidate_unverified" {
				t.Fatalf(
					"candidate metadata must not be reported as verified coverage: %+v",
					req,
				)
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

	planPath := filepath.Join(
		e.CoreRoot,
		"inventions",
		inv.Name,
		"capability_plan.json",
	)
	assertFileExists(t, planPath)

	r := httptest.NewRequest(
		"GET",
		"/v1/genesis/tools/"+inv.Name+"/capability_plan",
		nil,
	)
	r.RemoteAddr = "127.0.0.1:1234"

	w := httptest.NewRecorder()
	(&Server{Engine: e}).ServeHTTP(w, r)

	if w.Code != 200 ||
		!strings.Contains(w.Body.String(), `"capability_plan"`) {
		t.Fatalf(
			"capability plan endpoint failed: %d %s",
			w.Code,
			w.Body.String(),
		)
	}
}

func TestGuardianScreensUntrustedLibraryMetadataInCapabilityPlan(t *testing.T) {
	e := newTestEngine(t)

	libDir := filepath.Join(
		e.CoreRoot,
		"libraries",
		"created",
		"untrusted_catalog_entry",
	)
	if err := os.MkdirAll(libDir, 0o700); err != nil {
		t.Fatal(err)
	}

	meta := libraryMetadata{
		Name:     "untrusted_catalog_entry",
		Category: "software",
		Industry: "general",
		Capabilities: []string{
			"weapon design",
			"validate structured input",
			"record traceable evidence",
		},
		Dependencies: []string{},
	}

	if err := writeJSON(filepath.Join(libDir, "library.json"), meta); err != nil {
		t.Fatal(err)
	}

	_, err := e.Invent(
		context.Background(),
		"Create tool: offline file vault",
	)
	if !errors.Is(err, ErrBlocked) {
		t.Fatalf(
			"unsafe reusable-library metadata should block the proposal: %v",
			err,
		)
	}

	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions"))
	if err != nil {
		t.Fatal(err)
	}

	for _, entry := range entries {
		if entry.IsDir() && !strings.HasPrefix(entry.Name(), ".staging-") {
			t.Fatalf(
				"Guardian allowed invention generation from unsafe capability metadata: %s",
				entry.Name(),
			)
		}
	}

	assertFileExists(
		t,
		filepath.Join(e.CoreRoot, "guardian", "blocked.log"),
	)
}

func TestModelEnrichmentCannotDeleteCoreCapabilityRequirements(t *testing.T) {
	base := deriveSpec("Create tool: offline file vault")

	proposed := ToolSpec{
		Name:         "overridden_name",
		Category:     "software",
		Industry:     "general",
		Capabilities: []string{"invented optional capability"},
		Inputs:       []string{"extra optional input"},
		Outputs:      []string{"extra optional output"},
		Safeguards:   []string{"extra optional safeguard"},
	}

	merged := overlayModelMetadata(base, proposed)

	assertContainsAll := func(
		label string,
		required []string,
		actual []string,
	) {
		t.Helper()

		present := map[string]bool{}
		for _, item := range actual {
			present[strings.ToLower(item)] = true
		}

		for _, item := range required {
			if !present[strings.ToLower(item)] {
				t.Errorf(
					"model enrichment deleted required %s entry %q; actual=%v",
					label,
					item,
					actual,
				)
			}
		}
	}

	assertContainsAll("capability", base.Capabilities, merged.Capabilities)
	assertContainsAll("input", base.Inputs, merged.Inputs)
	assertContainsAll("output", base.Outputs, merged.Outputs)
	assertContainsAll("safeguard", base.Safeguards, merged.Safeguards)

	if !containsAny(
		strings.ToLower(strings.Join(merged.Capabilities, " ")),
		"invented optional capability",
	) {
		t.Fatal("safe model enrichment was not appended to the baseline")
	}

	if merged.Name != base.Name ||
		merged.Category != base.Category ||
		merged.Industry != base.Industry ||
		merged.NeedsHardwareGuide != base.NeedsHardwareGuide {
		t.Fatalf(
			"model enrichment changed deterministic identity or classification: %+v",
			merged,
		)
	}
}
