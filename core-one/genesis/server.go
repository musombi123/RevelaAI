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
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"revela-genesis.local/core-one/endpoint"
	"revela-genesis.local/core-one/rvx"
)

const (
	maxAPIRequestBytes  = 1 << 20
	maxAPIEvidenceBytes = 4 << 20
	maxAPIPlanBytes     = 4 << 20
	maxAPIKeyBytes      = 16 * 1024
	maxAPIEventType     = 80
	maxAPIToolName      = 64
	maxAPIListItems     = 10000
)

type Server struct {
	Engine *Engine
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	setAPIHeaders(w)

	if r == nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_request", "Invalid HTTP request.")
		return
	}

	if r.Method == http.MethodOptions {
		w.Header().Set("Allow", "GET, POST, OPTIONS")
		w.WriteHeader(http.StatusNoContent)
		return
	}

	if r.URL == nil || !utf8.ValidString(r.URL.Path) {
		writeAPIError(w, http.StatusBadRequest, "invalid_path", "Invalid request path.")
		return
	}

	path := strings.TrimRight(r.URL.Path, "/")
	if path == "" {
		path = "/"
	}

	// Health remains a public, read-only endpoint. Other remote requests
	// require an explicitly configured, valid Genesis admin token.
	if !remoteIsLoopback(r.RemoteAddr) &&
		path != "/v1/genesis/health" &&
		!s.authorized(r) {
		writeAPIError(
			w,
			http.StatusUnauthorized,
			"genesis_auth_required",
			"Remote requests require the configured Genesis token.",
		)
		return
	}

	// Health can report basic liveness even if the engine was not initialized.
	if path == "/v1/genesis/health" && r.Method == http.MethodGet {
		writeAPIJSON(w, http.StatusOK, map[string]any{
			"status":         "ok",
			"version":        Version,
			"standalone":     true,
			"model_assisted": strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL")) != "",
			"execution":      "proposal_only",
			"merge":          "human_required",
		})
		return
	}

	if s == nil || s.Engine == nil {
		writeAPIError(
			w,
			http.StatusServiceUnavailable,
			"genesis_unavailable",
			"Genesis engine is not initialized.",
		)
		return
	}

	switch {
	case path == "/v1/genesis/health":
		methodNotAllowed(w, "GET")

	case path == "/v1/genesis/status" && r.Method == http.MethodGet:
		status, err := s.Engine.OperationalStatus()
		if err != nil {
			writeAPIError(
				w,
				http.StatusInternalServerError,
				"status_unavailable",
				"Could not assemble operational status.",
			)
			return
		}
		writeAPIJSON(w, http.StatusOK, status)

	case path == "/v1/genesis/status":
		methodNotAllowed(w, "GET")

	case path == "/v1/genesis/invent" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) {
			return
		}

		var body struct {
			Demand   string `json:"demand"`
			Country  string `json:"country,omitempty"`
			Language string `json:"language,omitempty"`
		}

		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_json",
				"Request must contain a valid JSON object with demand.",
			)
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), 35*time.Second)
		defer cancel()

		profile, profileErr := endpoint.ResolveWorldContext(
			r,
			body.Country,
			body.Language,
		)
		if profileErr != nil {
			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_country",
				"Country or language context is invalid.",
			)
			return
		}

		inv, err := s.Engine.InventWorldwide(
			ctx,
			body.Demand,
			profile.Code,
			profile.Language,
		)
		if err != nil {
			switch {
			case errors.Is(err, ErrBlocked):
				writeAPIError(
					w,
					http.StatusForbidden,
					"guardian_block",
					"Guardian blocked the demand; no invention package was created.",
				)
			case errors.Is(err, ErrAlreadyExists):
				writeAPIError(
					w,
					http.StatusConflict,
					"already_exists",
					"The invention already exists.",
				)
			case errors.Is(err, context.Canceled),
				errors.Is(err, context.DeadlineExceeded):
				writeAPIError(
					w,
					http.StatusRequestTimeout,
					"invention_timeout",
					"The invention request was cancelled or exceeded its time limit.",
				)
			default:
				writeAPIError(
					w,
					http.StatusUnprocessableEntity,
					"invention_failed",
					"The invention request could not be completed.",
				)
			}
			return
		}

		writeAPIJSON(w, http.StatusCreated, inv)

	case path == "/v1/genesis/invent":
		methodNotAllowed(w, "POST")

	case path == "/v1/genesis/queue" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) {
			return
		}

		var body struct {
			Demand   string `json:"demand"`
			Source   string `json:"source,omitempty"`
			Country  string `json:"country,omitempty"`
			Language string `json:"language,omitempty"`
		}

		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_json",
				"Request must contain a valid JSON object with demand.",
			)
			return
		}

		profile, profileErr := endpoint.ResolveWorldContext(
			r,
			body.Country,
			body.Language,
		)
		if profileErr != nil {
			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_country",
				"Country or language context is invalid.",
			)
			return
		}

		item, err := s.Engine.EnqueueWorldwide(
			body.Demand,
			body.Source,
			profile.Code,
			profile.Language,
		)
		if err != nil {
			if errors.Is(err, ErrBlocked) {
				writeAPIError(
					w,
					http.StatusForbidden,
					"guardian_block",
					"Guardian blocked the demand before queueing.",
				)
				return
			}

			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_demand",
				"The demand could not be accepted into the local queue.",
			)
			return
		}

		s.Engine.publish(Event{
			Type:    "demand_queued",
			At:      time.Now().UTC(),
			Message: "Demand accepted into the local queue for the next daemon cycle.",
			Status:  "queued",
		})

		writeAPIJSON(w, http.StatusAccepted, map[string]any{
			"status":    "queued",
			"demand_id": item.ID,
			"next_scan": "within the configured daemon interval",
		})

	case path == "/v1/genesis/queue":
		methodNotAllowed(w, "POST")

	case path == "/v1/genesis/tools" && r.Method == http.MethodGet:
		items, err := s.Engine.ListInventions()
		if err != nil {
			writeAPIError(
				w,
				http.StatusInternalServerError,
				"tools_unavailable",
				"Could not list invention proposals.",
			)
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{
			"tools": items,
			"count": len(items),
		})

	case path == "/v1/genesis/tools":
		methodNotAllowed(w, "GET")

	case strings.HasPrefix(path, "/v1/genesis/tools/"):
		if r.Method != http.MethodGet {
			methodNotAllowed(w, "GET")
			return
		}
		s.serveTool(w, r, strings.TrimPrefix(path, "/v1/genesis/tools/"))

	case path == "/v1/genesis/stream" && r.Method == http.MethodGet:
		s.serveStream(w, r)

	case path == "/v1/genesis/stream":
		methodNotAllowed(w, "GET")

	case path == "/v1/genesis/key" &&
		(r.Method == http.MethodPost || r.Method == http.MethodGet):
		if r.Method == http.MethodPost {
			if !s.allowMutation(w, r) {
				return
			}
			s.requestProviderKey(w, r)
			return
		}

		writeAPIJSON(w, http.StatusOK, map[string]any{
			"status": "request_required",
			"message": "Genesis does not disclose or mint bearer secrets through this endpoint. " +
				"POST a request for human approval, or configure standalone mode.",
		})

	case path == "/v1/genesis/key":
		methodNotAllowed(w, "GET, POST")

	case path == "/v1/genesis/registry/tools" || strings.HasPrefix(path, "/v1/genesis/registry/tools/"):
		s.serveRegistry(w, r, path)

	case path == "/v1/rvx/compile" && r.Method == http.MethodPost:
		if !s.allowMutation(w, r) {
			return
		}

		var body struct {
			Source string `json:"source"`
		}

		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(
				w,
				http.StatusBadRequest,
				"invalid_json",
				"Request must contain source text.",
			)
			return
		}

		compiled, err := rvx.Compile(body.Source)
		if err != nil {
			writeAPIError(
				w,
				http.StatusUnprocessableEntity,
				"rvx_compile_error",
				"The supplied RVX source could not be compiled.",
			)
			return
		}
		writeAPIJSON(w, http.StatusOK, compiled)

	case path == "/v1/rvx/compile":
		methodNotAllowed(w, "POST")

	default:
		writeAPIError(
			w,
			http.StatusNotFound,
			"not_found",
			"Route not found.",
		)
	}
}

func setAPIHeaders(w http.ResponseWriter) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Pragma", "no-cache")
}

func methodNotAllowed(w http.ResponseWriter, allowed string) {
	w.Header().Set("Allow", allowed)
	writeAPIError(
		w,
		http.StatusMethodNotAllowed,
		"method_not_allowed",
		"The HTTP method is not supported for this route.",
	)
}

func (s *Server) authorized(r *http.Request) bool {
	if r == nil {
		return false
	}

	configured := strings.TrimSpace(os.Getenv("GENESIS_ADMIN_TOKEN"))
	if configured == "" || len(configured) > maxAPIKeyBytes {
		return false
	}

	given := strings.TrimSpace(r.Header.Get("X-Genesis-Token"))
	if given == "" {
		auth := strings.TrimSpace(r.Header.Get("Authorization"))
		if strings.HasPrefix(auth, "Bearer ") {
			given = strings.TrimSpace(strings.TrimPrefix(auth, "Bearer "))
		}
	}

	if given == "" || len(given) > maxAPIKeyBytes {
		return false
	}

	return len(given) == len(configured) &&
		subtle.ConstantTimeCompare([]byte(given), []byte(configured)) == 1
}

func (s *Server) allowMutation(w http.ResponseWriter, r *http.Request) bool {
	if s != nil && s.authorized(r) {
		return true
	}

	tokenConfigured := strings.TrimSpace(os.Getenv("GENESIS_ADMIN_TOKEN")) != ""
	if !tokenConfigured && r != nil && remoteIsLoopback(r.RemoteAddr) {
		return true
	}

	writeAPIError(
		w,
		http.StatusUnauthorized,
		"genesis_auth_required",
		"Supply a valid X-Genesis-Token or Bearer token. Without a configured token, mutations are permitted only over loopback.",
	)
	return false
}

func remoteIsLoopback(remote string) bool {
	remote = strings.TrimSpace(remote)
	if remote == "" {
		return false
	}

	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		host = remote
	}

	host = strings.Trim(host, "[]")
	if strings.EqualFold(host, "localhost") {
		return true
	}

	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (s *Server) serveTool(w http.ResponseWriter, r *http.Request, part string) {
	if s == nil || s.Engine == nil {
		writeAPIError(
			w,
			http.StatusServiceUnavailable,
			"genesis_unavailable",
			"Genesis engine is not initialized.",
		)
		return
	}

	parts := strings.Split(part, "/")
	if len(parts) == 0 ||
		!validResourceName(parts[0]) ||
		len(parts[0]) > maxAPIToolName {
		writeAPIError(
			w,
			http.StatusBadRequest,
			"invalid_tool_name",
			"Invalid tool name.",
		)
		return
	}

	name := parts[0]
	dir := filepath.Join(s.Engine.CoreRoot, "inventions", name)

	if len(parts) == 2 && parts[1] == "hardware_guide" {
		guide, profile, err := s.Engine.WorldwideHardwareGuide(
			name,
			r.URL.Query().Get("country"),
			r.URL.Query().Get("lang"),
		)
		if err != nil {
			writeAPIError(
				w,
				http.StatusNotFound,
				"tool_not_found",
				"Guide or country profile unavailable.",
			)
			return
		}

		writeAPIJSON(w, http.StatusOK, map[string]any{
			"name":            name,
			"status":          "await_merge",
			"country_context": profile,
			"hardware_guide":  guide,
		})
		return
	}

	if len(parts) == 2 && parts[1] == "capability_plan" {
		raw, err := readRegularFileLimited(
			filepath.Join(dir, "capability_plan.json"),
			maxAPIPlanBytes,
		)
		if err != nil {
			writeAPIError(
				w,
				http.StatusNotFound,
				"capability_plan_not_found",
				"Tool or capability plan not found.",
			)
			return
		}

		var plan CapabilityPlan
		if err := json.Unmarshal(raw, &plan); err != nil {
			writeAPIError(
				w,
				http.StatusInternalServerError,
				"capability_plan_invalid",
				"Saved capability plan could not be parsed.",
			)
			return
		}

		writeAPIJSON(w, http.StatusOK, map[string]any{
			"name":            name,
			"status":          "await_merge",
			"capability_plan": plan,
		})
		return
	}

	if len(parts) != 1 {
		writeAPIError(w, http.StatusNotFound, "not_found", "Route not found.")
		return
	}

	raw, err := readRegularFileLimited(
		filepath.Join(dir, "evidence.json"),
		maxAPIEvidenceBytes,
	)
	if err != nil {
		writeAPIError(
			w,
			http.StatusNotFound,
			"tool_not_found",
			"Tool proposal not found.",
		)
		return
	}

	var record map[string]any
	if err := json.Unmarshal(raw, &record); err != nil {
		writeAPIError(
			w,
			http.StatusInternalServerError,
			"proposal_invalid",
			"Saved proposal evidence could not be parsed.",
		)
		return
	}

	writeAPIJSON(w, http.StatusOK, map[string]any{
		"name":   name,
		"status": "await_merge",
		"proposal": record,
		"hardware_guide_url": "/v1/genesis/tools/" +
			name + "/hardware_guide",
	})
}

func (s *Server) serveStream(w http.ResponseWriter, r *http.Request) {
	if s == nil || s.Engine == nil {
		writeAPIError(
			w,
			http.StatusServiceUnavailable,
			"genesis_unavailable",
			"Genesis engine is not initialized.",
		)
		return
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeAPIError(
			w,
			http.StatusInternalServerError,
			"stream_unsupported",
			"Server does not support event streaming.",
		)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set("Cache-Control", "no-store")

	controller := http.NewResponseController(w)
	_ = controller.SetWriteDeadline(time.Time{})

	ch, cancel := s.Engine.Subscribe()
	defer cancel()

	heartbeat := time.NewTicker(20 * time.Second)
	defer heartbeat.Stop()

	w.WriteHeader(http.StatusOK)

	if _, err := io.WriteString(w, ": genesis stream connected\n\n"); err != nil {
		return
	}
	flusher.Flush()

	for {
		select {
		case <-r.Context().Done():
			return

		case event, open := <-ch:
			if !open {
				return
			}

			payload, err := json.Marshal(event)
			if err != nil {
				continue
			}

			eventType := safeSSEEventType(event.Type)
			if _, err := io.WriteString(
				w,
				"event: "+eventType+"\ndata: "+string(payload)+"\n\n",
			); err != nil {
				return
			}
			flusher.Flush()

		case <-heartbeat.C:
			if _, err := io.WriteString(w, ": heartbeat\n\n"); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func safeSSEEventType(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" || len(raw) > maxAPIEventType {
		return "message"
	}

	for _, r := range raw {
		if !(r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			r == '_' || r == '-' || r == '.') {
			return "message"
		}
	}

	return raw
}

func (s *Server) requestProviderKey(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ClientID string `json:"client_id"`
		Reason   string `json:"reason"`
	}

	if err := decodeAPIJSON(w, r, &body); err != nil {
		writeAPIError(
			w,
			http.StatusBadRequest,
			"invalid_json",
			"Request must contain client_id and reason.",
		)
		return
	}

	clientID, ok := normalizeAPIField(body.ClientID, 120)
	if !ok {
		writeAPIError(
			w,
			http.StatusBadRequest,
			"invalid_client_id",
			"client_id is empty or invalid.",
		)
		return
	}

	reason, ok := normalizeAPIField(body.Reason, 500)
	if !ok {
		writeAPIError(
			w,
			http.StatusBadRequest,
			"invalid_reason",
			"reason is empty or invalid.",
		)
		return
	}

	id := newID("provider_request")
	req := map[string]any{
		"id":         id,
		"client_id":  clientID,
		"reason":     reason,
		"created_at": time.Now().UTC(),
		"status":     "pending_approval",
		"note":       "No secret was issued by this request.",
	}

	dir := filepath.Join(s.Engine.CoreRoot, "state", "key_requests")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		writeAPIError(
			w,
			http.StatusInternalServerError,
			"key_request_failed",
			"Could not save provider key request.",
		)
		return
	}

	info, err := os.Lstat(dir)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		writeAPIError(
			w,
			http.StatusInternalServerError,
			"key_request_storage_invalid",
			"Provider key request storage is unavailable.",
		)
		return
	}

	if err := writeJSON(filepath.Join(dir, id+".json"), req); err != nil {
		writeAPIError(
			w,
			http.StatusInternalServerError,
			"key_request_failed",
			"Could not save provider key request.",
		)
		return
	}

	writeAPIJSON(w, http.StatusAccepted, req)
}

func (e *Engine) ListInventions() ([]map[string]any, error) {
	if e == nil || strings.TrimSpace(e.CoreRoot) == "" {
		return nil, errors.New("engine core root is not configured")
	}

	root := filepath.Join(e.CoreRoot, "inventions")
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	if len(entries) > maxAPIListItems {
		return nil, errors.New("invention directory exceeds the safe item limit")
	}

	out := make([]map[string]any, 0, len(entries))

	for _, item := range entries {
		if !item.IsDir() ||
			strings.HasPrefix(item.Name(), ".staging-") ||
			!validResourceName(item.Name()) {
			continue
		}

		dirPath := filepath.Join(root, item.Name())
		dirInfo, err := os.Lstat(dirPath)
		if err != nil || dirInfo.Mode()&os.ModeSymlink != 0 || !dirInfo.IsDir() {
			continue
		}

		raw, err := readRegularFileLimited(
			filepath.Join(dirPath, "evidence.json"),
			maxAPIEvidenceBytes,
		)
		if err != nil {
			continue
		}

		var rec struct {
			ID        string    `json:"invention_id"`
			CreatedAt time.Time `json:"created_at"`
			Status    string    `json:"status"`
			Spec      ToolSpec  `json:"specification"`
		}
		if json.Unmarshal(raw, &rec) != nil {
			continue
		}

		capabilitySummary := map[string]any{
			"url": "/v1/genesis/tools/" + item.Name() + "/capability_plan",
		}

		if planBytes, err := readRegularFileLimited(
			filepath.Join(dirPath, "capability_plan.json"),
			maxAPIPlanBytes,
		); err == nil {
			var plan CapabilityPlan
			if json.Unmarshal(planBytes, &plan) == nil {
				capabilitySummary["status"] = plan.Status
				capabilitySummary["coverage"] = plan.Coverage
				capabilitySummary["unresolved"] = plan.MissingCapabilities
			}
		}

		out = append(out, map[string]any{
			"id":              rec.ID,
			"name":            item.Name(),
			"title":           rec.Spec.Title,
			"category":        rec.Spec.Category,
			"industry":        rec.Spec.Industry,
			"status":          "await_merge",
			"created_at":      rec.CreatedAt,
			"capability_plan": capabilitySummary,
		})
	}

	sort.Slice(out, func(i, j int) bool {
		left, _ := out[i]["created_at"].(time.Time)
		right, _ := out[j]["created_at"].(time.Time)
		return left.After(right)
	})

	return out, nil
}

func (e *Engine) OperationalStatus() (map[string]any, error) {
	if e == nil || strings.TrimSpace(e.CoreRoot) == "" {
		return nil, errors.New("engine core root is not configured")
	}

	inventions, err := e.ListInventions()
	if err != nil {
		return nil, err
	}

	queueCounts := map[string]int{}

	for _, state := range []string{
		"pending",
		"processing",
		"await_merge",
		"blocked",
		"failed",
	} {
		dir := filepath.Join(e.CoreRoot, "state", "queue", state)

		dirInfo, statErr := os.Lstat(dir)
		if os.IsNotExist(statErr) {
			queueCounts[state] = 0
			continue
		}
		if statErr != nil {
			return nil, statErr
		}
		if dirInfo.Mode()&os.ModeSymlink != 0 || !dirInfo.IsDir() {
			return nil, errors.New("queue state path is not a regular directory")
		}

		entries, err := os.ReadDir(dir)
		if err != nil {
			return nil, err
		}
		if len(entries) > maxAPIListItems {
			return nil, errors.New("queue state exceeds the safe item limit")
		}

		for _, entry := range entries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
				continue
			}

			info, err := os.Lstat(filepath.Join(dir, entry.Name()))
			if err == nil &&
				info.Mode().IsRegular() &&
				info.Mode()&os.ModeSymlink == 0 {
				queueCounts[state]++
			}
		}
	}

	latestResearch := ""
	var latestResearchTime time.Time

	researchDir := filepath.Join(e.CoreRoot, "research")
	researchEntries, err := os.ReadDir(researchDir)
	if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	if err == nil {
		for _, entry := range researchEntries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
				continue
			}

			path := filepath.Join(researchDir, entry.Name())
			info, err := os.Lstat(path)
			if err != nil ||
				!info.Mode().IsRegular() ||
				info.Mode()&os.ModeSymlink != 0 {
				continue
			}

			if info.ModTime().After(latestResearchTime) {
				latestResearchTime = info.ModTime()
				latestResearch = entry.Name()
			}
		}
	}

	guardianReady, guardianReason := e.Guardian.policyReady()

	blockedLog := filepath.Join(e.CoreRoot, "guardian", "blocked.log")
	var blockedLogUpdated any

	if info, err := os.Lstat(blockedLog); err == nil &&
		info.Mode().IsRegular() &&
		info.Mode()&os.ModeSymlink == 0 {
		blockedLogUpdated = info.ModTime().UTC()
	}

	return map[string]any{
		"status":          "ok",
		"version":         Version,
		"standalone":      true,
		"model_assisted":  strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL")) != "",
		"offline_mode":    strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "1") || strings.EqualFold(os.Getenv("GENESIS_OFFLINE"), "true"),
		"guardian": map[string]any{
			"ready":                  guardianReady,
			"reason":                 guardianReason,
			"blocked_log_updated_at": blockedLogUpdated,
		},
		"queue":                   queueCounts,
		"invention_count":         len(inventions),
		"latest_research_file":    latestResearch,
		"generated_code_execution": false,
		"automatic_merge":          false,
	}, nil
}

// decodeAPIJSON limits incoming data, rejects unknown fields, and accepts
// exactly one JSON value. All API mutation handlers use this shared decoder.
func decodeAPIJSON(w http.ResponseWriter, r *http.Request, out any) error {
	if r == nil || r.Body == nil {
		return errors.New("request body is missing")
	}

	defer r.Body.Close()

	decoder := json.NewDecoder(http.MaxBytesReader(
		w,
		r.Body,
		maxAPIRequestBytes,
	))
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(out); err != nil {
		return err
	}

	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return errors.New("request body must contain exactly one JSON value")
		}
		return err
	}

	return nil
}

func readRegularFileLimited(path string, limit int64) ([]byte, error) {
	if limit <= 0 {
		return nil, errors.New("invalid file size limit")
	}

	before, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if before.Mode()&os.ModeSymlink != 0 || !before.Mode().IsRegular() {
		return nil, errors.New("expected a regular non-symlink file")
	}
	if before.Size() < 0 || before.Size() > limit {
		return nil, errors.New("file exceeds the permitted size")
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	opened, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !opened.Mode().IsRegular() || !os.SameFile(before, opened) {
		return nil, errors.New("file changed while being opened")
	}

	raw, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, errors.New("file exceeds the permitted size")
	}

	return raw, nil
}

func normalizeAPIField(raw string, maxBytes int) (string, bool) {
	if !utf8.ValidString(raw) {
		return "", false
	}

	raw = strings.TrimSpace(raw)
	if raw == "" || maxBytes <= 0 {
		return "", false
	}

	for _, r := range raw {
		if unicode.IsControl(r) && !unicode.IsSpace(r) {
			return "", false
		}
	}

	raw = strings.Join(strings.Fields(raw), " ")
	if raw == "" {
		return "", false
	}

	if len(raw) > maxBytes {
		raw = limitText(raw, maxBytes)
		raw = strings.TrimSpace(raw)
	}

	return raw, raw != ""
}

func writeAPIJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeAPIError(w http.ResponseWriter, status int, code, message string) {
	writeAPIJSON(w, status, map[string]string{
		"status":  "error",
		"code":    code,
		"message": message,
	})
}

func validResourceName(name string) bool {
	if name == "" ||
		len(name) > 64 ||
		name == "." ||
		name == ".." {
		return false
	}

	for _, r := range name {
		if !(r >= 'a' && r <= 'z' ||
			r >= '0' && r <= '9' ||
			r == '_' ||
			r == '-') {
			return false
		}
	}

	return true
}
