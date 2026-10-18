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
}
