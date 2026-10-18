package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"usect-zero.local/core-zero/forge"
	"usect-zero.local/core-zero/internal/kernel"
)

func call(t *testing.T, h http.Handler, method, path, body string, headers map[string]string) (int, map[string]any) {
	t.Helper()
	r := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	for k, v := range headers { r.Header.Set(k, v) }
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}
func TestKeyRequestIsPendingUntilAdminApproves(t *testing.T) {
	root := t.TempDir()
	k, e := kernel.New(root)
	if e != nil { t.Fatal(e) }
	h := New(k)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", "test-admin-token-123")
	code, body := call(t, h, http.MethodPost, "/v1/keys/request", `{"name":"Test Developer","email":"dev@example.invalid","reason":"Need an offline scan and RV plan compilation","scopes":["scan:read"]}`, map[string]string{"Content-Type": "application/json"})
	if code != 202 || body["secret_issued"] != false { t.Fatalf("request not pending: code=%d body=%v", code, body) }
	request, ok := body["request"].(map[string]any)
	if !ok || request["status"] != "pending_approval" { t.Fatalf("request state invalid: %v", body) }
	id := request["id"].(string)
	code, _ = call(t, h, http.MethodGet, "/v1/scan", "", nil)
	if code != 401 { t.Fatalf("scan without API key status=%d", code) }
	code, body = call(t, h, http.MethodPost, "/v1/keys/requests/"+id+"/approve", `{"confirmation":"ISSUE_KEY","ttl_days":30}`, map[string]string{"X-Admin-Token": "test-admin-token-123", "Content-Type": "application/json"})
	if code != 200 { t.Fatalf("approval failed: %d %v", code, body) }
	secret, ok := body["api_key"].(string)
	if !ok || secret == "" || body["shown_once"] != true { t.Fatalf("one-time key not returned: %v", body) }
	code, body = call(t, h, http.MethodGet, "/v1/scan", "", map[string]string{"X-API-Key": secret})
	if code != 200 || body["read_only"] != true { t.Fatalf("key scan failed: %d %v", code, body) }
	code, body = call(t, h, http.MethodPost, "/v1/mind/compile", `{"source":"scan\nheal sample.py"}`, map[string]string{"Content-Type": "application/json", "X-API-Key": secret})
	if code != 401 || body["code"] != "api_key_or_scope_required" { t.Fatalf("scope escalation accepted: %d %v", code, body) }
	if ok, _ := forge.New(k.CoreRoot).Validate(secret, "scan:read"); !ok { t.Fatal("key validation failed after API issue") }

	code, issued := call(t, h, http.MethodGet, "/v1/keys/issued?status=active", "", map[string]string{"X-Admin-Token": "test-admin-token-123"})
	if code != 200 { t.Fatalf("issued-key listing failed: %d %v", code, issued) }
	keys, ok := issued["keys"].([]any)
	if !ok || len(keys) != 1 { t.Fatalf("expected one active issued key: %v", issued) }
	keyView, ok := keys[0].(map[string]any)
	if !ok || keyView["id"] == nil || keyView["status"] != "active" { t.Fatalf("issued-key view invalid: %v", keys[0]) }
	if _, leaked := keyView["key_hash"]; leaked { t.Fatalf("key hash leaked in response: %v", keyView) }
	if _, leaked := keyView["api_key"]; leaked { t.Fatalf("raw API key leaked in listing: %v", keyView) }

	keyID, _ := keyView["id"].(string)
	code, revoked := call(t, h, http.MethodPost, "/v1/keys/issued/"+keyID+"/revoke", `{"confirmation":"REVOKE_KEY"}`, map[string]string{"X-Admin-Token": "test-admin-token-123", "Content-Type": "application/json"})
	if code != 200 || revoked["status"] != "revoked" { t.Fatalf("issued-key revocation failed: %d %v", code, revoked) }
	code, active := call(t, h, http.MethodGet, "/v1/keys/issued?status=active", "", map[string]string{"X-Admin-Token": "test-admin-token-123"})
	if code != 200 { t.Fatalf("active-key refresh failed: %d %v", code, active) }
	if remaining, ok := active["keys"].([]any); !ok || len(remaining) != 0 { t.Fatalf("revoked key remains active: %v", active) }
}


func TestDiagnosticsRequiresScopedKeyAndReturnsSafeReport(t *testing.T) {
	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}
	h := New(k)

	code, body := call(t, h, http.MethodGet, "/v1/diagnostics", "", nil)
	if code != 401 || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("diagnostics must require scan:read: code=%d body=%v", code, body)
	}

	code, requestBody := call(t, h, http.MethodPost, "/v1/keys/request", `{"name":"Diagnostics Test","email":"diag@example.invalid","reason":"Need operational diagnostics and baseline drift visibility","scopes":["scan:read"]}`, map[string]string{"Content-Type": "application/json"})
	if code != 202 {
		t.Fatalf("key request failed: %d %v", code, requestBody)
	}
	request, ok := requestBody["request"].(map[string]any)
	if !ok {
		t.Fatalf("request was missing from response: %v", requestBody)
	}
	id, _ := request["id"].(string)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", "test-admin-token-123")
	code, approved := call(t, h, http.MethodPost, "/v1/keys/requests/"+id+"/approve", `{"confirmation":"ISSUE_KEY","ttl_days":30}`, map[string]string{"X-Admin-Token": "test-admin-token-123", "Content-Type": "application/json"})
	if code != 200 {
		t.Fatalf("key approval failed: %d %v", code, approved)
	}
	secret, _ := approved["api_key"].(string)

	code, report := call(t, h, http.MethodGet, "/v1/diagnostics", "", map[string]string{"X-API-Key": secret})
	if code != 200 {
		t.Fatalf("diagnostics failed: %d %v", code, report)
	}
	if report["schema_version"] != "usect-zero.diagnostics.v1" || report["status"] != "ready" {
		t.Fatalf("unexpected diagnostics response: %v", report)
	}
	if _, leaked := report["repository_root"]; leaked {
		t.Fatalf("diagnostics leaked the absolute repository root: %v", report)
	}
	if _, ok := report["storage"].([]any); !ok {
		t.Fatalf("diagnostics storage checks missing: %v", report)
	}
}


func TestAssemblyCatalogIsScopedAndGenerationPinsTemplateVersion(t *testing.T) {
	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}
	h := New(k)

	code, body := call(t, h, http.MethodGet, "/v1/assemble/templates", "", nil)
	if code != 401 || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("assembly catalog should require scan:read: %d %v", code, body)
	}
	code, body = call(t, h, http.MethodGet, "/v1/assemble/boards", "", nil)
	if code != 401 || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("board profile catalog should require scan:read: %d %v", code, body)
	}

	code, requestBody := call(t, h, http.MethodPost, "/v1/keys/request", `{"name":"Assembly Test","email":"assembly@example.invalid","reason":"Need the template catalog and assembly proposal scope","scopes":["scan:read","assemble:propose"]}`, map[string]string{"Content-Type": "application/json"})
	if code != 202 {
		t.Fatalf("key request failed: %d %v", code, requestBody)
	}
	request, ok := requestBody["request"].(map[string]any)
	if !ok {
		t.Fatalf("request missing: %v", requestBody)
	}
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", "test-admin-token-123")
	id, _ := request["id"].(string)
	code, approved := call(t, h, http.MethodPost, "/v1/keys/requests/"+id+"/approve", `{"confirmation":"ISSUE_KEY","ttl_days":30}`, map[string]string{"X-Admin-Token": "test-admin-token-123", "Content-Type": "application/json"})
	if code != 200 {
		t.Fatalf("key approval failed: %d %v", code, approved)
	}
	secret, _ := approved["api_key"].(string)
	headers := map[string]string{"X-API-Key": secret}

	code, catalog := call(t, h, http.MethodGet, "/v1/assemble/templates", "", headers)
	if code != 200 || catalog["schema_version"] != "usect-zero.assembly-catalog.v1" {
		t.Fatalf("catalog request failed: %d %v", code, catalog)
	}
	items, ok := catalog["templates"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("expected one registered template: %v", catalog)
	}
	item, ok := items[0].(map[string]any)
	if !ok || item["version"] != "1.0.0" || item["validation_status"] != "valid_curated_template" || item["board_profile_id"] != "esp32-s3-generic" || item["electrical_review_required"] != true {
		t.Fatalf("catalog metadata invalid: %v", items)
	}
	code, boards := call(t, h, http.MethodGet, "/v1/assemble/boards", "", headers)
	if code != 200 || boards["schema_version"] != "usect-zero.board-profiles.v1" || boards["hardware_verified"] != false {
		t.Fatalf("board profile catalogue should remain explicitly unverified: %d %v", code, boards)
	}
	boardItems, ok := boards["boards"].([]any)
	if !ok || len(boardItems) < 1 {
		t.Fatalf("expected registered reference board profiles: %v", boards)
	}
	if board, ok := boardItems[0].(map[string]any); !ok || board["hardware_verified"] != false {
		t.Fatalf("board profile must not claim hardware verification: %v", boardItems[0])
	}

	code, generated := call(t, h, http.MethodPost, "/v1/assemble", `{"target":"esp32-sensor","template_version":"1.0.0"}`, map[string]string{"Content-Type": "application/json", "X-API-Key": secret})
	if code != 201 || generated["template_version"] != "1.0.0" || generated["status"] != "artifacts_generated_pending_review" {
		t.Fatalf("pinned template generation failed: %d %v", code, generated)
	}
	if generated["human_review_required"] != true || generated["validation"] == nil {
		t.Fatalf("review gate or validation report missing: %v", generated)
	}

	code, unsupported := call(t, h, http.MethodPost, "/v1/assemble", `{"target":"esp32-sensor","template_version":"9.9.9"}`, map[string]string{"Content-Type": "application/json", "X-API-Key": secret})
	if code != 422 || unsupported["status"] != "needs_curated_template" {
		t.Fatalf("unknown template version must be rejected: %d %v", code, unsupported)
	}
}
