package genesis

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strconv"
	"path/filepath"
	"strings"
	"time"
)

func (s *Server) serveRegistry(w http.ResponseWriter, r *http.Request, path string) {
	if s == nil || s.Engine == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "genesis_unavailable", "Genesis engine is not initialized.")
		return
	}
	if path == "/v1/genesis/registry/tools" {
		if r.Method != http.MethodGet {
			methodNotAllowed(w, "GET")
			return
		}
		records, err := ListSignedToolArtifacts(s.Engine.CoreRoot)
		if err != nil {
			writeAPIError(w, http.StatusServiceUnavailable, "registry_unavailable", "Signed tool registry is unavailable or its signing key is not configured.")
			return
		}
		root, err := registryRoot(s.Engine.CoreRoot)
		if err != nil {
			writeAPIError(w, http.StatusServiceUnavailable, "registry_unavailable", "Signed tool registry is unavailable.")
			return
		}
		active := make(map[string]ActiveToolPointer)
		_ = filepath.WalkDir(filepath.Join(root, "active"), func(file string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil || entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
				return nil
			}
			raw, readErr := os.ReadFile(file)
			if readErr != nil {
				return nil
			}
			var pointer ActiveToolPointer
			if json.Unmarshal(raw, &pointer) == nil && pointer.Active {
				active[pointer.Name] = pointer
			}
			return nil
		})
		items := make([]map[string]any, 0, len(records))
		for _, record := range records {
			pointer := active[record.Name]
			items = append(items, map[string]any{
				"name": record.Name, "version": record.Version, "artifact_hash": record.ArtifactHash,
				"risk_tier": record.Manifest.RiskTier, "manifest": record.Manifest,
				"active": pointer.Active && pointer.ArtifactHash == record.ArtifactHash,
				"signature": record.Signature, "sandbox_evidence": map[string]any{"passed": record.SandboxEvidence.Passed, "isolation_level": record.SandboxEvidence.IsolationLevel, "finished_at": record.SandboxEvidence.FinishedAt, "error_class": record.SandboxEvidence.ErrorClass},
				"created_at": record.CreatedAt,
			})
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"tools": items, "count": len(items)})
		return
	}
	if !strings.HasPrefix(path, "/v1/genesis/registry/tools/") {
		writeAPIError(w, http.StatusNotFound, "not_found", "Route not found.")
		return
	}
	parts := strings.Split(strings.TrimPrefix(path, "/v1/genesis/registry/tools/"), "/")
	if len(parts) == 0 || !validResourceName(parts[0]) {
		writeAPIError(w, http.StatusBadRequest, "invalid_tool_name", "Invalid tool name.")
		return
	}
	name := parts[0]

	if len(parts) == 1 && r.Method == http.MethodGet {
		records, err := ListSignedToolArtifacts(s.Engine.CoreRoot)
		if err != nil {
			writeAPIError(w, http.StatusServiceUnavailable, "registry_unavailable", "Signed tool registry is unavailable.")
			return
		}
		filtered := make([]SignedToolArtifact, 0)
		for _, record := range records {
			if record.Name == name {
				filtered = append(filtered, record)
			}
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"name": name, "versions": filtered, "count": len(filtered)})
		return
	}

	if len(parts) == 2 && parts[1] == "publish" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		candidateDir := filepath.Join(s.Engine.CoreRoot, "inventions", name)
		manifestPath := filepath.Join(candidateDir, "tool_manifest.json")
		raw, err := readRegularFileLimited(manifestPath, 256*1024)
		if err != nil {
			writeAPIError(w, http.StatusNotFound, "tool_manifest_not_found", "The invention has no valid tool manifest.")
			return
		}
		manifest, err := DecodeToolManifest(raw)
		if err != nil || manifest.Name != name {
			writeAPIError(w, http.StatusUnprocessableEntity, "tool_manifest_invalid", "The invention tool manifest failed validation.")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), time.Duration(MaxToolTimeoutMillis)*time.Millisecond)
		defer cancel()
		evidence, err := RunCandidateSandbox(ctx, candidateDir, filepath.Join(s.Engine.CoreRoot, "state", "sandbox-evidence", name, manifest.Version), manifest)
		if err != nil {
			writeAPIJSON(w, http.StatusUnprocessableEntity, map[string]any{
				"status": "sandbox_failed", "tool": name, "evidence": evidence,
				"message": "Sandbox build/test did not pass; no signed artifact was published.",
			})
			return
		}
		record, err := PublishSignedToolArtifact(s.Engine.CoreRoot, candidateDir, manifest, evidence)
		if err != nil {
			writeAPIError(w, http.StatusServiceUnavailable, "registry_publish_failed", "The tested artifact could not be signed and published.")
			return
		}
		writeAPIJSON(w, http.StatusCreated, map[string]any{
			"status": "signed", "artifact": record,
			"auto_activated": manifest.RiskTier == 0,
			"human_approval_required": manifest.RiskTier > 0,
		})
		return
	}

	if len(parts) == 2 && parts[1] == "deactivate" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		pointer, err := DeactivateSignedTool(s.Engine.CoreRoot, name)
		if err != nil {
			writeAPIError(w, http.StatusNotFound, "active_tool_not_found", "No active registry pointer exists for this tool.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "deactivated", "tool": pointer})
		return
	}

	if len(parts) == 2 && parts[1] == "rollback" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		var body struct {
			Version string `json:"version"`
			ArtifactHash string `json:"artifact_hash"`
			OwnerApprovalHash string `json:"owner_approval_hash"`
		}
		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(w, http.StatusBadRequest, "invalid_json", "Rollback requires version and artifact_hash.")
			return
		}
		record, err := loadSignedToolArtifact(s.Engine.CoreRoot, name, body.Version, body.ArtifactHash)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "rollback_rejected", "Rollback target is not a verified signed version.")
			return
		}
		if record.Manifest.RiskTier > 0 && !genesisCredentialMatches("GENESIS_OWNER_APPROVAL_TOKEN", r.Header.Get("X-Genesis-Owner-Approval")) {
			writeAPIError(w, http.StatusForbidden, "owner_approval_required", "Tier 1-2 rollback requires a separate owner approval credential and hash-bound approval.")
			return
		}
		pointer, err := RollbackSignedTool(s.Engine.CoreRoot, name, body.Version, body.ArtifactHash, body.OwnerApprovalHash)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "rollback_rejected", "Rollback target or hash-bound approval was rejected.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "rolled_back", "tool": pointer})
		return
	}

	if len(parts) == 3 && r.Method == http.MethodGet {
		record, err := loadSignedToolArtifact(s.Engine.CoreRoot, name, parts[1], parts[2])
		if err != nil {
			writeAPIError(w, http.StatusNotFound, "signed_artifact_not_found", "Signed tool version or signature could not be verified.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"artifact": record})
		return
	}

	if len(parts) == 4 && parts[3] == "activate" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		var body struct { OwnerApprovalHash string `json:"owner_approval_hash"` }
		if err := decodeAPIJSON(w, r, &body); err != nil {
			writeAPIError(w, http.StatusBadRequest, "invalid_json", "Activation requires owner_approval_hash for Tier 1-2.")
			return
		}
		record, err := loadSignedToolArtifact(s.Engine.CoreRoot, name, parts[1], parts[2])
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "activation_rejected", "Activation requires a verified signed artifact.")
			return
		}
		if record.Manifest.RiskTier > 0 && !genesisCredentialMatches("GENESIS_OWNER_APPROVAL_TOKEN", r.Header.Get("X-Genesis-Owner-Approval")) {
			writeAPIError(w, http.StatusForbidden, "owner_approval_required", "Tier 1-2 activation requires a separate owner approval credential and hash-bound approval.")
			return
		}
		pointer, err := ActivateSignedToolVersion(s.Engine.CoreRoot, name, parts[1], parts[2], body.OwnerApprovalHash)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "activation_rejected", "Activation requires a verified signed artifact and hash-bound approval for Tier 1-2.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "active", "tool": pointer})
		return
	}

	if len(parts) == 4 && parts[3] == "confirm" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		if !genesisCredentialMatches("GENESIS_ACTION_APPROVAL_TOKEN", r.Header.Get("X-Genesis-Action-Approval")) {
			writeAPIError(w, http.StatusForbidden, "action_approval_required", "Tier 2 confirmation requires the separate human action-approval credential.")
			return
		}
		var body struct {
			Arguments map[string]any `json:"arguments"`
		}
		if err := decodeAPIJSON(w, r, &body); err != nil || body.Arguments == nil || !validGeneratedToolArguments(body.Arguments) {
			writeAPIError(w, http.StatusBadRequest, "invalid_tool_arguments", "Confirmation requires a valid action arguments object.")
			return
		}
		input, err := json.Marshal(body.Arguments)
		if err != nil || len(input) > 64*1024 {
			writeAPIError(w, http.StatusRequestEntityTooLarge, "tool_arguments_too_large", "Tool arguments exceed the permitted size.")
			return
		}
		token, expires, err := IssueToolActionConfirmation(s.Engine.CoreRoot, name, parts[1], parts[2], input)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "action_confirmation_rejected", "Genesis refused the action confirmation; the exact active Tier 2 artifact and owner approval are required.")
			return
		}
		writeAPIJSON(w, http.StatusCreated, map[string]any{
			"status": "confirmed", "confirmation_token": token, "expires_at": expires,
			"tool": name, "version": parts[1], "artifact_hash": parts[2],
		})
		return
	}

	if len(parts) == 4 && parts[3] == "invoke" && r.Method == http.MethodPost {
		if !s.allowMutation(w, r) {
			return
		}
		var body struct {
			Arguments map[string]any `json:"arguments"`
			ConfirmationToken string `json:"confirmation_token,omitempty"`
		}
		if err := decodeAPIJSON(w, r, &body); err != nil || body.Arguments == nil {
			writeAPIError(w, http.StatusBadRequest, "invalid_tool_arguments", "Invocation requires an arguments JSON object.")
			return
		}
		if !validGeneratedToolArguments(body.Arguments) {
			writeAPIError(w, http.StatusBadRequest, "invalid_tool_arguments", "Tool arguments do not match the generated runtime contract.")
			return
		}
		input, err := json.Marshal(body.Arguments)
		if err != nil || len(input) > 64*1024 {
			writeAPIError(w, http.StatusRequestEntityTooLarge, "tool_arguments_too_large", "Tool arguments exceed the permitted size.")
			return
		}
		started := time.Now()
		output, runErr := RunSignedToolInvocation(r.Context(), s.Engine.CoreRoot, name, parts[1], parts[2], input, body.ConfirmationToken)
		event := ToolCallTelemetry{
			At: time.Now().UTC(), Tool: name, VersionHash: parts[2],
			Success: runErr == nil, LatencyMS: time.Since(started).Milliseconds(),
			ErrorClass: normalizeToolErrorClass(runErr),
		}
		_ = appendToolCallTelemetry(s.Engine.CoreRoot, event)
		s.Engine.publish(Event{
			Type: "tool_call", At: event.At, Invention: name,
			Status: map[bool]string{true: "success", false: "failure"}[event.Success],
			Message: "Signed tool invocation telemetry recorded without user content.",
		})
		if runErr != nil {
			code := "tool_execution_failed"
			status := http.StatusUnprocessableEntity
			if strings.Contains(strings.ToLower(runErr.Error()), "confirmation") {
				code, status = "tier2_confirmation_required", http.StatusForbidden
			} else if strings.Contains(strings.ToLower(runErr.Error()), "active signed version") {
				code, status = "tool_not_active", http.StatusConflict
			} else if strings.Contains(strings.ToLower(runErr.Error()), "signature") || strings.Contains(strings.ToLower(runErr.Error()), "hash") {
				code, status = "artifact_verification_failed", http.StatusForbidden
			}
			writeAPIError(w, status, code, "Genesis refused or could not complete the sandboxed tool invocation.")
			return
		}
		var result any
		if json.Unmarshal(output, &result) != nil {
			writeAPIError(w, http.StatusBadGateway, "tool_output_invalid", "Sandboxed tool returned invalid JSON.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "success", "tool": name, "version": parts[1], "artifact_hash": parts[2], "result": result})
		return
	}

	writeAPIError(w, http.StatusNotFound, "not_found", "Registry route not found.")
}


func validGeneratedToolArguments(arguments map[string]any) bool {
	if len(arguments) == 0 || len(arguments) > 3 {
		return false
	}
	for key := range arguments {
		if key != "action" && key != "inputs" && key != "consent" {
			return false
		}
	}
	action, ok := arguments["action"].(string)
	if !ok || strings.TrimSpace(action) == "" || len(action) > 2000 {
		return false
	}
	if raw, exists := arguments["consent"]; exists {
		if _, ok := raw.(bool); !ok {
			return false
		}
	}
	if raw, exists := arguments["inputs"]; exists {
		inputs, ok := raw.(map[string]any)
		if !ok || len(inputs) > 100 {
			return false
		}
		for key, value := range inputs {
			text, ok := value.(string)
			if !ok || strings.TrimSpace(key) == "" || len(key) > 100 || len(text) > 4000 {
				return false
			}
		}
	}
	return true
}


func (s *Server) serveToolTelemetry(w http.ResponseWriter, r *http.Request) {
	if s == nil || s.Engine == nil {
		writeAPIError(w, http.StatusServiceUnavailable, "genesis_unavailable", "Genesis engine is not initialized.")
		return
	}
	if r.Method != http.MethodGet {
		methodNotAllowed(w, "GET")
		return
	}
	limit := 100
	if raw := strings.TrimSpace(r.URL.Query().Get("limit")); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > 500 {
			writeAPIError(w, http.StatusBadRequest, "invalid_limit", "limit must be between 1 and 500.")
			return
		}
		limit = parsed
	}
	events, err := listToolCallTelemetry(s.Engine.CoreRoot, limit)
	if err != nil {
		writeAPIError(w, http.StatusServiceUnavailable, "telemetry_unavailable", "Genesis tool telemetry is unavailable.")
		return
	}
	writeAPIJSON(w, http.StatusOK, map[string]any{"events": events, "count": len(events), "content_included": false})
}


func genesisCredentialMatches(environmentName, presented string) bool {
	configured := strings.TrimSpace(os.Getenv(environmentName))
	presented = strings.TrimSpace(presented)
	return configured != "" && presented != "" && constantTimeStringEqual(configured, presented)
}
