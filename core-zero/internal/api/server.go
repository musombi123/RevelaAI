package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"usect-zero.local/core-zero/assemble"
	"usect-zero.local/core-zero/bridge"
	"usect-zero.local/core-zero/forge"
	"usect-zero.local/core-zero/heal"
	"usect-zero.local/core-zero/internal/kernel"
	"usect-zero.local/core-zero/mind"
	"usect-zero.local/core-zero/radar"
)

type apiError struct {
	Status  string `json:"status"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func replyJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func decodeJSON(w http.ResponseWriter, r *http.Request, v any) error {
	defer r.Body.Close()
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		return e
	}
	var extra any
	if e := d.Decode(&extra); e != io.EOF {
		return errors.New("request must contain one JSON object")
	}
	return nil
}
func (s *Server) adminOK(r *http.Request) bool {
	configured := strings.TrimSpace(os.Getenv("USECT_ZERO_ADMIN_TOKEN"))
	if configured == "" {
		return false
	}
	given := strings.TrimSpace(r.Header.Get("X-Admin-Token"))
	if given == "" && strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
		given = strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
	}
	if len(given) != len(configured) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(given), []byte(configured)) == 1
}
func (s *Server) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	if !s.adminOK(r) {
		replyJSON(w, 401, apiError{"error", "admin_approval_required", "A valid USECT-ZERO admin token is required; no action was executed."})
		return false
	}
	return true
}
func (s *Server) requireScope(w http.ResponseWriter, r *http.Request, scope string) (string, bool) {
	key := strings.TrimSpace(r.Header.Get("X-API-Key"))
	ok, id := s.Keys.Validate(key, scope)
	if !ok {
		replyJSON(w, 401, apiError{"error", "api_key_or_scope_required", "Supply an active X-API-Key with scope " + scope + ". Key requests remain pending until human approval."})
		return "", false
	}
	return id, true
}

type Server struct {
	K    *kernel.Kernel
	Keys *forge.KeyManager
}

func New(k *kernel.Kernel) *Server { return &Server{K: k, Keys: forge.New(k.CoreRoot)} }
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	k := s.K
	if r.URL.Path == "/v1/health" && r.Method == http.MethodGet {
		replyJSON(w, 200, map[string]any{"status": "ok", "service": "USECT-ZERO", "model_free": true, "offline_mode": true, "repository_root": k.Root, "execution_policy": "human-gated", "hardware_actuation": false})
		return
	}
	if r.URL.Path == "/v1/keys/requests" && r.Method == http.MethodGet {
		if !s.requireAdmin(w, r) { return }
		status := strings.TrimSpace(r.URL.Query().Get("status"))
		if status != "" && status != "pending_approval" && status != "approved" && status != "rejected" {
			replyJSON(w, 400, apiError{"error", "invalid_status_filter", "Supported status filters: pending_approval, approved, rejected."})
			return
		}
		items, err := s.Keys.ListRequests(status)
		if err != nil { replyJSON(w, 503, apiError{"error", "key_requests_unavailable", "Could not read the local key request queue."}); return }
		replyJSON(w, 200, map[string]any{"status": "ok", "requests": items, "count": len(items)})
		return
	}
	if r.URL.Path == "/v1/keys/request" && r.Method == http.MethodPost {
		var in struct {
			Name string `json:"name"`
			Email string `json:"email"`
			RepositoryURL string `json:"repository_url"`
			Reason string `json:"reason"`
			Scopes []string `json:"scopes"`
		}
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		req, e := s.Keys.Request(in.Name, in.Email, in.RepositoryURL, in.Reason, in.Scopes)
		if e != nil { replyJSON(w, 400, apiError{"error", "invalid_key_request", e.Error()}); return }
		_ = k.Audit("api_key_requested", "external-developer", req.ID, "pending_approval", map[string]any{"scopes": req.Scopes, "repository_url": req.RepositoryURL})
		replyJSON(w, 202, map[string]any{"status": "pending_approval", "request": req, "secret_issued": false, "message": "A human operator must review and approve this request. No API key has been issued."})
		return
	}
	if strings.HasPrefix(r.URL.Path, "/v1/keys/requests/") && strings.HasSuffix(r.URL.Path, "/approve") && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) { return }
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/keys/requests/"), "/approve")
		var in struct { Confirmation string `json:"confirmation"`; TTLDays int `json:"ttl_days"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		if in.Confirmation != "ISSUE_KEY" { replyJSON(w, 400, apiError{"error", "explicit_confirmation_required", "Provide confirmation=ISSUE_KEY after reviewing the request."}); return }
		if in.TTLDays <= 0 || in.TTLDays > 365 { in.TTLDays = 90 }
		req, secret, e := s.Keys.Approve(id, "human-operator", time.Duration(in.TTLDays)*24*time.Hour)
		if e != nil { replyJSON(w, 409, apiError{"error", "key_approval_failed", e.Error()}); return }
		_ = k.Audit("api_key_issued", "human-operator", req.ID, "approved", map[string]any{"scopes": req.Scopes, "secret_persisted": false})
		replyJSON(w, 200, map[string]any{"status": "approved", "request": req, "api_key": secret, "shown_once": true, "note": "Copy the key now. Only its hash is stored; this value cannot be retrieved again."})
		return
	}
	if strings.HasPrefix(r.URL.Path, "/v1/keys/issued/") && strings.HasSuffix(r.URL.Path, "/revoke") && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) { return }
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/keys/issued/"), "/revoke")
		var in struct { Confirmation string `json:"confirmation"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		if in.Confirmation != "REVOKE_KEY" { replyJSON(w, 400, apiError{"error", "explicit_confirmation_required", "Provide confirmation=REVOKE_KEY after reviewing the key."}); return }
		key, e := s.Keys.Revoke(id, "human-operator")
		if e != nil { replyJSON(w, 409, apiError{"error", "key_revocation_failed", e.Error()}); return }
		_ = k.Audit("api_key_revoked", "human-operator", key.ID, "revoked", map[string]any{"request_id": key.RequestID})
		replyJSON(w, 200, map[string]any{"status": "revoked", "key_id": key.ID, "revoked_at": key.RevokedAt})
		return
	}
	if r.URL.Path == "/v1/scan" && r.Method == http.MethodGet {
		actor, ok := s.requireScope(w, r, "scan:read")
		if !ok { return }
		scan, e := k.SaveEvidence()
		if e != nil { replyJSON(w, 503, apiError{"error", "scan_failed", e.Error()}); return }
		_ = k.Audit("api_scan", actor, scan.ManifestSHA256, "evidence_saved", map[string]any{"file_count": scan.FileCount})
		replyJSON(w, 200, scan)
		return
	}
	if r.URL.Path == "/v1/heal/baseline" && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) { return }
		b, e := k.RecordBaseline()
		if e != nil { replyJSON(w, 503, apiError{"error", "baseline_failed", e.Error()}); return }
		replyJSON(w, 201, map[string]any{"status": "baseline_recorded", "baseline": b, "approval_required_for_recovery": true})
		return
	}
	if r.URL.Path == "/v1/heal/proposals" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "heal:propose")
		if !ok { return }
		p, e := heal.ProposeMissing(k)
		if e != nil { replyJSON(w, 409, apiError{"error", "heal_proposal_failed", e.Error()}); return }
		_ = k.Audit("api_heal_proposal", actor, p.ID, p.Status, nil)
		replyJSON(w, 201, p)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/v1/heal/proposals/") && strings.HasSuffix(r.URL.Path, "/approve") && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) { return }
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/heal/proposals/"), "/approve")
		var in struct { Confirmation string `json:"confirmation"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		p, e := heal.ApproveRestore(k, id, in.Confirmation)
		if e != nil { replyJSON(w, 409, apiError{"error", "heal_approval_failed", e.Error()}); return }
		replyJSON(w, 200, p)
		return
	}
	if r.URL.Path == "/v1/assemble" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "assemble:propose")
		if !ok { return }
		var in struct { Target string `json:"target"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		out := filepath.Join(k.CoreRoot, "evidence", "assemble", time.Now().UTC().Format("20060102T150405.000000000Z"))
		res, e := assemble.Generate(in.Target, out)
		if e != nil { replyJSON(w, 422, map[string]any{"status": "needs_curated_template", "error": e.Error(), "result": res}); return }
		for i, p := range res.Artifacts { rel, er := filepath.Rel(k.Root, p); if er == nil { res.Artifacts[i] = filepath.ToSlash(rel) } }
		_ = k.Audit("assemble_proposal", actor, in.Target, res.Status, map[string]any{"artifact_count": len(res.Artifacts)})
		replyJSON(w, 201, res)
		return
	}
	if r.URL.Path == "/v1/radar/compare" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "radar:compare")
		if !ok { return }
		var in struct { Current radar.Evidence `json:"current"`; Candidate radar.Evidence `json:"candidate"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		res, e := radar.Compare(in.Current, in.Candidate)
		if e != nil { replyJSON(w, 400, apiError{"error", "invalid_comparison", e.Error()}); return }
		_ = k.Audit("radar_comparison", actor, in.Candidate.Name, res.Recommendation, map[string]any{"ratio": res.ImprovementRatio, "network_used": false})
		replyJSON(w, 200, res)
		return
	}
	if r.URL.Path == "/v1/bridge/plan" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "bridge:propose")
		if !ok { return }
		var in struct { Target string `json:"target"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		res, e := bridge.BuildPlan(in.Target)
		if e != nil { replyJSON(w, 400, apiError{"error", "unsupported_bridge", e.Error()}); return }
		_ = k.Audit("bridge_plan", actor, in.Target, res.Status, nil)
		replyJSON(w, 200, res)
		return
	}
	if r.URL.Path == "/v1/mind/compile" && r.Method == http.MethodPost {
		actor, ok := s.requireScope(w, r, "mind:compile")
		if !ok { return }
		var in struct { Source string `json:"source"` }
		if e := decodeJSON(w, r, &in); e != nil { replyJSON(w, 400, apiError{"error", "invalid_json", e.Error()}); return }
		res, e := mind.Compile(in.Source)
		if e != nil { replyJSON(w, 400, apiError{"error", "rv_compile_failed", e.Error()}); return }
		_ = k.Audit("rv_plan_compiled", actor, "RV Lang", "plan_generated_pending_review", map[string]any{"operation_count": len(res.Operations), "executed": false})
		replyJSON(w, 200, res)
		return
	}
	if r.URL.Path == "/v1/mind/ide" && r.Method == http.MethodGet { http.ServeFile(w, r, filepath.Join(k.CoreRoot, "ide", "index.html")); return }
	if r.URL.Path == "/v1/keys/request" && r.Method != http.MethodPost { w.Header().Set("Allow", http.MethodPost); replyJSON(w, 405, apiError{"error", "method_not_allowed", "Use POST to request API access."}); return }
	if strings.HasPrefix(r.URL.Path, "/v1/") { replyJSON(w, 404, apiError{"error", "not_found", "No route matched this API version and path."}); return }
	http.NotFound(w, r)
}

// ParsePositiveInt is shared by future retention/quotas; it rejects unbounded/invalid values.
func ParsePositiveInt(s string, max int) (int, error) {
	n, e := strconv.Atoi(s)
	if e != nil || n < 1 || n > max { return 0, errors.New("integer outside allowed bounds") }
	return n, nil
}
