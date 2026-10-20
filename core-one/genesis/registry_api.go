package genesis

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
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
				"signature": record.Signature, "sandbox_evidence": record.SandboxEvidence,
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
		ctx, cancel := context.WithTimeout(r.Context(), time.Duration(manifest.TimeoutMillis)*time.Millisecond)
		defer cancel()
		evidence, err := RunCandidateSandbox(ctx, candidateDir, candidateDir, manifest)
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
		pointer, err := RollbackSignedTool(s.Engine.CoreRoot, name, body.Version, body.ArtifactHash, body.OwnerApprovalHash)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "rollback_rejected", "Rollback target is not a verified signed version or its required approval is missing.")
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
		pointer, err := ActivateSignedToolVersion(s.Engine.CoreRoot, name, parts[1], parts[2], body.OwnerApprovalHash)
		if err != nil {
			writeAPIError(w, http.StatusForbidden, "activation_rejected", "Activation requires a verified signed artifact and hash-bound approval for Tier 1-2.")
			return
		}
		writeAPIJSON(w, http.StatusOK, map[string]any{"status": "active", "tool": pointer})
		return
	}

	writeAPIError(w, http.StatusNotFound, "not_found", "Registry route not found.")
}
