package genesis

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const maxSandboxLogBytes = 1 << 20

// SandboxEvidence records the requested isolation contract and observed result.
// It deliberately does not claim that host/container enforcement was independently
// attested; a successful Docker invocation is not a host security audit.
type SandboxEvidence struct {
	ToolName       string    `json:"tool_name"`
	ManifestHash   string    `json:"manifest_hash"`
	StartedAt      time.Time `json:"started_at"`
	FinishedAt     time.Time `json:"finished_at"`
	Passed         bool      `json:"passed"`
	ExitCode       int       `json:"exit_code"`
	IsolationLevel string    `json:"isolation_level"`
	BuildLog       string    `json:"build_log"`
	TestLog        string    `json:"test_log"`
	ErrorClass     string    `json:"error_class,omitempty"`
}

type sandboxCommandRunner func(context.Context, string, ...string) ([]byte, error)

// RunCandidateSandbox builds and tests an artifact in a Docker container with
// networking disabled, read-only root filesystem, a read-only candidate mount,
// bounded tmpfs, memory/CPU/PID limits, dropped capabilities and non-root UID.
// If Docker is unavailable or any constraint cannot be requested, it fails closed.
func RunCandidateSandbox(ctx context.Context, candidateDir, evidenceDir string, manifest ToolManifest) (SandboxEvidence, error) {
	return runCandidateSandbox(ctx, candidateDir, evidenceDir, manifest, runSandboxCommand)
}

func runSandboxCommand(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=/tmp", "TMPDIR=/tmp"}
	var out boundedBuffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	err := cmd.Run()
	return out.Bytes(), err
}

type boundedBuffer struct { bytes.Buffer }

func (b *boundedBuffer) Write(p []byte) (int, error) {
	if b.Len() >= maxSandboxLogBytes {
		return len(p), nil
	}
	remaining := maxSandboxLogBytes - b.Len()
	if len(p) > remaining {
		_, _ = b.Buffer.Write(p[:remaining])
		return len(p), nil
	}
	return b.Buffer.Write(p)
}

func runCandidateSandbox(ctx context.Context, candidateDir, evidenceDir string, manifest ToolManifest, runner sandboxCommandRunner) (SandboxEvidence, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ValidateToolManifest(manifest); err != nil {
		return SandboxEvidence{}, fmt.Errorf("sandbox refused invalid manifest: %w", err)
	}
	candidateDir, err := filepath.Abs(candidateDir)
	if err != nil {
		return SandboxEvidence{}, errors.New("sandbox candidate path is invalid")
	}
	info, err := os.Lstat(candidateDir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return SandboxEvidence{}, errors.New("sandbox candidate must be an existing non-symlink directory")
	}
	evidenceDir, err = filepath.Abs(evidenceDir)
	if err != nil {
		return SandboxEvidence{}, errors.New("sandbox evidence path is invalid")
	}
	if err := os.MkdirAll(evidenceDir, 0o700); err != nil {
		return SandboxEvidence{}, errors.New("sandbox evidence directory is unavailable")
	}

	image, command := "golang:1.23-alpine", []string{"sh", "-lc", "mkdir -p /tmp/work /tmp/gocache && cp -R /candidate/. /tmp/work/ && chmod -R u+rwX /tmp/work && cd /tmp/work && echo GENESIS_TESTS_BEGIN && GO111MODULE=off GOCACHE=/tmp/gocache go test . && echo GENESIS_BUILD_BEGIN && GO111MODULE=off GOCACHE=/tmp/gocache go build -o /tmp/genesis-candidate ."}
	if manifest.Language == "python" {
		image = "python:3.12-alpine"
		command = []string{"sh", "-lc", "mkdir -p /tmp/work && cp -R /candidate/. /tmp/work/ && chmod -R u+rwX /tmp/work && cd /tmp/work && echo GENESIS_TESTS_BEGIN && python -m compileall -q . && python -m unittest discover -v"}
	}
	args := []string{
		"run", "--rm", "--pull=never",
		"--network=none", "--read-only",
		"--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
		"--memory", strconv.FormatInt(manifest.MemoryBytes, 10),
		"--memory-swap", strconv.FormatInt(manifest.MemoryBytes, 10),
		"--cpus", "1",
		"--pids-limit", "64",
		"--user", "65534:65534",
		"--cap-drop=ALL",
		"--security-opt=no-new-privileges",
		"--mount", "type=bind,src="+candidateDir+",dst=/candidate,readonly",
		"--workdir", "/tmp",
		"--env", "PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin",
		"--env", "HOME=/tmp",
		"--env", "TMPDIR=/tmp",
		"--env", "GOTOOLCHAIN=local",
		image,
	}
	args = append(args, command...)
	started := time.Now().UTC()
	log, runErr := runner(ctx, "docker", args...)
	finished := time.Now().UTC()
	if len(log) > maxSandboxLogBytes {
		log = log[:maxSandboxLogBytes]
	}
	manifestJSON, _ := json.Marshal(manifest)
	manifestDigest := sha256.Sum256(manifestJSON)
	logText := string(log)
	testLog, buildLog := logText, ""
	if split := strings.Index(logText, "GENESIS_BUILD_BEGIN"); split >= 0 {
		testLog = strings.TrimSpace(strings.TrimPrefix(logText[:split], "GENESIS_TESTS_BEGIN"))
		buildLog = strings.TrimSpace(logText[split+len("GENESIS_BUILD_BEGIN"):])
	}
	evidence := SandboxEvidence{
		ToolName: manifest.Name,
		ManifestHash: hex.EncodeToString(manifestDigest[:]),
		StartedAt: started,
		FinishedAt: finished,
		Passed: runErr == nil,
		ExitCode: 0,
		IsolationLevel: "docker_constraints_requested_host_enforcement_unverified",
		BuildLog: buildLog,
		TestLog: testLog,
	}
	if runErr != nil {
		evidence.ExitCode = 1
		evidence.ErrorClass = "sandbox_or_candidate_failed"
		if strings.Contains(strings.ToLower(runErr.Error()), "executable file not found") {
			evidence.ErrorClass = "docker_unavailable"
			evidence.IsolationLevel = "unavailable_fail_closed"
		}
	}
	raw, _ := jsonMarshalIndent(evidence)
	if err := atomicWrite(filepath.Join(evidenceDir, "sandbox_evidence.json"), raw, 0o600); err != nil {
		return evidence, errors.New("sandbox evidence could not be persisted")
	}
	if runErr != nil {
		return evidence, errors.New("sandbox build/test did not pass; candidate must not be signed")
	}
	return evidence, nil
}

func jsonMarshalIndent(value any) ([]byte, error) {
	return json.MarshalIndent(value, "", "  ")
}
