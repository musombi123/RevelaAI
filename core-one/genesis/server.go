package genesis

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"revela-genesis.local/core-one/rvx"
	"revela-genesis.local/core-one/endpoint"
)

type Server struct{ Engine *Engine }

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "no-store")
	if r.Method == http.MethodOptions {
		w.Header().Set("Allow", "GET, POST, OPTIONS")
		w.WriteHeader(http.StatusNoContent)
		return
	}
	path := strings.TrimRight(r.URL.Path, "/")
	if !remoteIsLoopback(r.RemoteAddr) && path != "/v1/genesis/health" && !s.authorized(r) {
		writeAPIError(w, http.StatusUnauthorized, "genesis_auth_required", "Remote requests require the configured Genesis token.")
		return
	}
	switch {
	case path == "/v1/genesis/health" && r.Method == http.MethodGet:
		model := os.Getenv("GENESIS_MODEL_BASE_URL") != ""
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "ok", "version": Version, "standalone": true, "model_assisted": model, "execution": "proposal_only", "merge": "human_required"})
	case path == "/v1/genesis/status" && r.Method == http.MethodGet:
		status, err := s.Engine.OperationalStatus()
		if err != nil { writeAPIError(w, http.StatusInternalServerError, "status_unavailable", "Could not assemble operational status."); return }
		writeAPIJSON(w, http.StatusOK, status)
	case path == "/v1/genesis/invent" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) {
			return
		}
		var body struct { Demand string `json:"demand"`; Country string `json:"country,omitempty"`; Language string `json:"language,omitempty"` }
		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(w, http.StatusBadRequest, "invalid_json", "Request must contain a valid JSON object with demand.")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 35*time.Second)
		defer cancel()
		profile, profileErr := endpoint.ResolveWorldContext(r, body.Country, body.Language)
		if profileErr != nil { writeAPIError(w, http.StatusBadRequest, "invalid_country", profileErr.Error()); return }
		inv, err := s.Engine.InventWorldwide(ctx, body.Demand, profile.Code, profile.Language)
		if err != nil {
			if errors.Is(err, ErrBlocked) { writeAPIError(w, http.StatusForbidden, "guardian_block", "Guardian blocked the demand; no invention package was created."); return }
			if errors.Is(err, ErrAlreadyExists) { writeAPIError(w, http.StatusConflict, "already_exists", err.Error()); return }
			writeAPIError(w, http.StatusUnprocessableEntity, "invention_failed", err.Error()); return
		}
		writeAPIJSON(w, http.StatusCreated, inv)
	case path == "/v1/genesis/queue" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var body struct { Demand string `json:"demand"`; Source string `json:"source,omitempty"`; Country string `json:"country,omitempty"`; Language string `json:"language,omitempty"` }
		if err := decodeAPIJSON(w, r, &body); err != nil { writeAPIError(w, http.StatusBadRequest, "invalid_json", "Request must contain demand."); return }
		profile, profileErr := endpoint.ResolveWorldContext(r, body.Country, body.Language)
		if profileErr != nil { writeAPIError(w, http.StatusBadRequest, "invalid_country", profileErr.Error()); return }
		item, err := s.Engine.EnqueueWorldwide(body.Demand, body.Source, profile.Code, profile.Language)
		if err != nil { if errors.Is(err, ErrBlocked) { writeAPIError(w, http.StatusForbidden, "guardian_block", "Guardian blocked the demand before queueing."); return }; writeAPIError(w, http.StatusBadRequest, "invalid_demand", err.Error()); return }
		s.Engine.publish(Event{Type: "demand_queued", At: time.Now().UTC(), Message: "Demand accepted into the local queue for the next daemon cycle.", Status: "queued"})
		writeAPIJSON(w, http.StatusAccepted, map[string]any{"status": "queued", "demand_id": item.ID, "next_scan": "within the configured daemon interval"})
	case path == "/v1/genesis/tools" && r.Method == http.MethodGet:
		items, err := s.Engine.ListInventions()
		if err != nil { writeAPIError(w, 500, "tools_unavailable", "Could not list invention proposals."); return }
		writeAPIJSON(w, 200, map[string]any{"tools": items, "count": len(items)})
	case strings.HasPrefix(path, "/v1/genesis/tools/") && r.Method == http.MethodGet:
		s.serveTool(w, r, strings.TrimPrefix(path, "/v1/genesis/tools/"))
	case path == "/v1/genesis/stream" && r.Method == http.MethodGet:
		s.serveStream(w, r)
	case path == "/v1/genesis/key" && (r.Method == http.MethodPost || r.Method == http.MethodGet):
		if r.Method == http.MethodPost { if !s.allowMutation(w, r) { return }; s.requestProviderKey(w, r); return }
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "request_required", "message": "Genesis does not disclose or mint bearer secrets through this endpoint. POST a request for human approval, or configure standalone mode."})
	case path == "/v1/rvx/compile" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var body struct { Source string `json:"source"` }
		if err := decodeAPIJSON(w, r, &body); err != nil { writeAPIError(w, 400, "invalid_json", "Request must contain source text."); return }
		compiled, err := rvx.Compile(body.Source)
		if err != nil { writeAPIError(w, 422, "rvx_compile_error", err.Error()); return }
		writeAPIJSON(w, 200, compiled)
	default:
		writeAPIError(w, http.StatusNotFound, "not_found", "Route not found.")
	}
}

func (s *Server) authorized(r *http.Request) bool {
	configured := strings.TrimSpace(os.Getenv("GENESIS_ADMIN_TOKEN"))
	if configured == "" { return false }
	given := strings.TrimSpace(r.Header.Get("X-Genesis-Token"))
	if given == "" && strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") { given = strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")) }
	return len(given) == len(configured) && subtle.ConstantTimeCompare([]byte(given), []byte(configured)) == 1
}
func (s *Server) allowMutation(w http.ResponseWriter, r *http.Request) bool {
	if s.authorized(r) || (strings.TrimSpace(os.Getenv("GENESIS_ADMIN_TOKEN")) == "" && remoteIsLoopback(r.RemoteAddr)) { return true }
	writeAPIError(w, http.StatusUnauthorized, "genesis_auth_required", "Supply a valid X-Genesis-Token/Bearer token; without a configured token, mutations are permitted only over loopback.")
	return false
}
func remoteIsLoopback(remote string) bool {
	host, _, err := net.SplitHostPort(remote); if err != nil { host = remote }
	ip := net.ParseIP(strings.Trim(host, "[]")); return ip != nil && ip.IsLoopback()
}

func (s *Server) serveTool(w http.ResponseWriter, r *http.Request, part string) {
	parts := strings.Split(part, "/")
	if len(parts) == 0 || !validResourceName(parts[0]) { writeAPIError(w, 400, "invalid_tool_name", "Invalid tool name."); return }
	name := parts[0]; dir := filepath.Join(s.Engine.CoreRoot, "inventions", name)
	if len(parts) == 2 && parts[1] == "hardware_guide" {
		guide, profile, err := s.Engine.WorldwideHardwareGuide(name, r.URL.Query().Get("country"), r.URL.Query().Get("lang")); if err != nil { writeAPIError(w, 404, "tool_not_found", "Guide or country profile unavailable."); return }
		writeAPIJSON(w, 200, map[string]any{"name": name, "status": "await_merge", "country_context": profile, "hardware_guide": guide}); return
	}
	if len(parts) == 2 && parts[1] == "capability_plan" {
		b, err := os.ReadFile(filepath.Join(dir, "capability_plan.json"))
		if err != nil { writeAPIError(w, 404, "capability_plan_not_found", "Tool or capability plan not found."); return }
		var plan CapabilityPlan
		if err := json.Unmarshal(b, &plan); err != nil { writeAPIError(w, 500, "capability_plan_invalid", "Saved capability plan could not be parsed."); return }
		writeAPIJSON(w, 200, map[string]any{"name": name, "status": "await_merge", "capability_plan": plan})
		return
	}
	if len(parts) != 1 { writeAPIError(w, 404, "not_found", "Route not found."); return }
	b, err := os.ReadFile(filepath.Join(dir, "evidence.json")); if err != nil { writeAPIError(w, 404, "tool_not_found", "Tool proposal not found."); return }
	var record map[string]any
	if err := json.Unmarshal(b, &record); err != nil { writeAPIError(w, 500, "proposal_invalid", "Saved proposal evidence could not be parsed."); return }
	writeAPIJSON(w, 200, map[string]any{"name": name, "status": "await_merge", "proposal": record, "hardware_guide_url": "/v1/genesis/tools/" + name + "/hardware_guide"})
}

func (s *Server) serveStream(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher); if !ok { writeAPIError(w, 500, "stream_unsupported", "Server does not support event streaming."); return }
	w.Header().Set("Content-Type", "text/event-stream"); w.Header().Set("Connection", "keep-alive"); w.Header().Set("X-Accel-Buffering", "no")
	// Clear the server-wide write deadline for a long-lived stream; heartbeats keep it active.
	_ = http.NewResponseController(w).SetWriteDeadline(time.Time{})
	ch, cancel := s.Engine.Subscribe(); defer cancel(); deadline := time.NewTicker(20 * time.Second); defer deadline.Stop()
	w.WriteHeader(200); _, _ = io.WriteString(w, ": genesis stream connected\n\n"); flusher.Flush()
	for { select {
	case <-r.Context().Done(): return
	case event, open := <-ch:
		if !open { return }; b, err := json.Marshal(event); if err != nil { continue }
		_, _ = io.WriteString(w, "event: "+event.Type+"\ndata: "+string(b)+"\n\n"); flusher.Flush()
	case <-deadline.C: _, _ = io.WriteString(w, ": heartbeat\n\n"); flusher.Flush()
	} }
}

func (s *Server) requestProviderKey(w http.ResponseWriter, r *http.Request) {
	var body struct { ClientID string `json:"client_id"`; Reason string `json:"reason"` }
	if err := decodeAPIJSON(w, r, &body); err != nil { writeAPIError(w, 400, "invalid_json", "Request must contain client_id and reason."); return }
	body.ClientID = limitText(body.ClientID, 120); body.Reason = limitText(body.Reason, 500)
	if body.ClientID == "" || body.Reason == "" { writeAPIError(w, 400, "missing_fields", "client_id and reason are required."); return }
	req := map[string]any{"id": newID("provider_request"), "client_id": body.ClientID, "reason": body.Reason, "created_at": time.Now().UTC(), "status": "pending_approval", "note": "No secret was issued by this request."}
	if err := writeJSON(filepath.Join(s.Engine.CoreRoot, "state", "key_requests", req["id"].(string)+".json"), req); err != nil { writeAPIError(w, 500, "key_request_failed", "Could not save provider key request."); return }
	writeAPIJSON(w, 202, req)
}

func (e *Engine) ListInventions() ([]map[string]any, error) {
	entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "inventions")); if err != nil { return nil, err }
	out := make([]map[string]any, 0, len(entries))
	for _, item := range entries {
		if !item.IsDir() || strings.HasPrefix(item.Name(), ".staging-") || !validResourceName(item.Name()) { continue }
		raw, err := os.ReadFile(filepath.Join(e.CoreRoot, "inventions", item.Name(), "evidence.json")); if err != nil { continue }
		var rec struct { ID string `json:"invention_id"`; CreatedAt time.Time `json:"created_at"`; Status string `json:"status"`; Specification ToolSpec `json:"specification"` }
		if json.Unmarshal(raw, &rec) != nil { continue }
		capabilitySummary := map[string]any{"url": "/v1/genesis/tools/" + item.Name() + "/capability_plan"}
		if planBytes, err := os.ReadFile(filepath.Join(e.CoreRoot, "inventions", item.Name(), "capability_plan.json")); err == nil {
			var plan CapabilityPlan
			if json.Unmarshal(planBytes, &plan) == nil { capabilitySummary["status"] = plan.Status; capabilitySummary["coverage"] = plan.Coverage; capabilitySummary["unresolved"] = plan.MissingCapabilities }
		}
		out = append(out, map[string]any{"id": rec.ID, "name": item.Name(), "title": rec.Specification.Title, "category": rec.Specification.Category, "industry": rec.Specification.Industry, "status": "await_merge", "created_at": rec.CreatedAt, "capability_plan": capabilitySummary})
	}
	return out, nil
}


func (e *Engine) OperationalStatus() (map[string]any, error) {
	inventions, err := e.ListInventions()
	if err != nil { return nil, err }
	queueCounts := map[string]int{}
	for _, state := range []string{"pending", "processing", "await_merge", "blocked", "failed"} {
		entries, err := os.ReadDir(filepath.Join(e.CoreRoot, "state", "queue", state))
		if os.IsNotExist(err) { queueCounts[state] = 0; continue }
		if err != nil { return nil, err }
		for _, entry := range entries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") { continue }
			info, err := entry.Info()
			if err == nil && info.Mode().IsRegular() { queueCounts[state]++ }
		}
	}
	latestResearch := ""
	researchEntries, err := os.ReadDir(filepath.Join(e.CoreRoot, "research"))
	if err != nil && !os.IsNotExist(err) { return nil, err }
	if err == nil {
		for i := len(researchEntries)-1; i >= 0; i-- {
			entry := researchEntries[i]
			if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".json") { latestResearch = entry.Name(); break }
		}
	}
	guardianOK, guardianReason := e.Guardian.policyReady()
	blockedLog := filepath.Join(e.CoreRoot, "guardian", "blocked.log")
	var blockedLogUpdated any
	if info, err := os.Stat(blockedLog); err == nil { blockedLogUpdated = info.ModTime().UTC() }
	return map[string]any{
		"status": "ok", "version": Version, "standalone": true,
		"model_assisted": strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL")) != "",
		"offline_mode": strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "1") || strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "true"),
		"guardian": map[string]any{"ready": guardianOK, "reason": guardianReason, "blocked_log_updated_at": blockedLogUpdated},
		"queue": queueCounts, "invention_count": len(inventions), "latest_research_file": latestResearch,
		"generated_code_execution": false, "automatic_merge": false,
	}, nil
}

func decodeAPIJSON(w http.ResponseWriter, r *http.Request, out any) error {
	defer r.Body.Close(); dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)); dec.DisallowUnknownFields()
	if err := dec.Decode(out); err != nil { return err }; var extra any; if err := dec.Decode(&extra); err != io.EOF { return errors.New("request body must contain exactly one JSON value") }; return nil
}
func writeAPIJSON(w http.ResponseWriter, status int, value any) { w.Header().Set("Content-Type", "application/json; charset=utf-8"); w.WriteHeader(status); _ = json.NewEncoder(w).Encode(value) }
func writeAPIError(w http.ResponseWriter, status int, code, message string) { writeAPIJSON(w, status, map[string]string{"status": "error", "code": code, "message": message}) }
func validResourceName(name string) bool {
	if name == "" || len(name) > 64 || name == "." || name == ".." { return false }
	for _, r := range name { if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '_' || r == '-') { return false } }; return true
}
