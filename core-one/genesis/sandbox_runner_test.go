package genesis

import (
	"context"
	"errors"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestSandboxRequestsIsolationAndStripsEnvironment(t *testing.T) {
	root := t.TempDir()
	candidate := filepath.Join(root, "candidate")
	evidence := filepath.Join(root, "evidence")
	if err := os.Mkdir(candidate, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "code.go"), []byte("package candidate"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "test.go"), []byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	m := validManifestForTest()
	var seen []string
	runner := func(_ context.Context, name string, args ...string) ([]byte, error) {
		if name != "docker" {
			t.Fatalf("expected docker runner, got %q", name)
		}
		seen = append(seen, args...)
		return []byte("GENESIS_TESTS_BEGIN\nPASS\nGENESIS_BUILD_BEGIN\nbuild ok"), nil
	}
	result, err := runCandidateSandbox(context.Background(), candidate, evidence, m, runner)
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "65534:65534", "--memory", "--cpus", "--pids-limit", "readonly"} {
		found := false
		for _, arg := range seen {
			if strings.Contains(arg, required) {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("sandbox command missing required constraint %q", required)
		}
	}
	for _, arg := range seen {
		if strings.Contains(strings.ToLower(arg), "api_key") || strings.Contains(strings.ToLower(arg), "secret") {
			t.Errorf("sandbox command must not pass host secrets: %q", arg)
		}
	}
	if !result.Passed || result.IsolationLevel != "docker_constraints_requested_host_enforcement_unverified" {
		t.Fatalf("unexpected sandbox evidence: %#v", result)
	}
	raw, err := os.ReadFile(filepath.Join(evidence, "sandbox_evidence.json"))
	if err != nil {
		t.Fatal(err)
	}
	var saved SandboxEvidence
	if err := json.Unmarshal(raw, &saved); err != nil {
		t.Fatal(err)
	}
	if saved.ManifestHash == "" || !strings.Contains(saved.TestLog, "PASS") || !strings.Contains(saved.BuildLog, "build ok") {
		t.Fatalf("sandbox evidence incomplete: %#v", saved)
	}
}

func TestSandboxFailureCannotPassCandidate(t *testing.T) {
	root := t.TempDir()
	candidate := filepath.Join(root, "candidate")
	if err := os.Mkdir(candidate, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "code.go"), []byte("package candidate"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "test.go"), []byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	m := validManifestForTest()
	result, err := runCandidateSandbox(context.Background(), candidate, filepath.Join(root, "evidence"), m, func(context.Context, string, ...string) ([]byte, error) {
		return []byte("compile error"), exec.ErrNotFound
	})
	if err == nil || result.Passed {
		t.Fatalf("failed sandbox run must fail closed: evidence=%#v error=%v", result, err)
	}
	if result.IsolationLevel != "unavailable_fail_closed" {
		t.Fatalf("missing Docker must be reported as unavailable: %#v", result)
	}
}


func TestStagedSnapshotGuardianRunsBeforeSandboxRunner(t *testing.T) {
	root := t.TempDir()
	candidate := filepath.Join(root, "candidate")
	evidence := filepath.Join(root, "evidence")
	if err := os.Mkdir(candidate, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "code.go"), []byte("package candidate // BLOCKED_PAYLOAD\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(candidate, "test.go"), []byte("package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest := validManifestForTest()
	runnerCalled := false
	_, err := runCandidateSandboxWithValidator(
		context.Background(),
		candidate,
		evidence,
		manifest,
		func(context.Context, string, ...string) ([]byte, error) {
			runnerCalled = true
			return []byte("should not run"), nil
		},
		func(staged string) error {
			raw, readErr := os.ReadFile(filepath.Join(staged, "code.go"))
			if readErr != nil {
				return readErr
			}
			if strings.Contains(string(raw), "BLOCKED_PAYLOAD") {
				return errors.New("Guardian test rule blocked this payload")
			}
			return nil
		},
	)
	if err == nil {
		t.Fatal("candidate rejected by staged-snapshot Guardian check must fail closed")
	}
	if runnerCalled {
		t.Fatal("sandbox runner started before staged-snapshot Guardian review completed")
	}
}
