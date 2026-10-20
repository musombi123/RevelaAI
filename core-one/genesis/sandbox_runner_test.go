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
	if err := os.WriteFile(filepath.Join(candidate, "library.go"), []byte("package candidate\n"), 0o600); err != nil {
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
	if err := os.WriteFile(filepath.Join(candidate, "library.go"), []byte("package candidate\n"), 0o600); err != nil {
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
	if result.IsolationLevel != "docker_unavailable_fail_closed" {
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
	if err := os.WriteFile(filepath.Join(candidate, "library.go"), []byte("package candidate\n"), 0o600); err != nil {
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


func TestGoCandidateRejectsUncopiedHelperModules(t *testing.T) {
	root := t.TempDir()
	for name, content := range map[string]string{
		"code.go":    "package candidate\n",
		"library.go": "package candidate\n",
		"test.go":    "package candidate\nimport \"testing\"\nfunc TestCandidate(t *testing.T) {}\n",
	} {
		if err := os.WriteFile(filepath.Join(root, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	manifest := validManifestForTest()
	if err := validateSandboxCandidate(root, manifest); err != nil {
		t.Fatalf("runtime-compatible candidate should validate: %v", err)
	}
	if err := os.Mkdir(filepath.Join(root, "helpers"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "helpers", "extra.go"), []byte("package candidate\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := validateSandboxCandidate(root, manifest); err == nil {
		t.Fatal("candidate containing a helper module omitted by runtime must be rejected")
	}
}


func TestNamedSandboxContainerGetsCleanupAfterTimeout(t *testing.T) {
	type invocation struct {
		name string
		args []string
	}
	var calls []invocation
	runner := func(_ context.Context, name string, args ...string) ([]byte, error) {
		calls = append(calls, invocation{name: name, args: append([]string(nil), args...)})
		if len(calls) == 1 {
			return []byte("runner timed out"), context.DeadlineExceeded
		}
		return nil, nil
	}
	_, err := runNamedDockerContainer(
		context.Background(),
		runner,
		"genesis-test",
		[]string{"run", "--rm", "--network=none", "python:3.12-alpine", "sh", "-lc", "true"}...,
	)
	if err == nil {
		t.Fatal("runner timeout must remain a failed sandbox result")
	}
	if len(calls) != 2 {
		t.Fatalf("expected run and cleanup calls, got %d", len(calls))
	}
	if calls[0].name != "docker" || len(calls[0].args) < 3 || calls[0].args[0] != "run" || calls[0].args[1] != "--name" {
		t.Fatalf("Docker run must have a unique explicit container name: %#v", calls[0])
	}
	containerName := calls[0].args[2]
	if !strings.HasPrefix(containerName, "genesis-test-") {
		t.Fatalf("unexpected container name: %q", containerName)
	}
	if calls[1].name != "docker" || len(calls[1].args) != 3 ||
		calls[1].args[0] != "rm" || calls[1].args[1] != "-f" || calls[1].args[2] != containerName {
		t.Fatalf("timed-out container cleanup was not attempted: %#v", calls[1])
	}
}
