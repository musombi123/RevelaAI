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
	writeTestCandidateManifest(t, candidate, manifest)
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
	writeTestCandidateManifest(t, candidate, manifest)
	if err := screenCandidateForPublication(engine, candidate, manifest); err != nil {
		t.Fatalf("safe candidate should pass Guardian screening: %v", err)
	}
}


func TestPublicationGuardianRejectsChangedEmbeddedManifest(t *testing.T) {
	engine := newTestEngine(t)
	candidate := writeRegistryCandidate(t, "package candidate\nfunc Safe() string { return \"proposal only\" }\n")
	if err := os.WriteFile(filepath.Join(candidate, "test.go"), []byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	embedded := validManifestForTest()
	writeTestCandidateManifest(t, candidate, embedded)

	changed := embedded
	changed.Version = "1.0.1"
	if err := screenCandidateForPublication(engine, candidate, changed); err == nil {
		t.Fatal("publication must reject a manifest that disagrees with the embedded tool_manifest.json")
	}
}
