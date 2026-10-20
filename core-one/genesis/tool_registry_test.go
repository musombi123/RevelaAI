package genesis

import (
	"context"
	"encoding/base64"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func registryEvidenceForTest(t *testing.T, manifest ToolManifest, passed bool) SandboxEvidence {
	t.Helper()
	raw, err := json.Marshal(manifest)
	if err != nil { t.Fatal(err) }
	digest := sha256.Sum256(raw)
	return SandboxEvidence{
		ToolName: manifest.Name,
		ManifestHash: hex.EncodeToString(digest[:]),
		Passed: passed,
		IsolationLevel: "test-fixture_not_a_real_sandbox",
	}
}

func writeRegistryCandidate(t *testing.T, text string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "code.go"), []byte(text), 0o600); err != nil { t.Fatal(err) }
	if err := os.WriteFile(filepath.Join(dir, "library.go"), []byte("package candidate\n"), 0o600); err != nil { t.Fatal(err) }
	return dir
}

func TestFailedSandboxEvidenceCannotBeSigned(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
	coreRoot := t.TempDir()
	manifest := validManifestForTest()
	_, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n"), manifest, registryEvidenceForTest(t, manifest, false))
	if err == nil {
		t.Fatal("candidate with failing tests must never be signed")
	}
	records, err := ListSignedToolArtifacts(coreRoot)
	if err != nil { t.Fatal(err) }
	if len(records) != 0 { t.Fatalf("failed candidate unexpectedly signed: %#v", records) }
}

func TestApprovalForHashACannotActivateHashB(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
	coreRoot := t.TempDir()
	manifestA := validManifestForTest()
	manifestA.Permissions.Network = true
	manifestA.RiskTier = 1
	manifestB := manifestA
	manifestB.Version = "1.0.1"
	recordA, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n// version A\n"), manifestA, registryEvidenceForTest(t, manifestA, true))
	if err != nil { t.Fatal(err) }
	recordB, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n// version B\n"), manifestB, registryEvidenceForTest(t, manifestB, true))
	if err != nil { t.Fatal(err) }
	if _, err := ActivateSignedToolVersion(coreRoot, manifestB.Name, manifestB.Version, recordB.ArtifactHash, recordA.ArtifactHash); err == nil {
		t.Fatal("approval for hash A must not activate hash B")
	}
	pointer, err := ActivateSignedToolVersion(coreRoot, manifestA.Name, manifestA.Version, recordA.ArtifactHash, recordA.ArtifactHash)
	if err != nil { t.Fatal(err) }
	if !pointer.Active || pointer.ArtifactHash != recordA.ArtifactHash {
		t.Fatalf("expected hash A to activate: %#v", pointer)
	}
}

func TestRollbackRestoresPreviousSignedVersion(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
	coreRoot := t.TempDir()
	manifestA := validManifestForTest()
	recordA, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n// version A\n"), manifestA, registryEvidenceForTest(t, manifestA, true))
	if err != nil { t.Fatal(err) }
	manifestB := manifestA
	manifestB.Version = "1.0.1"
	recordB, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n// version B\n"), manifestB, registryEvidenceForTest(t, manifestB, true))
	if err != nil { t.Fatal(err) }
	current, err := readActivePointer(filepath.Join(coreRoot, registryRootName), manifestA.Name)
	if err != nil { t.Fatal(err) }
	if current.ArtifactHash != recordB.ArtifactHash { t.Fatalf("new Tier 0 version should be active: %#v", current) }
	restored, err := RollbackSignedTool(coreRoot, manifestA.Name, manifestA.Version, recordA.ArtifactHash, "")
	if err != nil { t.Fatal(err) }
	if restored.ArtifactHash != recordA.ArtifactHash || !restored.Active {
		t.Fatalf("rollback did not restore prior signed version: %#v", restored)
	}
}

func TestTierTwoInvocationRequiresHashBoundPerActionConfirmation(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
	coreRoot := t.TempDir()
	manifest := validManifestForTest()
	manifest.Permissions.Hardware = true
	manifest.RiskTier = 2
	record, err := PublishSignedToolArtifact(coreRoot, writeRegistryCandidate(t, "package candidate\n"), manifest, registryEvidenceForTest(t, manifest, true))
	if err != nil { t.Fatal(err) }
	if _, err := ActivateSignedToolVersion(coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, record.ArtifactHash); err != nil { t.Fatal(err) }
	_, err = RunSignedToolInvocation(context.Background(), coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, []byte(`{"action":"plan"}`), "")
	if err == nil {
		t.Fatal("Tier 2 tool invocation must be refused without per-action confirmation")
	}
}
