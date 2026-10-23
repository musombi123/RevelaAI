package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"usect-zero.local/core-zero/forge"
	"usect-zero.local/core-zero/internal/kernel"
)

const testAdminToken = "test-admin-token-123"

func newTestServer(t *testing.T) (*kernel.Kernel, *Server) {
	t.Helper()

	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatalf("initialize kernel: %v", err)
	}

	return k, New(k)
}

func callWithResponse(
	t *testing.T,
	h http.Handler,
	method, path, body string,
	headers map[string]string,
) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()

	req := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	for key, value := range headers {
		req.Header.Set(key, value)
	}

	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, req)

	var response map[string]any
	if recorder.Body.Len() > 0 {
		if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
			t.Fatalf(
				"response is not valid JSON: status=%d body=%q error=%v",
				recorder.Code,
				recorder.Body.String(),
				err,
			)
		}
	}

	return recorder, response
}

func call(
	t *testing.T,
	h http.Handler,
	method, path, body string,
	headers map[string]string,
) (int, map[string]any) {
	t.Helper()

	recorder, response := callWithResponse(
		t, h, method, path, body, headers,
	)

	return recorder.Code, response
}

func requestAPIKey(
	t *testing.T,
	h http.Handler,
	name string,
	scopes []string,
) string {
	t.Helper()

	payload := map[string]any{
		"name":          name,
		"email":         "test@example.invalid",
		"repository_url": "",
		"reason":        "Automated USECT-ZERO API regression tests",
		"scopes":        scopes,
	}

	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal key request: %v", err)
	}

	code, response := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/request",
		string(raw),
		map[string]string{"Content-Type": "application/json"},
	)
	if code != http.StatusAccepted {
		t.Fatalf("key request failed: status=%d body=%v", code, response)
	}

	request, ok := response["request"].(map[string]any)
	if !ok {
		t.Fatalf("key request response missing request object: %v", response)
	}

	id, ok := request["id"].(string)
	if !ok || id == "" {
		t.Fatalf("key request response missing ID: %v", request)
	}

	approvalBody := `{"confirmation":"ISSUE_KEY","ttl_days":30}`
	code, approved := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/requests/"+id+"/approve",
		approvalBody,
		map[string]string{
			"X-Admin-Token": testAdminToken,
			"Content-Type":  "application/json",
		},
	)
	if code != http.StatusOK {
		t.Fatalf("key approval failed: status=%d body=%v", code, approved)
	}

	secret, ok := approved["api_key"].(string)
	if !ok || secret == "" {
		t.Fatalf("approval did not return an API key: %v", approved)
	}

	return secret
}

func TestHealthIsPublicAndDoesNotExposeFilesystemPaths(t *testing.T) {
	root := t.TempDir()

	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}

	h := New(k)
	recorder, body := callWithResponse(
		t, h, http.MethodGet, "/v1/health", "", nil,
	)

	if recorder.Code != http.StatusOK {
		t.Fatalf("health status=%d body=%v", recorder.Code, body)
	}

	if body["status"] != "ok" || body["service"] != "USECT-ZERO" {
		t.Fatalf("unexpected health response: %v", body)
	}

	if body["execution_policy"] != "human-gated" {
		t.Fatalf("health response weakened execution policy: %v", body)
	}

	if body["hardware_actuation"] != false {
		t.Fatalf("health response must not claim hardware actuation: %v", body)
	}

	if _, exists := body["repository_root"]; exists {
		t.Fatalf("health endpoint exposed repository_root: %v", body)
	}

	if strings.Contains(recorder.Body.String(), root) {
		t.Fatalf("health endpoint exposed an absolute filesystem path: %s", recorder.Body.String())
	}

	if recorder.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("expected no-store response, got %q", recorder.Header().Get("Cache-Control"))
	}

	if recorder.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("missing nosniff security header")
	}
}

func TestNilKernelFailsClosed(t *testing.T) {
	h := New(nil)

	code, body := call(t, h, http.MethodGet, "/v1/health", "", nil)
	if code != http.StatusServiceUnavailable || body["code"] != "kernel_unavailable" {
		t.Fatalf("nil kernel should fail closed: status=%d body=%v", code, body)
	}
}

func TestUninitializedKeyManagerFailsClosed(t *testing.T) {
	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}

	h := &Server{K: k}

	code, body := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/request",
		`{"name":"Test","email":"test@example.invalid","reason":"Testing","scopes":["scan:read"]}`,
		map[string]string{"Content-Type": "application/json"},
	)

	if code != http.StatusServiceUnavailable || body["code"] != "key_manager_unavailable" {
		t.Fatalf("uninitialized key manager should fail closed: status=%d body=%v", code, body)
	}
}

func TestCORSRejectsUnapprovedOrigins(t *testing.T) {
	t.Setenv("USECT_ZERO_CORS_ORIGINS", "https://revelacode.co.ke")

	_, h := newTestServer(t)

	recorder, body := callWithResponse(
		t,
		h,
		http.MethodGet,
		"/v1/health",
		"",
		map[string]string{"Origin": "https://attacker.example"},
	)

	if recorder.Code != http.StatusForbidden || body["code"] != "cors_origin_denied" {
		t.Fatalf("unapproved origin was not denied: status=%d body=%v", recorder.Code, body)
	}

	if recorder.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatal("unapproved origin received an Access-Control-Allow-Origin header")
	}
}

func TestCORSAllowsConfiguredOrigin(t *testing.T) {
	const allowedOrigin = "https://revelacode.co.ke"

	t.Setenv("USECT_ZERO_CORS_ORIGINS", allowedOrigin)

	_, h := newTestServer(t)

	recorder, body := callWithResponse(
		t,
		h,
		http.MethodGet,
		"/v1/health",
		"",
		map[string]string{"Origin": allowedOrigin},
	)

	if recorder.Code != http.StatusOK || body["status"] != "ok" {
		t.Fatalf("configured origin should be permitted: status=%d body=%v", recorder.Code, body)
	}

	if got := recorder.Header().Get("Access-Control-Allow-Origin"); got != allowedOrigin {
		t.Fatalf("unexpected CORS origin: got=%q want=%q", got, allowedOrigin)
	}

	if !strings.Contains(recorder.Header().Get("Vary"), "Origin") {
		t.Fatal("CORS response must vary by Origin")
	}
}

func TestCORSPreflightRequiresApprovedOrigin(t *testing.T) {
	const allowedOrigin = "https://revelacode.co.ke"

	t.Setenv("USECT_ZERO_CORS_ORIGINS", allowedOrigin)

	_, h := newTestServer(t)

	recorder, _ := callWithResponse(
		t,
		h,
		http.MethodOptions,
		"/v1/health",
		"",
		map[string]string{
			"Origin":                        allowedOrigin,
			"Access-Control-Request-Method":  "POST",
			"Access-Control-Request-Headers": "content-type,x-api-key",
		},
	)

	if recorder.Code != http.StatusNoContent {
		t.Fatalf("approved preflight status=%d body=%s", recorder.Code, recorder.Body.String())
	}

	if recorder.Header().Get("Access-Control-Allow-Origin") != allowedOrigin {
		t.Fatal("approved preflight lacks Access-Control-Allow-Origin")
	}

	if !strings.Contains(
		recorder.Header().Get("Access-Control-Allow-Methods"),
		"POST",
	) {
		t.Fatal("preflight does not allow POST")
	}

	if !strings.Contains(
		strings.ToLower(recorder.Header().Get("Access-Control-Allow-Headers")),
		"x-api-key",
	) {
		t.Fatal("preflight does not allow X-API-Key")
	}
}

func TestCORSRejectsWildcardConfiguration(t *testing.T) {
	t.Setenv("USECT_ZERO_CORS_ORIGINS", "*")

	_, h := newTestServer(t)

	recorder, body := callWithResponse(
		t,
		h,
		http.MethodGet,
		"/v1/health",
		"",
		map[string]string{"Origin": "https://revelacode.co.ke"},
	)

	if recorder.Code != http.StatusForbidden || body["code"] != "cors_origin_denied" {
		t.Fatalf("wildcard configuration must not authorize arbitrary origins: status=%d body=%v", recorder.Code, body)
	}
}

func TestAdminAuthenticationFailsClosedAndSupportsBearerScheme(t *testing.T) {
	_, h := newTestServer(t)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", "")

	code, body := call(
		t,
		h,
		http.MethodGet,
		"/v1/keys/issued",
		"",
		map[string]string{"X-Admin-Token": testAdminToken},
	)

	if code != http.StatusUnauthorized || body["code"] != "admin_approval_required" {
		t.Fatalf("unconfigured admin secret must fail closed: status=%d body=%v", code, body)
	}

	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	code, body = call(
		t,
		h,
		http.MethodGet,
		"/v1/keys/issued",
		"",
		map[string]string{"Authorization": "bEaReR " + testAdminToken},
	)

	if code != http.StatusOK {
		t.Fatalf("case-insensitive Bearer scheme was rejected: status=%d body=%v", code, body)
	}
}

func TestMalformedAndAmbiguousJSONRequestsAreRejected(t *testing.T) {
	_, h := newTestServer(t)

	cases := []struct {
		name string
		body string
	}{
		{
			name: "invalid JSON",
			body: `{"name":`,
		},
		{
			name: "unknown field",
			body: `{"name":"Test","unknown_admin":true}`,
		},
		{
			name: "multiple JSON values",
			body: `{"name":"Test"} {"second":"object"}`,
		},
		{
			name: "trailing garbage",
			body: `{"name":"Test"} trailing`,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			code, body := call(
				t,
				h,
				http.MethodPost,
				"/v1/keys/request",
				testCase.body,
				map[string]string{"Content-Type": "application/json"},
			)

			if code != http.StatusBadRequest || body["code"] != "invalid_json" {
				t.Fatalf("ambiguous input accepted: status=%d body=%v", code, body)
			}
		})
	}
}

func TestRequestBodyLimitIsEnforced(t *testing.T) {
	_, h := newTestServer(t)

	// This is a large string value in a syntactically structured JSON request.
	body := `{"name":"` + strings.Repeat("x", (1<<20)+32) + `"}`

	code, response := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/request",
		body,
		map[string]string{"Content-Type": "application/json"},
	)

	if code != http.StatusBadRequest || response["code"] != "invalid_json" {
		t.Fatalf("oversized request body was not rejected: status=%d body=%v", code, response)
	}
}

func TestKeyRequestIsPendingUntilAdminApproves(t *testing.T) {
	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}

	h := New(k)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	code, body := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/request",
		`{"name":"Test Developer","email":"dev@example.invalid","reason":"Need an offline scan and RV plan compilation","scopes":["scan:read"]}`,
		map[string]string{"Content-Type": "application/json"},
	)

	if code != http.StatusAccepted || body["secret_issued"] != false {
		t.Fatalf("request not pending: status=%d body=%v", code, body)
	}

	request, ok := body["request"].(map[string]any)
	if !ok || request["status"] != "pending_approval" {
		t.Fatalf("request state invalid: %v", body)
	}

	id, ok := request["id"].(string)
	if !ok || id == "" {
		t.Fatalf("request ID missing: %v", request)
	}

	code, _ = call(t, h, http.MethodGet, "/v1/scan", "", nil)
	if code != http.StatusUnauthorized {
		t.Fatalf("scan without API key status=%d", code)
	}

	code, body = call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/requests/"+id+"/approve",
		`{"confirmation":"ISSUE_KEY","ttl_days":30}`,
		map[string]string{
			"X-Admin-Token": testAdminToken,
			"Content-Type":  "application/json",
		},
	)

	if code != http.StatusOK {
		t.Fatalf("approval failed: %d %v", code, body)
	}

	secret, ok := body["api_key"].(string)
	if !ok || secret == "" || body["shown_once"] != true {
		t.Fatalf("one-time key not returned: %v", body)
	}

	code, body = call(
		t,
		h,
		http.MethodGet,
		"/v1/scan",
		"",
		map[string]string{"X-API-Key": secret},
	)

	if code != http.StatusOK || body["read_only"] != true {
		t.Fatalf("key scan failed: %d %v", code, body)
	}

	code, body = call(
		t,
		h,
		http.MethodPost,
		"/v1/mind/compile",
		`{"source":"scan\nheal sample.py"}`,
		map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    secret,
		},
	)

	if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("scope escalation accepted: %d %v", code, body)
	}

	if valid, _ := forge.New(k.CoreRoot).Validate(secret, "scan:read"); !valid {
		t.Fatal("key validation failed after API issue")
	}

	code, issued := call(
		t,
		h,
		http.MethodGet,
		"/v1/keys/issued?status=active",
		"",
		map[string]string{"X-Admin-Token": testAdminToken},
	)

	if code != http.StatusOK {
		t.Fatalf("issued-key listing failed: %d %v", code, issued)
	}

	keys, ok := issued["keys"].([]any)
	if !ok || len(keys) != 1 {
		t.Fatalf("expected one active issued key: %v", issued)
	}

	keyView, ok := keys[0].(map[string]any)
	if !ok || keyView["id"] == nil || keyView["status"] != "active" {
		t.Fatalf("issued-key view invalid: %v", keys[0])
	}

	if _, leaked := keyView["key_hash"]; leaked {
		t.Fatalf("key hash leaked in response: %v", keyView)
	}

	if _, leaked := keyView["api_key"]; leaked {
		t.Fatalf("raw API key leaked in listing: %v", keyView)
	}

	keyID, ok := keyView["id"].(string)
	if !ok || keyID == "" {
		t.Fatalf("issued key ID missing: %v", keyView)
	}

	code, revoked := call(
		t,
		h,
		http.MethodPost,
		"/v1/keys/issued/"+keyID+"/revoke",
		`{"confirmation":"REVOKE_KEY"}`,
		map[string]string{
			"X-Admin-Token": testAdminToken,
			"Content-Type":  "application/json",
		},
	)

	if code != http.StatusOK || revoked["status"] != "revoked" {
		t.Fatalf("issued-key revocation failed: %d %v", code, revoked)
	}

	code, active := call(
		t,
		h,
		http.MethodGet,
		"/v1/keys/issued?status=active",
		"",
		map[string]string{"X-Admin-Token": testAdminToken},
	)

	if code != http.StatusOK {
		t.Fatalf("active-key refresh failed: %d %v", code, active)
	}

	if remaining, ok := active["keys"].([]any); !ok || len(remaining) != 0 {
		t.Fatalf("revoked key remains active: %v", active)
	}

	code, body = call(
		t,
		h,
		http.MethodGet,
		"/v1/scan",
		"",
		map[string]string{"X-API-Key": secret},
	)
	if code != http.StatusUnauthorized {
		t.Fatalf("revoked API key still authorized: status=%d body=%v", code, body)
	}
}

func TestInvalidResourceIDsDoNotReachKeyApproval(t *testing.T) {
	_, h := newTestServer(t)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	cases := []string{
		"/v1/keys/requests/a%2Fb/approve",
		"/v1/keys/requests/%20/approve",
		"/v1/keys/requests//approve",
	}

	for _, path := range cases {
		t.Run(path, func(t *testing.T) {
			code, body := call(
				t,
				h,
				http.MethodPost,
				path,
				`{"confirmation":"ISSUE_KEY"}`,
				map[string]string{
					"X-Admin-Token": testAdminToken,
					"Content-Type":  "application/json",
				},
			)

			if code != http.StatusBadRequest || body["code"] != "invalid_resource_id" {
				t.Fatalf("invalid resource ID was not rejected: status=%d body=%v", code, body)
			}
		})
	}
}

func TestDiagnosticsRequiresScopedKeyAndReturnsSafeReport(t *testing.T) {
	_, h := newTestServer(t)

	code, body := call(t, h, http.MethodGet, "/v1/diagnostics", "", nil)
	if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("diagnostics must require scan:read: status=%d body=%v", code, body)
	}

	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)
	secret := requestAPIKey(t, h, "Diagnostics Test", []string{"scan:read"})

	code, report := call(
		t,
		h,
		http.MethodGet,
		"/v1/diagnostics",
		"",
		map[string]string{"X-API-Key": secret},
	)

	if code != http.StatusOK {
		t.Fatalf("diagnostics failed: %d %v", code, report)
	}

	if report["schema_version"] != "usect-zero.diagnostics.v1" ||
		report["status"] != "ready" {
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
	dataRoot := filepath.Join(t.TempDir(), "persistent", "usect-zero")
	t.Setenv("USECT_ZERO_DATA_DIR", dataRoot)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}
	h := New(k)

	code, body := call(t, h, http.MethodGet, "/v1/assemble/templates", "", nil)
	if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("assembly catalog should require scan:read: %d %v", code, body)
	}

	code, body = call(t, h, http.MethodGet, "/v1/assemble/boards", "", nil)
	if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("board profile catalog should require scan:read: %d %v", code, body)
	}

	secret := requestAPIKey(
		t,
		h,
		"Assembly Test",
		[]string{"scan:read", "assemble:propose"},
	)
	headers := map[string]string{"X-API-Key": secret}

	code, catalog := call(t, h, http.MethodGet, "/v1/assemble/templates", "", headers)
	if code != http.StatusOK || catalog["schema_version"] != "usect-zero.assembly-catalog.v1" {
		t.Fatalf("catalog request failed: %d %v", code, catalog)
	}

	items, ok := catalog["templates"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("expected one registered template: %v", catalog)
	}

	item, ok := items[0].(map[string]any)
	if !ok ||
		item["version"] != "1.0.0" ||
		item["validation_status"] != "valid_curated_template" ||
		item["board_profile_id"] != "esp32-s3-generic" ||
		item["electrical_review_required"] != true {
		t.Fatalf("catalog metadata invalid: %v", items)
	}

	code, boards := call(t, h, http.MethodGet, "/v1/assemble/boards", "", headers)
	if code != http.StatusOK ||
		boards["schema_version"] != "usect-zero.board-profiles.v1" ||
		boards["hardware_verified"] != false {
		t.Fatalf("board profiles should remain explicitly unverified: %d %v", code, boards)
	}

	boardItems, ok := boards["boards"].([]any)
	if !ok || len(boardItems) < 1 {
		t.Fatalf("expected registered reference board profiles: %v", boards)
	}

	board, ok := boardItems[0].(map[string]any)
	if !ok || board["hardware_verified"] != false {
		t.Fatalf("board profile must not claim hardware verification: %v", boardItems[0])
	}

	code, generated := call(
		t,
		h,
		http.MethodPost,
		"/v1/assemble",
		`{"target":"esp32-sensor","template_version":"1.0.0"}`,
		map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    secret,
		},
	)

	if code != http.StatusCreated ||
		generated["template_version"] != "1.0.0" ||
		generated["status"] != "artifacts_generated_pending_review" {
		t.Fatalf("pinned template generation failed: %d %v", code, generated)
	}

	if generated["human_review_required"] != true || generated["validation"] == nil {
		t.Fatalf("review gate or validation report missing: %v", generated)
	}

	artifacts, ok := generated["artifacts"].([]any)
	if !ok || len(artifacts) != 6 {
		t.Fatalf("expected six generated artifact references: %v", generated["artifacts"])
	}

	firstArtifact, ok := artifacts[0].(string)
	if !ok ||
		!strings.HasPrefix(firstArtifact, "usect-zero-data/evidence/assemble/") ||
		strings.Contains(firstArtifact, "..") ||
		filepath.IsAbs(firstArtifact) {
		t.Fatalf("external persistent storage must return a safe logical path: %v", artifacts[0])
	}

	code, unsupported := call(
		t,
		h,
		http.MethodPost,
		"/v1/assemble",
		`{"target":"esp32-sensor","template_version":"9.9.9"}`,
		map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    secret,
		},
	)

	if code != http.StatusUnprocessableEntity ||
		unsupported["status"] != "needs_curated_template" {
		t.Fatalf("unknown template version must be rejected: %d %v", code, unsupported)
	}
}

func TestAssemblyDoesNotAllowScopeEscalation(t *testing.T) {
	_, h := newTestServer(t)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	secret := requestAPIKey(t, h, "Scan-Only Test", []string{"scan:read"})

	code, body := call(
		t,
		h,
		http.MethodPost,
		"/v1/assemble",
		`{"target":"esp32-sensor","template_version":"1.0.0"}`,
		map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    secret,
		},
	)

	if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
		t.Fatalf("scan-only key gained assembly permission: status=%d body=%v", code, body)
	}
}

func TestAssemblyAndCompilationRequireExplicitScopes(t *testing.T) {
	_, h := newTestServer(t)
	t.Setenv("USECT_ZERO_ADMIN_TOKEN", testAdminToken)

	secret := requestAPIKey(t, h, "Scan-Only Scope Test", []string{"scan:read"})

	cases := []struct {
		name   string
		path   string
		body   string
		method string
	}{
		{
			name:   "mind compilation",
			path:   "/v1/mind/compile",
			body:   `{"source":"scan sample.py"}`,
			method: http.MethodPost,
		},
		{
			name:   "bridge planning",
			path:   "/v1/bridge/plan",
			body:   `{"target":"supported-target"}`,
			method: http.MethodPost,
		},
		{
			name:   "radar comparison",
			path:   "/v1/radar/compare",
			body:   `{"current":{},"candidate":{}}`,
			method: http.MethodPost,
		},
		{
			name:   "assembly proposal",
			path:   "/v1/assemble",
			body:   `{"target":"esp32-sensor","template_version":"1.0.0"}`,
			method: http.MethodPost,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			code, body := call(
				t,
				h,
				testCase.method,
				testCase.path,
				testCase.body,
				map[string]string{
					"Content-Type": "application/json",
					"X-API-Key":    secret,
				},
			)

			if code != http.StatusUnauthorized || body["code"] != "api_key_or_scope_required" {
				t.Fatalf("scope escalation accepted: status=%d body=%v", code, body)
			}
		})
	}
}


func TestGeneratedBrainTokenIsScopedAndNotAdmin(t *testing.T) {
	t.Setenv("USECT_ZERO_BRAIN_TOKEN", "test-generated-brain-token-long-random-value")
	_, h := newTestServer(t)

	code, body := call(
		t,
		h,
		http.MethodGet,
		"/v1/scan",
		"",
		map[string]string{"X-API-Key": "test-generated-brain-token-long-random-value"},
	)
	if code != http.StatusOK || body["read_only"] != true {
		t.Fatalf("generated brain token should allow read scope: status=%d body=%v", code, body)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/scan", nil)
	req.Header.Set("X-API-Key", "test-generated-brain-token-long-random-value")
	recorder := httptest.NewRecorder()
	_, ok := h.requireScope(recorder, req, "admin:write")
	if ok || recorder.Code != http.StatusForbidden {
		t.Fatalf("generated brain token must reject unapproved scopes: status=%d", recorder.Code)
	}
	var denied map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &denied); err != nil {
		t.Fatalf("decode scope rejection: %v", err)
	}
	if denied["code"] != "internal_brain_scope_denied" {
		t.Fatalf("unexpected scope rejection: %v", denied)
	}

	code, body = call(
		t,
		h,
		http.MethodGet,
		"/v1/keys/issued",
		"",
		map[string]string{"X-API-Key": "test-generated-brain-token-long-random-value"},
	)
	if code != http.StatusUnauthorized || body["code"] != "admin_approval_required" {
		t.Fatalf("brain token must not grant admin access: status=%d body=%v", code, body)
	}
}
