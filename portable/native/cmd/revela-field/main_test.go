package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/musombi123/revela-field-engine/internal/contract"
)

func validFinding() contract.Finding {
	return contract.Finding{
		SchemaVersion: contract.SchemaVersion,
		ID: "field-0123456789abcdef",
		Source: "revela-field-engine",
		Target: "isolated synthetic fixture",
		Category: "identity_monitoring",
		Severity: "informational",
		Title: "Synthetic authentication-failure burst",
		Summary: "A harmless synthetic test event.",
		Evidence: []contract.Evidence{{Kind: "synthetic_event", Ref: "scenario://auth-failure-burst"}},
		Recommendation: "Review detection thresholds.",
		Scope: "lab",
		Simulated: true,
	}
}

func TestValidateSyncOrigin(t *testing.T) {
	accepted := []string{
		"https://revelaai.example",
		"https://revelaai.example/",
		"http://127.0.0.1:8789",
		"http://localhost:8789",
		"http://[::1]:8789",
	}
	for _, value := range accepted {
		if _, err := validateSyncOrigin(value); err != nil {
			t.Errorf("%q should be accepted: %v", value, err)
		}
	}
	rejected := []string{
		"http://revelaai.example",
		"ftp://revelaai.example",
		"https://user:pass@revelaai.example",
		"https://revelaai.example/api/meta-engineer",
		"https://revelaai.example?token=secret",
	}
	for _, value := range rejected {
		if _, err := validateSyncOrigin(value); err == nil {
			t.Errorf("%q should be rejected", value)
		}
	}
}

func TestRunSyncPostsOnlyValidatedFindingWithAdminBearer(t *testing.T) {
	finding := validFinding()
	data, err := json.Marshal(finding)
	if err != nil { t.Fatal(err) }
	path := filepath.Join(t.TempDir(), "finding.json")
	if err := os.WriteFile(path, data, 0600); err != nil { t.Fatal(err) }

	received := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		received = true
		if r.Method != http.MethodPost { t.Errorf("method = %s", r.Method) }
		if r.URL.Path != "/api/meta-engineer/fieldkit/findings" { t.Errorf("path = %s", r.URL.Path) }
		if r.Header.Get("Authorization") != "Bearer test-admin-session" { t.Errorf("missing admin bearer") }
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") { t.Errorf("wrong content type") }
		var got contract.Finding
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil { t.Errorf("decode body: %v", err) }
		if got.ID != finding.ID || !got.Simulated || got.Scope != "lab" { t.Errorf("unexpected finding: %+v", got) }
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"status":"awaiting_review","repair_executed":false}`))
	}))
	defer server.Close()
	t.Setenv("REVELA_ADMIN_BEARER", "test-admin-session")

	if err := runSync([]string{"--finding", path, "--url", server.URL}); err != nil {
		t.Fatalf("runSync failed: %v", err)
	}
	if !received { t.Fatal("Meta Engineer endpoint was not called") }
}

func TestRunSyncRejectsInvalidFieldScopeBeforeNetwork(t *testing.T) {
	finding := validFinding()
	finding.Scope = "local" // synthetic findings must remain lab-scoped
	data, _ := json.Marshal(finding)
	path := filepath.Join(t.TempDir(), "finding.json")
	if err := os.WriteFile(path, data, 0600); err != nil { t.Fatal(err) }
	t.Setenv("REVELA_ADMIN_BEARER", "test-admin-session")
	if err := runSync([]string{"--finding", path, "--url", "http://127.0.0.1:8789"}); err == nil {
		t.Fatal("invalid scope must be rejected")
	}
}

func TestSimulateCanExportFindingJSON(t *testing.T) {
	path := filepath.Join(t.TempDir(), "finding.json")
	if err := runSimulate([]string{"--scenario", "vpn-observation", "--finding-out", path}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil { t.Fatal(err) }
	var finding contract.Finding
	if err := json.Unmarshal(data, &finding); err != nil { t.Fatal(err) }
	if !finding.Simulated || finding.Scope != "lab" || finding.Source != "revela-field-engine" {
		t.Fatalf("unexpected exported finding: %+v", finding)
	}
}
