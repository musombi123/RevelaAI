package genesis

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func registryAPIRequest(server *Server, method, path, body string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	recorder := httptest.NewRecorder()
	server.ServeHTTP(recorder, req)
	return recorder
}

func setRegistryAPITestKeys(t *testing.T) {
	t.Helper()
	t.Setenv("GENESIS_REGISTRY_DIR", "")
	t.Setenv("GENESIS_ADMIN_TOKEN", "genesis-admin-test-token")
	t.Setenv("GENESIS_OWNER_APPROVAL_TOKEN", "genesis-owner-test-token")
	t.Setenv("GENESIS_ACTION_APPROVAL_TOKEN", "genesis-action-test-token")
	seed := []byte("01234567890123456789012345678901")
	t.Setenv("GENESIS_SIGNING_KEY", base64.StdEncoding.EncodeToString(seed))
}

func TestRegistryAPITierOneActivationRequiresSeparateOwnerCredential(t *testing.T) {
	setRegistryAPITestKeys(t)
	engine := newTestEngine(t)
	manifest := validManifestForTest()
	manifest.Permissions.Network = true
	manifest.RiskTier = 1
	record := publishTestArtifact(t, engine.CoreRoot, manifest, "package candidate\n// approved candidate\n", true)
	server := &Server{Engine: engine}
	path := "/v1/genesis/registry/tools/" + manifest.Name + "/" + manifest.Version + "/" + record.ArtifactHash + "/activate"
	body := `{"owner_approval_hash":"` + record.ArtifactHash + `"}`

	headers := map[string]string{"X-Genesis-Token": "genesis-admin-test-token"}
	denied := registryAPIRequest(server, http.MethodPost, path, body, headers)
	if denied.Code != http.StatusForbidden {
		t.Fatalf("activation without owner credential should be forbidden; got %d: %s", denied.Code, denied.Body.String())
	}
	if _, err := readActivePointer(filepath.Join(engine.CoreRoot, registryRootName), manifest.Name); err == nil {
		t.Fatal("Tier 1 artifact must not activate without owner approval")
	}

	headers["X-Genesis-Owner-Approval"] = "genesis-owner-test-token"
	allowed := registryAPIRequest(server, http.MethodPost, path, body, headers)
	if allowed.Code != http.StatusOK {
		t.Fatalf("activation with exact owner credential should succeed; got %d: %s", allowed.Code, allowed.Body.String())
	}
	pointer, err := readActivePointer(filepath.Join(engine.CoreRoot, registryRootName), manifest.Name)
	if err != nil {
		t.Fatal(err)
	}
	if !pointer.Active || pointer.ArtifactHash != record.ArtifactHash || pointer.OwnerApprovalHash != record.ArtifactHash {
		t.Fatalf("unexpected owner-approved active pointer: %#v", pointer)
	}
}

func TestRegistryAPITierTwoConfirmationRequiresActionCredentialAndMintsOneUseToken(t *testing.T) {
	setRegistryAPITestKeys(t)
	engine := newTestEngine(t)
	manifest := validManifestForTest()
	manifest.Permissions.Hardware = true
	manifest.RiskTier = 2
	record := publishTestArtifact(t, engine.CoreRoot, manifest, "package candidate\n// proposal only\n", true)
	if _, err := ActivateSignedToolVersion(engine.CoreRoot, manifest.Name, manifest.Version, record.ArtifactHash, record.ArtifactHash); err != nil {
		t.Fatal(err)
	}
	server := &Server{Engine: engine}
	path := "/v1/genesis/registry/tools/" + manifest.Name + "/" + manifest.Version + "/" + record.ArtifactHash + "/confirm"
	body := `{"arguments":{"action":"inspect","inputs":{"device":"pump-1"}}}`
	headers := map[string]string{"X-Genesis-Token": "genesis-admin-test-token"}

	denied := registryAPIRequest(server, http.MethodPost, path, body, headers)
	if denied.Code != http.StatusForbidden {
		t.Fatalf("confirmation without action credential should be forbidden; got %d: %s", denied.Code, denied.Body.String())
	}

	headers["X-Genesis-Action-Approval"] = "genesis-action-test-token"
	allowed := registryAPIRequest(server, http.MethodPost, path, body, headers)
	if allowed.Code != http.StatusCreated {
		t.Fatalf("valid confirmation should return 201; got %d: %s", allowed.Code, allowed.Body.String())
	}
	var result struct {
		ConfirmationToken string `json:"confirmation_token"`
		ArtifactHash string `json:"artifact_hash"`
	}
	if err := json.Unmarshal(allowed.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.ConfirmationToken) != 64 || result.ArtifactHash != record.ArtifactHash {
		t.Fatalf("confirmation token is not bound to the expected artifact: %#v", result)
	}
	input := []byte(`{"action":"inspect","inputs":{"device":"pump-1"}}`)
	if err := consumeToolActionConfirmation(result.ConfirmationToken, manifest.Name, manifest.Version, record.ArtifactHash, input); err != nil {
		t.Fatalf("exact confirmation should be consumable once: %v", err)
	}
	if err := consumeToolActionConfirmation(result.ConfirmationToken, manifest.Name, manifest.Version, record.ArtifactHash, input); err == nil {
		t.Fatal("confirmation token must be one-use")
	}
}
