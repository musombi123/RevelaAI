package api

import (
	"net/http"
	"path/filepath"
	"os"
	"testing"
)

func TestAuditVerifyEndpointRequiresAdminAndDetectsTampering(t *testing.T) {
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)
	k, h := newTestServer(t)
	if err := k.Audit("before_test", "test", "subject", "ok", nil); err != nil {
		t.Fatal(err)
	}

	code, body := call(t, h, http.MethodGet, "/v1/audit/verify", "", nil)
	if code != http.StatusUnauthorized || body["code"] != "admin_approval_required" {
		t.Fatalf("verification endpoint should require admin auth: status=%d body=%v", code, body)
	}

	headers := map[string]string{"X-Admin-Token": testAdminToken}
	code, body = call(t, h, http.MethodGet, "/v1/audit/verify", "", headers)
	if code != http.StatusOK || body["verified"] != true {
		t.Fatalf("valid audit chain should verify: status=%d body=%v", code, body)
	}

	path := filepath.Join(k.CoreRoot, "audit_log", "events.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(data) == 0 {
		t.Fatal("expected audit record")
	}
	data[0] ^= 1
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	code, body = call(t, h, http.MethodGet, "/v1/audit/verify", "", headers)
	if code != http.StatusConflict || body["chain_valid"] != false {
		t.Fatalf("tampered audit chain should return conflict: status=%d body=%v", code, body)
	}
}
