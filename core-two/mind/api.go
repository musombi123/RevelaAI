package mind

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"revela-mind.local/core-two/provider"
)

func (s *Service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	switch {
	case r.URL.Path == "/v1/mind/health" && r.Method == http.MethodGet:
		mirror, _ := os.ReadFile(filepath.Join(s.CoreRoot, "metrics", "mirror.json"))
		var mirrorStatus any
		if len(mirror) > 0 { _ = json.Unmarshal(mirror, &mirrorStatus) }
		writeJSON(w, 200, map[string]any{"status": "ok", "service": "USECT-TWO", "version": Version, "model_free": true, "integration": s.IntegrationStatus(), "mirror": mirrorStatus})
	case r.URL.Path == "/v1/mind/metrics" && r.Method == http.MethodGet:
		result, err := s.Scan(r.Context())
		if err != nil { writeAPIError(w, 503, "metrics_unavailable", err.Error()); return }
		writeJSON(w, 200, result)
	case r.URL.Path == "/v1/mind/evolve" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var req EvolveRequest
		if err := decodeJSON(w, r, &req); err != nil { writeAPIError(w, 400, "invalid_json", err.Error()); return }
		result, err := s.Evolve(r.Context(), req)
		if err != nil { if errors.Is(err, ErrGuardianBlocked) { writeAPIError(w, 403, "guardian_blocked", "Guardian blocked the request before creating any mutation or evolution files."); return }; if errors.Is(err, ErrNoQualifiedMutation) { writeAPIError(w, 422, "no_qualified_mutation", err.Error()); return }; writeAPIError(w, 500, "evolution_failed", err.Error()); return }
		writeJSON(w, 202, result)
	case r.URL.Path == "/v1/mind/learning" && r.Method == http.MethodGet:
		summary, err := s.learningSummary(); if err != nil { writeAPIError(w, 503, "learning_unavailable", "Could not read the human-feedback ledger."); return }; writeJSON(w, 200, summary)
	case r.URL.Path == "/v1/mind/feedback" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var feedback LearningFeedback
		if err := decodeJSON(w, r, &feedback); err != nil { writeAPIError(w, 400, "invalid_json", err.Error()); return }
		summary, err := s.RecordFeedback(feedback); if err != nil { writeAPIError(w, 422, "feedback_rejected", err.Error()); return }; writeJSON(w, 201, summary)
	case r.URL.Path == "/v1/mind/telemetry/events" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var event ToolTelemetryEvent
		if err := decodeStrictAPIJSON(w, r, &event); err != nil { writeAPIError(w, 400, "invalid_telemetry", "Telemetry must contain only the declared operational fields."); return }
		if err := s.RecordToolTelemetry(event); err != nil { writeAPIError(w, 422, "telemetry_rejected", err.Error()); return }
		writeJSON(w, 201, map[string]any{"status": "recorded", "tool_name": event.ToolName, "version_hash": event.VersionHash, "user_content_recorded": false, "synthetic_fixture": false})
	case r.URL.Path == "/v1/mind/candidates" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var candidate FoundryCandidate
		if err := decodeStrictAPIJSON(w, r, &candidate); err != nil { writeAPIError(w, 400, "invalid_candidate", "Candidate must contain only the declared metadata fields."); return }
		result, err := s.ScoreFoundryCandidate(r.Context(), candidate, CoreOneFoundrySource{})
		if err != nil {
			if errors.Is(err, ErrGuardianBlocked) { writeAPIError(w, 403, "guardian_blocked", "Mind or Core-One Guardian blocked this candidate before scoring."); return }
			writeAPIError(w, 422, "candidate_rejected", err.Error()); return
		}
		writeJSON(w, 200, result)
	case r.URL.Path == "/v1/mind/evolutions" && r.Method == http.MethodGet:
		items, err := s.listEvolutions(); if err != nil { writeAPIError(w, 503, "evolutions_unavailable", err.Error()); return }; writeJSON(w, 200, map[string]any{"status": "ok", "evolutions": items, "count": len(items)})
	case strings.HasPrefix(r.URL.Path, "/v1/mind/tools/") && strings.HasSuffix(r.URL.Path, "/improvement") && r.Method == http.MethodGet:
		name := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/mind/tools/"), "/improvement")
		if !validName(name) || !safeMindToolName(name) { writeAPIError(w, 400, "invalid_tool_name", "Invalid tool name."); return }
		snapshot := s.ToolTelemetrySnapshot()
		versions := []ToolVersionMetrics{}
		if all, ok := snapshot["tools"].(map[string][]ToolVersionMetrics); ok { versions = all[name] }
		raw, readErr := readMindFileWithinRoot(s.CoreRoot, filepath.Join("metrics", name+".json"), maxEvidenceBytes)
		var detail map[string]any
		if readErr == nil {
			if err := json.Unmarshal(raw, &detail); err != nil || detail == nil { writeAPIError(w, 503, "metrics_invalid", "The stored improvement record is invalid."); return }
		} else if os.IsNotExist(readErr) && len(versions) > 0 {
			detail = map[string]any{"tool_name": name, "status": "observed", "provenance": "recorded_tool_runner_events"}
		} else if snapshot["status"] == "unavailable" {
			writeAPIError(w, 503, "telemetry_unavailable", "Recorded tool telemetry is unavailable or invalid."); return
		} else if os.IsNotExist(readErr) {
			writeAPIError(w, 404, "metrics_not_found", "No improvement or telemetry record exists for this name."); return
		} else {
			writeAPIError(w, 503, "metrics_unavailable", "The stored improvement record is unavailable or unsafe."); return
		}
		detail["tool_telemetry"] = map[string]any{"status": snapshot["status"], "versions": versions, "provenance": "recorded_tool_runner_events"}
		detail["synthetic_fixture"] = false
		detail["production_verified"] = false
		writeJSON(w, 200, detail)
	case r.URL.Path == "/v1/mind/key" && r.Method == http.MethodGet:
		mesh := provider.FromEnvironment(); writeJSON(w, 200, map[string]any{"status": "request_required", "provider_url_configured": mesh.BaseURL != "", "provider_key_configured": mesh.Key != "", "credential_env_names": []string{"REVELACODE_PROVIDER_URL", "REVELACODE_PROVIDER_KEY"}, "same_credentials_as_core_one": true, "secret_disclosed": false})
	case r.URL.Path == "/v1/mind/key" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) { return }
		var body struct { ClientID string `json:"client_id"`; Reason string `json:"reason"` }
		if err := decodeJSON(w, r, &body); err != nil { writeAPIError(w, 400, "invalid_json", err.Error()); return }
		body.ClientID = strings.TrimSpace(body.ClientID); body.Reason = strings.TrimSpace(body.Reason)
		if body.ClientID == "" || body.Reason == "" || len(body.ClientID) > 120 || len(body.Reason) > 500 { writeAPIError(w, 400, "missing_fields", "client_id and reason (1–500 characters) are required."); return }
		request := map[string]any{"id": fmt.Sprintf("mind-key-%d", time.Now().UTC().UnixNano()), "client_id": body.ClientID, "reason": body.Reason, "created_at": time.Now().UTC(), "status": "pending_approval", "secret_issued": false}
		if err := writeJSONFile(filepath.Join(s.CoreRoot, "state", "provider_key_requests", request["id"].(string)+".json"), request, 0o600); err != nil { writeAPIError(w, 500, "key_request_failed", "Could not save the provider-key request."); return }; writeJSON(w, 202, request)
	case r.URL.Path == "/v1/mind/stream" && r.Method == http.MethodGet:
		s.serveStream(w, r)
	case r.URL.Path == "/v1/zero/status" && r.Method == http.MethodGet:
		writeJSON(w, 200, map[string]any{"status": "ok", "integration": s.IntegrationStatus(), "audit_log_observed": fileExists(filepath.Join(s.ZeroRoot, "audit_log", "events.jsonl")), "healing_evidence_observed": directoryExists(filepath.Join(s.ZeroRoot, "evidence", "heal"))})
	case strings.HasPrefix(r.URL.Path, "/v1/zero/"):
		s.proxyCore(w, r, "zero")
	case strings.HasPrefix(r.URL.Path, "/v1/genesis/") || r.URL.Path == "/v1/rvx/compile":
		s.proxyCore(w, r, "one")
	default:
		writeAPIError(w, 404, "not_found", "Route not found.")
	}
}

func (s *Service) allowMutation(w http.ResponseWriter, r *http.Request) bool {
	configured := strings.TrimSpace(os.Getenv("MIND_ADMIN_TOKEN"))
	if configured == "" { writeAPIError(w, 503, "mind_mutations_disabled", "MIND_ADMIN_TOKEN is not configured; Mind API mutations fail closed."); return false }
	given := strings.TrimSpace(r.Header.Get("X-Mind-Token")); if given == "" && strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") { given = strings.TrimSpace(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")) }
	if len(given) == len(configured) && subtleConstantTimeEqual(given, configured) { return true }
	writeAPIError(w, 401, "mind_auth_required", "Supply a valid X-Mind-Token or Bearer token."); return false
}

func normalizeCoreBase(raw string) (string, error) {
    raw = strings.TrimSpace(raw)
    if raw == "" { return "", fmt.Errorf("core URL is empty") }
    if !strings.Contains(raw, "://") {
        if strings.ContainsAny(raw, "/?#@") { return "", fmt.Errorf("invalid internal host:port") }
        candidate, err := url.Parse("//" + raw)
        if err != nil || candidate.Hostname() == "" { return "", fmt.Errorf("invalid internal host:port") }
        raw = "http://" + raw
    }
    parsed, err := url.Parse(raw)
    if err != nil || parsed.Hostname() == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") {
        return "", fmt.Errorf("invalid core URL")
    }
    if parsed.Scheme != "http" && parsed.Scheme != "https" { return "", fmt.Errorf("unsupported core URL scheme") }
    host := strings.ToLower(parsed.Hostname())
    loopback := host == "localhost" || host == "127.0.0.1" || host == "::1"
    internalService := !strings.Contains(host, ".") && !strings.Contains(host, ":") && host != "" && host != "localhost"
    if parsed.Scheme != "https" && !(parsed.Scheme == "http" && (loopback || internalService)) {
        return "", fmt.Errorf("clear-text HTTP is allowed only to loopback or a private service name")
    }
    return strings.TrimRight(parsed.String(), "/"), nil
}

func (s *Service) proxyCore(w http.ResponseWriter, r *http.Request, which string) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead && r.Method != http.MethodOptions { if !s.allowMutation(w, r) { return } }
	base := strings.TrimSpace(os.Getenv("GENESIS_BASE_URL")); path := r.URL.Path
	if which == "zero" { base = strings.TrimSpace(os.Getenv("USECT_ZERO_BASE_URL")); path = "/v1" + strings.TrimPrefix(path, "/v1/zero") }
	if base == "" { if which == "zero" { base = "http://127.0.0.1:8780" } else { base = "http://127.0.0.1:8781" } }
	base, err := normalizeCoreBase(base)
    if err != nil { writeAPIError(w, 502, "invalid_upstream", "Core upstream URL is invalid or violates the private-network policy."); return }
    u, err := url.Parse(base + path); if err != nil { writeAPIError(w, 502, "invalid_upstream", "Core upstream URL is invalid."); return }; u.RawQuery = r.URL.RawQuery
	upReq, err := http.NewRequestWithContext(r.Context(), r.Method, u.String(), r.Body); if err != nil { writeAPIError(w, 502, "upstream_request_failed", "Could not construct Core upstream request."); return }
	for _, header := range []string{"Accept", "Content-Type", "Authorization", "X-API-Key", "X-Admin-Token", "X-Genesis-Token"} { if value:=r.Header.Get(header);value!=""{upReq.Header.Set(header,value)} }
	client := &http.Client{Transport:&http.Transport{ResponseHeaderTimeout:8*time.Second}}; resp, err := client.Do(upReq); if err != nil { writeAPIError(w, 502, "upstream_unavailable", "Core upstream is unavailable; start the corresponding existing daemon."); return }; defer resp.Body.Close()
	for _,header:=range []string{"Content-Type","Cache-Control","ETag","Last-Modified"}{if value:=resp.Header.Get(header);value!=""{w.Header().Set(header,value)}};w.WriteHeader(resp.StatusCode);_,_=io.Copy(w,io.LimitReader(resp.Body,8<<20))
}

func (s *Service) serveStream(w http.ResponseWriter, r *http.Request) {
	flusher,ok:=w.(http.Flusher);if !ok{writeAPIError(w,500,"stream_unsupported","Server does not support streaming.");return};w.Header().Set("Content-Type","text/event-stream");w.Header().Set("Connection","keep-alive");w.Header().Set("X-Accel-Buffering","no");w.WriteHeader(200);flusher.Flush();ticker:=time.NewTicker(15*time.Second);defer ticker.Stop()
	emit:=func(){evolutions,_:=s.listEvolutions();if len(evolutions)>5{evolutions=evolutions[:5]};data:=map[string]any{"at":time.Now().UTC(),"integration":s.IntegrationStatus(),"recent_events":s.recentEvents(),"mirror":s.readMirrorSnapshot(),"learning":s.learningSummarySnapshot(),"recent_evolutions":evolutions,"model_free":true,"automatic_merge":false};b,_:=json.Marshal(data);_,_=fmt.Fprintf(w,"event: mind_snapshot\ndata: %s\n\n",b);flusher.Flush()};emit()
	for{select{case<-r.Context().Done():return;case<-ticker.C:emit()}}
}

func (s *Service) listEvolutions() ([]map[string]any,error){entries,err:=os.ReadDir(filepath.Join(s.CoreRoot,"evolutions"));if err!=nil{return nil,err};out:=[]map[string]any{};for _,e:=range entries{if !e.IsDir()||strings.HasPrefix(e.Name(),"."){continue};raw,er:=os.ReadFile(filepath.Join(s.CoreRoot,"evolutions",e.Name(),"evidence.json"));if er!=nil{continue};var obj map[string]any;if json.Unmarshal(raw,&obj)!=nil{continue};obj["version"]=e.Name();out=append(out,obj)};sort.Slice(out,func(i,j int)bool{return fmt.Sprint(out[i]["version"])>fmt.Sprint(out[j]["version"])});return out,nil}

func (s *Service) logBlocked(stage,input,reason string)error{path:=filepath.Join(s.CoreRoot,"guardian","blocked.log");if err:=os.MkdirAll(filepath.Dir(path),0o700);err!=nil{return err};entry:=map[string]any{"at":time.Now().UTC(),"stage":stage,"input_sha256":hashString(input),"reason":reason,"mutation_files_created":false};b,err:=json.Marshal(entry);if err!=nil{return err};f,err:=os.OpenFile(path,os.O_APPEND|os.O_CREATE|os.O_WRONLY,0o600);if err!=nil{return err};defer f.Close();_,err=f.Write(append(b,'\n'));return err}
func (s *Service) publish(event string,data map[string]any){s.mu.Lock();defer s.mu.Unlock();if s.events==nil{s.events=[]map[string]any{}};s.events=append(s.events,map[string]any{"event":event,"at":time.Now().UTC(),"data":data});if len(s.events)>100{s.events=append([]map[string]any(nil),s.events[len(s.events)-100:]...)}}

func(s *Service)readMirrorSnapshot()any{raw,err:=os.ReadFile(filepath.Join(s.CoreRoot,"metrics","mirror.json"));if err!=nil{return map[string]any{"status":"not_observed_yet"}};var value any;if json.Unmarshal(raw,&value)!=nil{return map[string]any{"status":"invalid_saved_snapshot"}};return value}
func(s *Service)learningSummarySnapshot()any{value,err:=s.learningSummary();if err!=nil{return map[string]any{"status":"unavailable"}};return value}


func decodeStrictAPIJSON(w http.ResponseWriter, r *http.Request, target any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil { return err }
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil { return errors.New("multiple JSON values are not allowed") }
		return err
	}
	return nil
}
