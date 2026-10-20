package genesis

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func registryTestRoot(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	// Published artifact trees are deliberately read-only in production. Make
	// the test fixture writable before testing.T removes its temporary root.
	t.Cleanup(func() { _ = makeTreeWritable(root) })
	return root
}

func testSigningKey(t *testing.T) {
	t.Helper()
	seed := []byte("01234567890123456789012345678901")
	t.Setenv("GENESIS_SIGNING_KEY", base64.StdEncoding.EncodeToString(seed))
}

func registryEvidenceForTest(t *testing.T, manifest ToolManifest, passed bool, candidateDir string) SandboxEvidence {
	t.Helper()
	raw, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(raw)
	candidateHash, err := hashArtifactTree(candidateDir)
	if err != nil {
		t.Fatal(err)
	}
	return SandboxEvidence{
		ToolName:       manifest.Name,
		CandidateHash:  candidateHash,
		ManifestHash:   hex.EncodeToString(digest[:]),
		Passed:         passed,
		IsolationLevel: "test-fixture_not_a_real_sandbox",
	}
}

func writeRegistryCandidate(t *testing.T, text string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "code.go"), []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "library.go"), []byte("package candidate\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return dir
}

func publishTestArtifact(t *testing.T, coreRoot string, manifest ToolManifest, source string, passing bool) SignedToolArtifact {
	t.Helper()
	candidate := writeRegistryCandidate(t, source)
	record, err := PublishSignedToolArtifact(
		coreRoot,
		candidate,
		manifest,
		registryEvidenceForTest(t, manifest, passing, candidate),
	)
	if err != nil {
		t.Fatal(err)
	}
	return record
}

func TestFailedSandboxEvidenceCannotBeSigned(t *testing.T) {
	testSigningKey(t)
	coreRoot := registryTestRoot(t)
	manifest := validManifestForTest()
	candidate := writeRegistryCandidate(t, "package candidate\n")
	_, err := PublishSignedToolArtifact(
		coreRoot, candidate, manifest,
		registryEvidenceForTest(t, manifest, false, candidate),
	)
	if err == nil {
		t.Fatal("candidate with failing tests must never be signed")
	}
	records, err := ListSignedToolArtifacts(coreRoot)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 0 {
		t.Fatalf("failed candidate unexpectedly signed: %#v", records)
	}
}

func TestApprovalForHashACannotActivateHashB(t *testing.T) {
	testSigningKey(t)
	coreRoot := registryTestRoot(t)
	manifestA := validManifestForTest()
	manifestA.Permissions.Network = true
	manifestA.RiskTier = 1
	recordA := publishTestArtifact(t, coreRoot, manifestA, "package candidate\n// version A\n", true)

	manifestB := manifestA
	manifestB.Version = "1.0.1"
	recordB := publishTestArtifact(t, coreRoot, manifestB, "package candidate\n// version B\n", true)

	if _, err := ActivateSignedToolVersion(coreRoot, manifestB.Name, manifestB.Version, recordB.ArtifactHash, recordA.ArtifactHash); err == nil {
		t.Fatal("approval for hash A must not activate hash B")
	}
	pointer, err := ActivateSignedToolVersion(coreRoot, manifestA.Name, manifestA.Version, recordA.ArtifactHash, recordA.ArtifactHash)
	if err != nil {
		t.Fatal(err)
	}
	if !pointer.Active || pointer.ArtifactHash != recordA.ArtifactHash {
		t.Fatalf("expected hash A to activate: %#v", pointer)
	}
}

func TestRollbackRestoresPreviousSignedVersion(t *testing.T) {
	testSigningKey(t)
	coreRoot := registryTestRoot(t)
	manifestA := validManifestForTest()
	recordA := publishTestArtifact(t, coreRoot, manifestA, "package candidate\n// version A\n", true)

	manifestB := manifestA
	manifestB.Version = "1.0.1"
	recordB := publishTestArtifact(t, coreRoot, manifestB, "package candidate\n// version B\n", true)

	current, err := readActivePointer(filepath.Join(coreRoot, registryRootName), manifestA.Name)
	if err != nil {
		t.Fatal(err)
	}
	if current.ArtifactHash != recordB.ArtifactHash {
		t.Fatalf("new Tier 0 version should be active: %#v", current)
	}
	restored, err := RollbackSignedTool(coreRoot, manifestA.Name, manifestA.Version, recordA.ArtifactHash, "")
	if err != nil {
		t.Fatal(err)
	}
	if restored.ArtifactHash != recordA.ArtifactHash || !restored.Active {
		t.Fatalf("rollback did not restore prior signed version: %#v", restored)
	}
}

func TestTierTwoInvocationRequiresHashBoundPerActionConfirmation(t *testing.T) {
	testSigningKey(t)
	coreRoot := registryTestRoot(t)
	manifest := validManifestForTest()
	manifest.Permissions.Hardware = true
	manifest.RiskTier = 2
	record := publishTestArtifact(t, coreRoot, manifest, "package candidate\n", true)
	if _, err := ActivateSignedToolVersion(coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, record.ArtifactHash); err != nil {
		t.Fatal(err)
	}
	_, err := RunSignedToolInvocation(context.Background(), coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, []byte("{\"action\":\"plan\"}"), "")
	if err == nil {
		t.Fatal("Tier 2 tool invocation must be refused without per-action confirmation")
	}
}

func TestTierTwoConfirmationIsBoundToExactArgumentsAndConsumedOnce(t *testing.T) {
	testSigningKey(t)
	coreRoot := registryTestRoot(t)
	manifest := validManifestForTest()
	manifest.Permissions.Hardware = true
	manifest.RiskTier = 2
	record := publishTestArtifact(t, coreRoot, manifest, "package candidate\n", true)
	if _, err := ActivateSignedToolVersion(coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, record.ArtifactHash); err != nil {
		t.Fatal(err)
	}

	input := []byte("{\"action\":\"switch\",\"inputs\":{\"device\":\"pump-1\"}}")
	token, expires, err := IssueToolActionConfirmation(coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, input)
	if err != nil {
		t.Fatal(err)
	}
	if !expires.After(time.Now()) {
		t.Fatal("confirmation token expiry must be in the future")
	}
	changedInput := []byte("{\"action\":\"switch\",\"inputs\":{\"device\":\"pump-2\"}}")
	if err := consumeToolActionConfirmation(token, manifest.Name, manifest.Version, record.ArtifactHash, changedInput); err == nil {
		t.Fatal("confirmation for one action must not authorize different arguments")
	}
	if err := consumeToolActionConfirmation(token, manifest.Name, manifest.Version, record.ArtifactHash, input); err == nil {
		t.Fatal("a mismatched confirmation attempt must consume the one-use token")
	}

	token, _, err = IssueToolActionConfirmation(coreRoot, manifest.Name, manifest.Version, record.ArtifactHash, input)
	if err != nil {
		t.Fatal(err)
	}
	if err := consumeToolActionConfirmation(token, manifest.Name, manifest.Version, record.ArtifactHash, input); err != nil {
		t.Fatalf("exact confirmed action should be authorized once: %v", err)
	}
	if err := consumeToolActionConfirmation(token, manifest.Name, manifest.Version, record.ArtifactHash, input); err == nil {
		t.Fatal("the same confirmation token must not be reusable")
	}
}
