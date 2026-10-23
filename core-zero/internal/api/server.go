package api

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"usect-zero.local/core-zero/assemble"
	"usect-zero.local/core-zero/bridge"
	"usect-zero.local/core-zero/diagnostics"
	"usect-zero.local/core-zero/forge"
	"usect-zero.local/core-zero/heal"
	globalhealer "usect-zero.local/core-zero/healer"
	"usect-zero.local/core-zero/internal/kernel"
	"usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

const (
	maxJSONBodyBytes = 1 << 20 // 1 MiB

	adminTokenEnv = "USECT_ZERO_ADMIN_TOKEN"
	corsOriginsEnv = "USECT_ZERO_CORS_ORIGINS"
)

type apiError struct {
	Status  string `json:"status"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

type rateWindow struct {
	started time.Time
	count   int
}

const (
	scopeRateWindow = time.Minute
	scopeRateLimit  = 60
	maxRateBuckets  = 10000
)

type Server struct {
	K       *kernel.Kernel
	Keys    *forge.KeyManager
	Devices *bridge.DeviceRegistry

	rateMu sync.Mutex
	rates  map[string]rateWindow
}

func (s *Server) allowScopeRate(keyID, scope string) bool {
	if s == nil || keyID == "" || scope == "" {
		return false
	}
	now := time.Now()
	bucket := keyID + ":" + scope

	s.rateMu.Lock()
	defer s.rateMu.Unlock()
	if s.rates == nil {
		s.rates = make(map[string]rateWindow)
	}
	window, exists := s.rates[bucket]
	if !exists || now.Sub(window.started) >= scopeRateWindow || now.Before(window.started) {
		if len(s.rates) >= maxRateBuckets {
			for name, candidate := range s.rates {
				if now.Sub(candidate.started) >= scopeRateWindow || now.Before(candidate.started) {
					delete(s.rates, name)
				}
			}
			if len(s.rates) >= maxRateBuckets {
				return false
			}
		}
		s.rates[bucket] = rateWindow{started: now, count: 1}
		return true
	}
	if window.count >= scopeRateLimit {
		return false
	}
	window.count++
	s.rates[bucket] = window
	return true
}

// New constructs the HTTP API server.
//
// A nil kernel is tolerated here so that construction itself does not panic.
// ServeHTTP returns a controlled service-unavailable response if dependencies
// have not been configured.
func New(k *kernel.Kernel) *Server {
	s := &Server{K: k}
	if k != nil {
		s.Keys = forge.New(k.CoreRoot)
		s.Devices = bridge.NewDeviceRegistry(k.CoreRoot)
	}
	return s
}

func replyJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")

	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func setSecurityHeaders(w http.ResponseWriter) {
	h := w.Header()
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Referrer-Policy", "no-referrer")
	h.Set("X-Frame-Options", "DENY")
	h.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
}

// decodeJSON reads exactly one JSON value and rejects unknown struct fields
// and request bodies larger than maxJSONBodyBytes.
//
// Callers should return immediately when this function returns an error.
func decodeJSON(w http.ResponseWriter, r *http.Request, v any) error {
	if r == nil || r.Body == nil {
		return errors.New("request body is required")
	}

	defer r.Body.Close()

	body := http.MaxBytesReader(w, r.Body, maxJSONBodyBytes)
	d := json.NewDecoder(body)
	d.DisallowUnknownFields()

	if err := d.Decode(v); err != nil {
		return err
	}

	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		if err == nil {
			return errors.New("request must contain exactly one JSON value")
		}
		return err
	}

	return nil
}

// validCORSOrigin accepts a bare HTTP(S) origin only. Paths, credentials,
// query strings, fragments, wildcards, and malformed URLs are rejected.
func validCORSOrigin(candidate string) bool {
	if candidate == "" || strings.ContainsAny(candidate, " \t\r\n") {
		return false
	}

	u, err := url.Parse(candidate)
	if err != nil {
		return false
	}

	if !strings.EqualFold(u.Scheme, "http") &&
		!strings.EqualFold(u.Scheme, "https") {
		return false
	}

	return u.Host != "" &&
		u.User == nil &&
		u.Opaque == "" &&
		u.Path == "" &&
		u.RawPath == "" &&
		u.RawQuery == "" &&
		!u.ForceQuery &&
		u.Fragment == ""
}

// configuredCORSOrigins loads exact permitted origins from
// USECT_ZERO_CORS_ORIGINS, a comma-separated list such as:
//
// https://revelacode.co.ke,https://revelaai.onrender.com
//
// No wildcard is accepted. CORS is not an authentication mechanism; protected
// endpoints must still validate their admin token or API key.
func configuredCORSOrigins() map[string]struct{} {
	origins := make(map[string]struct{})

	for _, entry := range strings.Split(os.Getenv(corsOriginsEnv), ",") {
		origin := strings.TrimSpace(entry)
		if !validCORSOrigin(origin) {
			continue
		}
		origins[origin] = struct{}{}
	}

	return origins
}

// applyCORS applies an explicit browser-origin allowlist.
//
// Requests without an Origin header remain available to server-to-server
// callers. Requests that include an unapproved Origin are rejected. Preflight
// requests succeed only for approved origins.
func applyCORS(w http.ResponseWriter, r *http.Request) bool {
	origin := strings.TrimSpace(r.Header.Get("Origin"))

	if origin != "" {
		w.Header().Add("Vary", "Origin")

		_, allowed := configuredCORSOrigins()[origin]
		if !allowed {
			replyJSON(w, http.StatusForbidden, apiError{
				Status:  "error",
				Code:    "cors_origin_denied",
				Message: "This request origin is not permitted by the USECT-ZERO CORS policy.",
			})
			return false
		}

		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set(
			"Access-Control-Allow-Headers",
			"Authorization, Content-Type, X-Admin-Token, X-API-Key, X-Device-Token",
		)
		w.Header().Set(
			"Access-Control-Allow-Methods",
			"GET, POST, OPTIONS",
		)
		w.Header().Set("Access-Control-Max-Age", "600")
	}

	if r.Method == http.MethodOptions {
		if origin == "" {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "cors_origin_required",
				Message: "An Origin header is required for a CORS preflight request.",
			})
			return false
		}

		w.WriteHeader(http.StatusNoContent)
		return false
	}

	return true
}

// bearerCredential extracts a single Bearer credential. The authentication
// scheme name is case-insensitive, as required by HTTP authentication rules.
func bearerCredential(header string) string {
	fields := strings.Fields(header)
	if len(fields) != 2 || !strings.EqualFold(fields[0], "Bearer") {
		return ""
	}

	return strings.TrimSpace(fields[1])
}

// constantTimeTokenEqual compares fixed-length SHA-256 digests rather than
// returning immediately when candidate token lengths differ.
func constantTimeTokenEqual(given, configured string) bool {
	if given == "" || configured == "" {
		return false
	}

	givenDigest := sha256.Sum256([]byte(given))
	configuredDigest := sha256.Sum256([]byte(configured))

	return subtle.ConstantTimeCompare(givenDigest[:], configuredDigest[:]) == 1
}

func (s *Server) adminOK(r *http.Request) bool {
	if s == nil || r == nil {
		return false
	}

	configured := strings.TrimSpace(os.Getenv(adminTokenEnv))
	if configured == "" {
		// Fail closed when no admin token is configured.
		return false
	}

	given := strings.TrimSpace(r.Header.Get("X-Admin-Token"))
	if given == "" {
		given = bearerCredential(r.Header.Get("Authorization"))
	}

	return constantTimeTokenEqual(given, configured)
}

func (s *Server) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	if !s.adminOK(r) {
		replyJSON(w, http.StatusUnauthorized, apiError{
			Status:  "error",
			Code:    "admin_approval_required",
			Message: "A valid USECT-ZERO admin token is required; no action was executed.",
		})
		return false
	}

	return true
}

func internalBrainScopeAllowed(scope string) bool {
	switch scope {
	case "scan:read", "heal:propose", "assemble:propose", "radar:compare", "bridge:propose", "mind:compile":
		return true
	default:
		return false
	}
}

func (s *Server) requireScope(
	w http.ResponseWriter,
	r *http.Request,
	scope string,
) (string, bool) {
	if s == nil || s.Keys == nil {
		replyJSON(w, http.StatusServiceUnavailable, apiError{
			Status:  "error",
			Code:    "key_manager_unavailable",
			Message: "API-key validation is unavailable; the requested operation was not executed.",
		})
		return "", false
	}

	key := strings.TrimSpace(r.Header.Get("X-API-Key"))
	if key == "" {
		replyJSON(w, http.StatusUnauthorized, apiError{
			Status:  "error",
			Code:    "api_key_or_scope_required",
			Message: "Supply an active X-API-Key with scope " + scope + ". Key requests remain pending until human approval.",
		})
		return "", false
	}

	// The generated service-to-service brain token is distinct from human-issued
	// developer keys and admin credentials. It can invoke only bounded read/proposal
	// scopes; administrator actions use a separate credential and route.
	brainToken := strings.TrimSpace(os.Getenv("USECT_ZERO_BRAIN_TOKEN"))
	if constantTimeTokenEqual(key, brainToken) {
		if !internalBrainScopeAllowed(scope) {
			replyJSON(w, http.StatusForbidden, apiError{
				Status:  "error",
				Code:    "internal_brain_scope_denied",
				Message: "The RevelaAI service identity is limited to approved read/proposal scopes.",
			})
			return "", false
		}
		const actor = "revelaai-brain"
		if !s.allowScopeRate(actor, scope) {
			w.Header().Set("Retry-After", "60")
			replyJSON(w, http.StatusTooManyRequests, apiError{
				Status:  "error",
				Code:    "scope_rate_limit_exceeded",
				Message: "The internal brain identity has exceeded the request limit for this scope.",
			})
			return "", false
		}
		return actor, true
	}

	ok, id := s.Keys.Validate(key, scope)
	if !ok {
		replyJSON(w, http.StatusUnauthorized, apiError{
			Status:  "error",
			Code:    "api_key_or_scope_required",
			Message: "Supply an active X-API-Key with scope " + scope + ". Key requests remain pending until human approval.",
		})
		return "", false
	}
	if !s.allowScopeRate(id, scope) {
		w.Header().Set("Retry-After", "60")
		replyJSON(w, http.StatusTooManyRequests, apiError{
			Status: "error",
			Code: "scope_rate_limit_exceeded",
			Message: "The approved key has exceeded the request limit for this scope; retry after the rate-limit window.",
		})
		return "", false
	}

	return id, true
}

// extractRouteID extracts a single resource identifier from a known route.
// Slash, backslash, whitespace/control characters, and empty IDs are rejected
// before the value is passed to a subsystem.
func extractRouteID(path, prefix, suffix string) (string, bool) {
	if !strings.HasPrefix(path, prefix) ||
		!strings.HasSuffix(path, suffix) ||
		len(path) < len(prefix)+len(suffix) {
		return "", false
	}

	id := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	if id == "" || strings.ContainsAny(id, `/\`) {
		return "", false
	}

	for _, ch := range id {
		if ch < 0x21 || ch == 0x7f {
			return "", false
		}
	}

	return id, true
}

func probeDependency(raw, path string) map[string]any {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return map[string]any{"status": "not_configured", "healthy": false}
	}
	if !strings.Contains(raw, "://") {
		raw = "http://" + raw
	}
	parsed, err := url.Parse(raw)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") ||
		parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return map[string]any{"status": "misconfigured", "healthy": false}
	}
	parsed.Path = path
	parsed.RawPath = ""
	client := &http.Client{
		Timeout: 2 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}
	req, err := http.NewRequest(http.MethodGet, parsed.String(), nil)
	if err != nil {
		return map[string]any{"status": "misconfigured", "healthy": false}
	}
	resp, err := client.Do(req)
	if err != nil {
		return map[string]any{"status": "unavailable", "healthy": false}
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	_ = resp.Body.Close()
	healthy := resp.StatusCode >= 200 && resp.StatusCode < 300
	status := "unhealthy"
	if healthy {
		status = "ok"
	}
	return map[string]any{"status": status, "healthy": healthy, "http_status": resp.StatusCode}
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	setSecurityHeaders(w)

	if r == nil {
		replyJSON(w, http.StatusBadRequest, apiError{
			Status:  "error",
			Code:    "invalid_request",
			Message: "A valid HTTP request is required.",
		})
		return
	}

	if !applyCORS(w, r) {
		return
	}

	if s == nil || s.K == nil {
		replyJSON(w, http.StatusServiceUnavailable, apiError{
			Status:  "error",
			Code:    "kernel_unavailable",
			Message: "USECT-ZERO has not completed kernel initialization.",
		})
		return
	}

	k := s.K

	// Do not let key-management routes panic if the server was constructed
	// without an initialized key manager.
	if strings.HasPrefix(r.URL.Path, "/v1/keys/") && s.Keys == nil {
		replyJSON(w, http.StatusServiceUnavailable, apiError{
			Status:  "error",
			Code:    "key_manager_unavailable",
			Message: "The API-key management subsystem is not initialized.",
		})
		return
	}

	if r.URL.Path == "/v1/health" && r.Method == http.MethodGet {
		// Do not expose an absolute server filesystem path from public health.
		replyJSON(w, http.StatusOK, map[string]any{
			"status":                   "ok",
			"service":                  "USECT-ZERO",
			"api_version":              "v1",
			"model_free":                true,
			"offline_mode":              true,
			"repository_root_configured": k.Root != "",
			"key_manager_ready":         s.Keys != nil,
			"execution_policy":          "human-gated",
			"hardware_actuation":        false,
		})
		return
	}

	if r.URL.Path == "/v1/audit/verify" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) {
			return
		}
		report, err := k.VerifyAudit()
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status: "error",
				Code: "audit_verification_unavailable",
				Message: "The audit log could not be verified safely.",
			})
			return
		}
		status := http.StatusOK
		if !report.ChainValid {
			status = http.StatusConflict
		}
		replyJSON(w, status, report)
		return
	}

	if r.URL.Path == "/v1/supervisor/status" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) {
			return
		}
		killSwitch, err := s.Devices.KillSwitchActive()
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "supervisor_state_unavailable", Message: "Supervisor state is unavailable."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{
			"status": "ok",
			"gateway": probeDependency(os.Getenv("USECT_ZERO_GATEWAY_URL"), "/api/usect-zero/health"),
			"core_one": probeDependency(os.Getenv("GENESIS_BASE_URL"), "/v1/genesis/health"),
			"core_two": probeDependency(os.Getenv("MIND_BASE_URL"), "/v1/mind/health"),
			"kill_switch_active": killSwitch,
			"health_checks_are_advisory": true,
		})
		return
	}

	if r.URL.Path == "/v1/supervisor/kill-switch" && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}
		var in struct {
			Enabled bool   `json:"enabled"`
			Confirmation string `json:"confirmation"`
		}
		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_json", Message: "Send enabled and an explicit confirmation phrase."})
			return
		}
		expected := "DEACTIVATE_GLOBAL_KILL_SWITCH"
		if in.Enabled {
			expected = "ACTIVATE_GLOBAL_KILL_SWITCH"
		}
		if in.Confirmation != expected {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "explicit_confirmation_required", Message: "The global kill-switch confirmation phrase does not match the requested state."})
			return
		}
		if err := s.Devices.SetKillSwitch(in.Enabled); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "kill_switch_update_failed", Message: "The global kill switch could not be persisted."})
			return
		}
		outcome := "disabled"
		if in.Enabled {
			outcome = "enabled_and_tier_1_2_revoked"
		}
		if err := k.Audit("global_device_kill_switch", "human-operator", "device-registry", outcome, map[string]any{"enabled": in.Enabled}); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "audit_unavailable", Message: "The kill-switch state changed, but the audit log could not be verified; inspect supervisor state before further actions."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{"status": outcome, "kill_switch_active": in.Enabled, "tier_1_2_permissions_revoked": in.Enabled})
		return
	}

	if r.URL.Path == "/v1/devices" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) {
			return
		}
		devices, err := s.Devices.List()
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "device_registry_unavailable", Message: "The enrolled-device registry is unavailable."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{"status": "ok", "devices": devices, "count": len(devices)})
		return
	}

	if r.URL.Path == "/v1/devices/enroll" && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}
		var in struct {
			Name string `json:"name"`
			SerialPort string `json:"serial_port"`
			Scopes []string `json:"scopes"`
			Tier int `json:"tier"`
			TTLHours int `json:"ttl_hours"`
			Confirmation string `json:"confirmation"`
		}
		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_json", Message: "Send a valid enrollment object."})
			return
		}
		if in.Confirmation != "ENROLL_DEVICE" {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "explicit_confirmation_required", Message: "Provide confirmation=ENROLL_DEVICE after reviewing the device port, scopes, and tier."})
			return
		}
		if in.TTLHours < 1 || in.TTLHours > 2160 {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_device_ttl", Message: "ttl_hours must be between 1 and 2160."})
			return
		}
		device, token, err := s.Devices.Enroll(in.Name, in.SerialPort, in.Scopes, in.Tier, time.Duration(in.TTLHours)*time.Hour)
		if err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "device_enrollment_rejected", Message: err.Error()})
			return
		}
		if err := k.Audit("device_enrolled", "human-operator", device.ID, "approved", map[string]any{"tier": device.Tier, "scopes": device.Scopes}); err != nil {
			_, _ = s.Devices.Revoke(device.ID)
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "audit_unavailable", Message: "Enrollment was revoked because the audit log could not be verified."})
			return
		}
		replyJSON(w, http.StatusCreated, map[string]any{"status": "enrolled", "device": device, "device_token": token, "shown_once": true, "note": "Only the token hash is stored. Copy this token now; it cannot be retrieved again."})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/devices/") && strings.HasSuffix(r.URL.Path, "/revoke") && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}
		id, ok := extractRouteID(r.URL.Path, "/v1/devices/", "/revoke")
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_device_id", Message: "The device identifier is invalid."})
			return
		}
		var in struct { Confirmation string `json:"confirmation"` }
		if err := decodeJSON(w, r, &in); err != nil || in.Confirmation != "REVOKE_DEVICE" {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "explicit_confirmation_required", Message: "Provide confirmation=REVOKE_DEVICE."})
			return
		}
		device, err := s.Devices.Revoke(id)
		if err != nil {
			replyJSON(w, http.StatusConflict, apiError{Status: "error", Code: "device_revocation_failed", Message: "The device could not be revoked."})
			return
		}
		if err := k.Audit("device_revoked", "human-operator", device.ID, "revoked", map[string]any{"tier": device.Tier}); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "audit_unavailable", Message: "The device is revoked, but audit verification failed."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{"status": "revoked", "device_id": device.ID, "revoked_at": device.RevokedAt})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/devices/") && strings.HasSuffix(r.URL.Path, "/read") && r.Method == http.MethodGet {
		id, ok := extractRouteID(r.URL.Path, "/v1/devices/", "/read")
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_device_id", Message: "The device identifier is invalid."})
			return
		}
		token := strings.TrimSpace(r.Header.Get("X-Device-Token"))
		if _, err := s.Devices.Authorize(id, token, "device:read", 0); err != nil {
			replyJSON(w, http.StatusUnauthorized, apiError{Status: "error", Code: "device_authorization_failed", Message: "The device token is expired, revoked, or lacks read permission."})
			return
		}
		if !s.allowScopeRate("device:"+id, "device:read") {
			w.Header().Set("Retry-After", "60")
			replyJSON(w, http.StatusTooManyRequests, apiError{Status: "error", Code: "scope_rate_limit_exceeded", Message: "The device exceeded its read-scope request limit."})
			return
		}
		adapter := bridge.NewESP32USBAdapter(s.Devices)
		if err := adapter.Connect(id, token); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "device_unavailable", Message: "The enrolled ESP32 serial adapter could not connect."})
			return
		}
		defer func() { _ = adapter.Disconnect(id, token) }()
		data, err := adapter.Read(id, token)
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "device_read_failed", Message: "The enrolled device read failed."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{"status": "ok", "device_id": id, "response": string(data)})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/devices/") && strings.HasSuffix(r.URL.Path, "/act") && r.Method == http.MethodPost {
		id, ok := extractRouteID(r.URL.Path, "/v1/devices/", "/act")
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_device_id", Message: "The device identifier is invalid."})
			return
		}
		var action bridge.DeviceAction
		if err := decodeJSON(w, r, &action); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "invalid_json", Message: "Send a valid, bounded ESP32 action."})
			return
		}
		token := strings.TrimSpace(r.Header.Get("X-Device-Token"))
		device, err := s.Devices.Authorize(id, token, "device:act", 1)
		if err != nil {
			replyJSON(w, http.StatusUnauthorized, apiError{Status: "error", Code: "device_authorization_failed", Message: "The device token is expired, revoked, or lacks act permission."})
			return
		}
		if !s.allowScopeRate("device:"+id, "device:act") {
			w.Header().Set("Retry-After", "60")
			replyJSON(w, http.StatusTooManyRequests, apiError{Status: "error", Code: "scope_rate_limit_exceeded", Message: "The device exceeded its act-scope request limit."})
			return
		}
		if device.Tier == 2 && action.Confirmation != "CONFIRM_DEVICE_ACTION" {
			replyJSON(w, http.StatusBadRequest, apiError{Status: "error", Code: "explicit_confirmation_required", Message: "Tier 2 actions require confirmation=CONFIRM_DEVICE_ACTION for each action."})
			return
		}
		if err := k.Audit("device_action_requested", "human-operator", id, "pending", map[string]any{"action": action.Name, "tier": device.Tier}); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "audit_unavailable", Message: "The action was not executed because the audit log could not be verified."})
			return
		}
		adapter := bridge.NewESP32USBAdapter(s.Devices)
		if err := adapter.Connect(id, token); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "device_unavailable", Message: "The enrolled ESP32 serial adapter could not connect."})
			return
		}
		defer func() { _ = adapter.Disconnect(id, token) }()
		if err := adapter.Act(id, token, action); err != nil {
			replyJSON(w, http.StatusConflict, apiError{Status: "error", Code: "device_action_rejected", Message: "The action was rejected, not acknowledged, or failed its approval checks."})
			return
		}
		if err := k.Audit("device_action", "human-operator", id, "acknowledged", map[string]any{"action": action.Name, "tier": device.Tier}); err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{Status: "error", Code: "audit_unavailable_after_action", Message: "The ESP32 acknowledged the action, but its completion audit record failed."})
			return
		}
		replyJSON(w, http.StatusOK, map[string]any{"status": "action_acknowledged", "device_id": id, "human_confirmation_required": device.Tier == 2})
		return
	}

	if r.URL.Path == "/v1/heal/global-classify" && r.Method == http.MethodPost {
		if _, ok := s.requireScope(w, r, "scan:read"); !ok {
			return
		}

		var body map[string]string
		if err := decodeJSON(w, r, &body); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "Send a valid JSON object containing error_text and optional country/language.",
			})
			return
		}

		countryCode := strings.TrimSpace(r.URL.Query().Get("country"))
		if countryCode == "" {
			countryCode = body["country"]
		}

		language := strings.TrimSpace(r.URL.Query().Get("lang"))
		if language == "" {
			language = body["language"]
		}

		result, err := globalhealer.Classify(
			body["error_text"],
			countryCode,
			language,
			k.Root,
		)
		if err != nil {
			replyJSON(w, http.StatusUnprocessableEntity, apiError{
				Status:  "error",
				Code:    "global_diagnostic_unavailable",
				Message: "The global diagnostic classifier could not complete this request.",
			})
			return
		}

		replyJSON(w, http.StatusOK, map[string]any{
			"status":               "ok",
			"result":               result,
			"automatic_repair":     false,
			"human_review_required": true,
		})
		return
	}

	if r.URL.Path == "/v1/keys/requests" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) {
			return
		}

		status := strings.TrimSpace(r.URL.Query().Get("status"))
		if status != "" &&
			status != "pending_approval" &&
			status != "approved" &&
			status != "rejected" {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_status_filter",
				Message: "Supported status filters: pending_approval, approved, rejected.",
			})
			return
		}

		items, err := s.Keys.ListRequests(status)
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status:  "error",
				Code:    "key_requests_unavailable",
				Message: "Could not read the local key request queue.",
			})
			return
		}

		replyJSON(w, http.StatusOK, map[string]any{
			"status":   "ok",
			"requests": items,
			"count":    len(items),
		})
		return
	}

	if r.URL.Path == "/v1/keys/issued" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) {
			return
		}

		status := strings.TrimSpace(r.URL.Query().Get("status"))
		if status != "" &&
			status != "active" &&
			status != "revoked" &&
			status != "expired" {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_status_filter",
				Message: "Supported issued-key status filters: active, revoked, expired.",
			})
			return
		}

		items, err := s.Keys.ListIssued(status)
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status:  "error",
				Code:    "issued_keys_unavailable",
				Message: "Could not read issued-key metadata.",
			})
			return
		}

		// Never serialize IssuedKey directly: it contains persisted key metadata
		// that should not be exposed in this listing.
		publicKeys := make([]map[string]any, 0, len(items))
		for _, key := range items {
			publicKeys = append(publicKeys, map[string]any{
				"id":         key.ID,
				"request_id": key.RequestID,
				"scopes":     key.Scopes,
				"status":     key.Status,
				"created_at": key.CreatedAt,
				"expires_at": key.ExpiresAt,
				"revoked_at": key.RevokedAt,
				"revoked_by": key.RevokedBy,
			})
		}

		replyJSON(w, http.StatusOK, map[string]any{
			"status": "ok",
			"keys":   publicKeys,
			"count":  len(publicKeys),
		})
		return
	}

	if r.URL.Path == "/v1/keys/request" && r.Method == http.MethodPost {
		var in struct {
			Name         string   `json:"name"`
			Email        string   `json:"email"`
			RepositoryURL string  `json:"repository_url"`
			Reason       string   `json:"reason"`
			Scopes       []string `json:"scopes"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must be one valid JSON object with supported fields.",
			})
			return
		}

		req, err := s.Keys.Request(
			in.Name,
			in.Email,
			in.RepositoryURL,
			in.Reason,
			in.Scopes,
		)
		if err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_key_request",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"api_key_requested",
			"external-developer",
			req.ID,
			"pending_approval",
			map[string]any{
				"scopes":         req.Scopes,
				"repository_url": req.RepositoryURL,
			},
		)

		replyJSON(w, http.StatusAccepted, map[string]any{
			"status":        "pending_approval",
			"request":       req,
			"secret_issued": false,
			"message":       "A human operator must review and approve this request. No API key has been issued.",
		})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/keys/requests/") &&
		strings.HasSuffix(r.URL.Path, "/approve") &&
		r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}

		id, ok := extractRouteID(
			r.URL.Path,
			"/v1/keys/requests/",
			"/approve",
		)
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_resource_id",
				Message: "The key request identifier is invalid.",
			})
			return
		}

		var in struct {
			Confirmation string `json:"confirmation"`
			TTLDays      int    `json:"ttl_days"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		if in.Confirmation != "ISSUE_KEY" {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "explicit_confirmation_required",
				Message: "Provide confirmation=ISSUE_KEY after reviewing the request.",
			})
			return
		}

		if in.TTLDays <= 0 || in.TTLDays > 365 {
			in.TTLDays = 90
		}

		req, secret, err := s.Keys.Approve(
			id,
			"human-operator",
			time.Duration(in.TTLDays)*24*time.Hour,
		)
		if err != nil {
			replyJSON(w, http.StatusConflict, apiError{
				Status:  "error",
				Code:    "key_approval_failed",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"api_key_issued",
			"human-operator",
			req.ID,
			"approved",
			map[string]any{
				"scopes":          req.Scopes,
				"secret_persisted": false,
			},
		)

		// The plaintext key is returned once. The key manager must persist only
		// the key hash, not this returned secret.
		replyJSON(w, http.StatusOK, map[string]any{
			"status":     "approved",
			"request":    req,
			"api_key":    secret,
			"shown_once": true,
			"note":       "Copy the key now. Only its hash is stored; this value cannot be retrieved again.",
		})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/keys/issued/") &&
		strings.HasSuffix(r.URL.Path, "/revoke") &&
		r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}

		id, ok := extractRouteID(
			r.URL.Path,
			"/v1/keys/issued/",
			"/revoke",
		)
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_resource_id",
				Message: "The issued key identifier is invalid.",
			})
			return
		}

		var in struct {
			Confirmation string `json:"confirmation"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		if in.Confirmation != "REVOKE_KEY" {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "explicit_confirmation_required",
				Message: "Provide confirmation=REVOKE_KEY after reviewing the key.",
			})
			return
		}

		key, err := s.Keys.Revoke(id, "human-operator")
		if err != nil {
			replyJSON(w, http.StatusConflict, apiError{
				Status:  "error",
				Code:    "key_revocation_failed",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"api_key_revoked",
			"human-operator",
			key.ID,
			"revoked",
			map[string]any{"request_id": key.RequestID},
		)

		replyJSON(w, http.StatusOK, map[string]any{
			"status":     "revoked",
			"key_id":     key.ID,
			"revoked_at": key.RevokedAt,
		})
		return
	}

	if r.URL.Path == "/v1/diagnostics" && r.Method == http.MethodGet {
		actor, ok := s.requireScope(w, r, "scan:read")
		if !ok {
			return
		}

		report, err := diagnostics.Run(k)
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status:  "error",
				Code:    "diagnostics_failed",
				Message: "Could not complete the bounded operational diagnostics.",
			})
			return
		}

		_ = k.Audit(
			"core_diagnostics",
			actor,
			report.Repository.ManifestSHA256,
			report.Status,
			map[string]any{
				"baseline_status":  report.Baseline.Status,
				"added_count":      report.Baseline.AddedCount,
				"modified_count":   report.Baseline.ModifiedCount,
				"missing_count":    report.Baseline.MissingCount,
			},
		)

		replyJSON(w, http.StatusOK, report)
		return
	}

	if r.URL.Path == "/v1/scan" && r.Method == http.MethodGet {
		actor, ok := s.requireScope(w, r, "scan:read")
		if !ok {
			return
		}

		scan, err := k.SaveEvidence()
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status:  "error",
				Code:    "scan_failed",
				Message: "The evidence scan could not be completed.",
			})
			return
		}

		_ = k.Audit(
			"api_scan",
			actor,
			scan.ManifestSHA256,
			"evidence_saved",
			map[string]any{"file_count": scan.FileCount},
		)

		replyJSON(w, http.StatusOK, scan)
		return
	}

	if r.URL.Path == "/v1/heal/baseline" && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}

		baseline, err := k.RecordBaseline()
		if err != nil {
			replyJSON(w, http.StatusServiceUnavailable, apiError{
				Status:  "error",
				Code:    "baseline_failed",
				Message: "The baseline could not be recorded.",
			})
			return
		}

		replyJSON(w, http.StatusCreated, map[string]any{
			"status":                         "baseline_recorded",
			"baseline":                       baseline,
			"approval_required_for_recovery": true,
		})
		return
	}

	if r.URL.Path == "/v1/heal/proposals" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "heal:propose")
		if !ok {
			return
		}

		proposal, err := heal.ProposeMissing(k)
		if err != nil {
			replyJSON(w, http.StatusConflict, apiError{
				Status:  "error",
				Code:    "heal_proposal_failed",
				Message: "A recovery proposal could not be created.",
			})
			return
		}

		_ = k.Audit(
			"api_heal_proposal",
			actor,
			proposal.ID,
			proposal.Status,
			nil,
		)

		replyJSON(w, http.StatusCreated, proposal)
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/heal/proposals/") &&
		strings.HasSuffix(r.URL.Path, "/approve") &&
		r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}

		id, ok := extractRouteID(
			r.URL.Path,
			"/v1/heal/proposals/",
			"/approve",
		)
		if !ok {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_resource_id",
				Message: "The recovery proposal identifier is invalid.",
			})
			return
		}

		var in struct {
			Confirmation string `json:"confirmation"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		proposal, err := heal.ApproveRestore(k, id, in.Confirmation)
		if err != nil {
			replyJSON(w, http.StatusConflict, apiError{
				Status:  "error",
				Code:    "heal_approval_failed",
				Message: "The recovery proposal could not be approved.",
			})
			return
		}

		replyJSON(w, http.StatusOK, proposal)
		return
	}

	if r.URL.Path == "/v1/assemble/boards" && r.Method == http.MethodGet {
		if _, ok := s.requireScope(w, r, "scan:read"); !ok {
			return
		}

		profiles := assemble.ListBoardProfiles()
		replyJSON(w, http.StatusOK, map[string]any{
			"status":             "ok",
			"schema_version":     "usect-zero.board-profiles.v1",
			"boards":             profiles,
			"count":              len(profiles),
			"hardware_verified":  false,
			"human_review_required": true,
		})
		return
	}

	if r.URL.Path == "/v1/assemble/templates" && r.Method == http.MethodGet {
		if _, ok := s.requireScope(w, r, "scan:read"); !ok {
			return
		}

		templates := assemble.ListTemplates()
		replyJSON(w, http.StatusOK, map[string]any{
			"status":             "ok",
			"schema_version":     "usect-zero.assembly-catalog.v1",
			"templates":          templates,
			"count":              len(templates),
			"human_review_required": true,
		})
		return
	}

	if r.URL.Path == "/v1/assemble" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "assemble:propose")
		if !ok {
			return
		}

		var in struct {
			Target          string `json:"target"`
			TemplateVersion string `json:"template_version"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		out := filepath.Join(
			k.CoreRoot,
			"evidence",
			"assemble",
			time.Now().UTC().Format("20060102T150405.000000000Z"),
		)

		result, err := assemble.GenerateVersion(
			in.Target,
			in.TemplateVersion,
			out,
		)
		if err != nil {
			replyJSON(w, http.StatusUnprocessableEntity, map[string]any{
				"status": "needs_curated_template",
				"error":  err.Error(),
				"result": result,
			})
			return
		}

		for i, artifact := range result.Artifacts {
			rel, relErr := filepath.Rel(k.Root, artifact)
			if relErr == nil &&
				rel != ".." &&
				!strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
				result.Artifacts[i] = filepath.ToSlash(rel)
				continue
			}

			// A persistent data directory can be outside the repository.
			// Return a logical path instead of an absolute filesystem path.
			dataRel, dataErr := filepath.Rel(k.CoreRoot, artifact)
			if dataErr == nil &&
				dataRel != ".." &&
				!strings.HasPrefix(dataRel, ".."+string(filepath.Separator)) {
				result.Artifacts[i] = filepath.ToSlash(
					filepath.Join("usect-zero-data", dataRel),
				)
			}
		}

		_ = k.Audit(
			"assemble_proposal",
			actor,
			in.Target,
			result.Status,
			map[string]any{"artifact_count": len(result.Artifacts)},
		)

		replyJSON(w, http.StatusCreated, result)
		return
	}

	if r.URL.Path == "/v1/radar/compare" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "radar:compare")
		if !ok {
			return
		}

		var in struct {
			Current   radar.Evidence `json:"current"`
			Candidate radar.Evidence `json:"candidate"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid comparison evidence.",
			})
			return
		}

		result, err := radar.Compare(in.Current, in.Candidate)
		if err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_comparison",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"radar_comparison",
			actor,
			in.Candidate.Name,
			result.Recommendation,
			map[string]any{
				"ratio":       result.ImprovementRatio,
				"network_used": false,
			},
		)

		replyJSON(w, http.StatusOK, result)
		return
	}

	if r.URL.Path == "/v1/bridge/plan" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "bridge:propose")
		if !ok {
			return
		}

		var in struct {
			Target string `json:"target"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		result, err := bridge.BuildPlan(in.Target)
		if err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "unsupported_bridge",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"bridge_plan",
			actor,
			in.Target,
			result.Status,
			nil,
		)

		replyJSON(w, http.StatusOK, result)
		return
	}

	if r.URL.Path == "/v1/mind/compile" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "mind:compile")
		if !ok {
			return
		}

		var in struct {
			Source string `json:"source"`
		}

		if err := decodeJSON(w, r, &in); err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "invalid_json",
				Message: "The request body must contain valid JSON.",
			})
			return
		}

		result, err := mind.Compile(in.Source)
		if err != nil {
			replyJSON(w, http.StatusBadRequest, apiError{
				Status:  "error",
				Code:    "rv_compile_failed",
				Message: err.Error(),
			})
			return
		}

		_ = k.Audit(
			"rv_plan_compiled",
			actor,
			"RV Lang",
			"plan_generated_pending_review",
			map[string]any{
				"operation_count": len(result.Operations),
				"executed":        false,
			},
		)

		replyJSON(w, http.StatusOK, result)
		return
	}

	if r.URL.Path == "/v1/mind/ide" && r.Method == http.MethodGet {
		http.ServeFile(
			w,
			r,
			filepath.Join(k.CoreRoot, "ide", "index.html"),
		)
		return
	}

	if r.URL.Path == "/v1/keys/request" && r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		replyJSON(w, http.StatusMethodNotAllowed, apiError{
			Status:  "error",
			Code:    "method_not_allowed",
			Message: "Use POST to request API access.",
		})
		return
	}

	if strings.HasPrefix(r.URL.Path, "/v1/") {
		replyJSON(w, http.StatusNotFound, apiError{
			Status:  "error",
			Code:    "not_found",
			Message: "No route matched this API version and path.",
		})
		return
	}

	http.NotFound(w, r)
}

// ParsePositiveInt is shared by bounded retention and quota settings.
// It rejects non-integers, zero, negative values, and values above max.
func ParsePositiveInt(s string, max int) (int, error) {
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 || n > max {
		return 0, errors.New("integer outside allowed bounds")
	}

	return n, nil
}
