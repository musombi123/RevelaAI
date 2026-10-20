package genesis

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPublicationGuardianScreensEditedCandidateSource(t *testing.T) {
	engine := newTestEngine(t)
	candidate := writeRegistryCandidate(t, "package candidate\n// steal credentials from users\n")
	if err := os.WriteFile(
		filepath.Join(candidate, "test.go"),
		[]byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n"),
		0o600,
	); err != nil {
		t.Fatal(err)
	}
	manifest := validManifestForTest()
	if err := screenCandidateForPublication(engine, candidate, manifest); err == nil {
		t.Fatal("modified candidate source that matches a prohibited Guardian term must be rejected before sandboxing")
	}
}

func TestPublicationGuardianAllowsSafeCandidateSource(t *testing.T) {
	engine := newTestEngine(t)
	candidate := writeRegistryCandidate(t, "package candidate\nfunc Safe() string { return \"proposal only\" }\n")
	if err := os.WriteFile(
		filepath.Join(candidate, "test.go"),
		[]byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) { if Safe() == \"\" { t.Fatal(\"empty\") } }\n"),
		0o600,
	); err != nil {
		t.Fatal(err)
	}
	manifest := validManifestForTest()
	if err := screenCandidateForPublication(engine, candidate, manifest); err != nil {
		t.Fatalf("safe candidate should pass Guardian screening: %v", err)
	}
}
