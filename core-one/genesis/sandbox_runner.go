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

// SandboxEvidence records observed build/test results and the isolation
// constraints requested from the runner. It never attests that host enforcement
// has been independently verified.
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

// RunCandidateSandbox builds and tests a candidate in a no-network, resource-
// limited jail. Docker is preferred; Bubblewrap is attempted only if Docker
// cannot start or its daemon/image is unavailable. If neither jail can enforce
// its requested constraints, the candidate fails closed and is never signed.
func RunCandidateSandbox(ctx context.Context, candidateDir, evidenceDir string, manifest ToolManifest) (SandboxEvidence, error) {
	return runCandidateSandbox(ctx, candidateDir, evidenceDir, manifest, runSandboxCommand)
}

func runSandboxCommand(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	// Do not inherit provider credentials, cloud credentials, or arbitrary host
	// environment variables into either runner process.
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=/tmp", "TMPDIR=/tmp"}
	var out boundedBuffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	err := cmd.Run()
	return out.Bytes(), err
}

type boundedBuffer struct{ bytes.Buffer }

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

func candidateBuildScript(language string, timeoutSeconds int, memoryBytes int64) string {
	limits := fmt.Sprintf("ulimit -t %d; ulimit -v %d; ulimit -f 65536; ulimit -u 64 2>/dev/null || true; ", timeoutSeconds, memoryBytes/1024)
	if language == "python" {
		return limits + "mkdir -p /tmp/work && cp -R /candidate/. /tmp/work/ && chmod -R u+rwX /tmp/work && cd /tmp/work && echo GENESIS_TESTS_BEGIN && python -m compileall -q . && python -m unittest discover -v"
	}
	return limits + "mkdir -p /tmp/work /tmp/gocache && cp -R /candidate/. /tmp/work/ && chmod -R u+rwX /tmp/work && cd /tmp/work && echo GENESIS_TESTS_BEGIN && GO111MODULE=off GOCACHE=/tmp/gocache go test . && echo GENESIS_BUILD_BEGIN && GO111MODULE=off GOCACHE=/tmp/gocache go build -o /tmp/genesis-candidate ."
}

func dockerSandboxArgs(candidateDir string, manifest ToolManifest) []string {
	image := "golang:1.23-alpine"
	if manifest.Language == "python" {
		image = "python:3.12-alpine"
	}
	args := []string{
		"run", "--rm", "--pull=never",
		"--network=none", "--read-only",
		"--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
		"--memory", strconv.FormatInt(manifest.MemoryBytes, 10),
		"--memory-swap", strconv.FormatInt(manifest.MemoryBytes, 10),
		"--cpus", "1", "--pids-limit", "64",
		"--user", "65534:65534", "--cap-drop=ALL",
		"--security-opt=no-new-privileges",
		"--mount", "type=bind,src=" + candidateDir + ",dst=/candidate,readonly",
		"--workdir", "/tmp",
		"--env", "PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin",
		"--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
		"--env", "GOTOOLCHAIN=local",
		image, "sh", "-lc", candidateBuildScript(manifest.Language, maxInt(1, manifest.TimeoutMillis/1000), manifest.MemoryBytes),
	}
	return args
}

func bubblewrapSandboxArgs(candidateDir string, manifest ToolManifest) []string {
	// Root filesystem is mounted read-only; /tmp is the only writable tree;
	// network is unshared; environment is cleared; the child runs with a
	// non-root UID inside a user namespace. Failure to create namespaces is fatal.
	args := []string{
		"--die-with-parent", "--new-session",
		"--unshare-net", "--unshare-user", "--uid", "65534", "--gid", "65534",
		"--ro-bind", "/", "/",
		"--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
		"--ro-bind", candidateDir, "/candidate",
		"--chdir", "/tmp", "--clearenv",
		"--setenv", "PATH", "/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin",
		"--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
		"--setenv", "GOTOOLCHAIN", "local",
		"--", "/bin/sh", "-lc", candidateBuildScript(manifest.Language, maxInt(1, manifest.TimeoutMillis/1000), manifest.MemoryBytes),
	}
	return args
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

	// Ensure the candidate cannot be reached by modifying a path after initial
	// validation. Absolute paths are passed as data, never through a shell.
	started := time.Now().UTC()
	log, runErr := runner(ctx, "docker", dockerSandboxArgs(candidateDir, manifest)...)
	isolation := "docker_constraints_requested_host_enforcement_unverified"

	if runnerNeedsFallback(log, runErr) {
		fallbackLog, fallbackErr := runner(ctx, "bwrap", bubblewrapSandboxArgs(candidateDir, manifest)...)
		log = append(append([]byte{}, log...), []byte("\n--- Bubblewrap fallback ---\n")...)
		log = append(log, fallbackLog...)
		runErr = fallbackErr
		isolation = "bubblewrap_constraints_requested_host_enforcement_unverified"
		if fallbackErr != nil {
			isolation = "unavailable_fail_closed"
		}
	}
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
	exitCode := 0
	errorClass := ""
	if runErr != nil {
		exitCode = 1
		errorClass = "sandbox_or_candidate_failed"
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
		if isolation == "unavailable_fail_closed" {
			errorClass = "sandbox_unavailable"
		}
	}
	evidence := SandboxEvidence{
		ToolName: manifest.Name,
		ManifestHash: hex.EncodeToString(manifestDigest[:]),
		StartedAt: started,
		FinishedAt: finished,
		Passed: runErr == nil,
		ExitCode: exitCode,
		IsolationLevel: isolation,
		BuildLog: buildLog,
		TestLog: testLog,
		ErrorClass: errorClass,
	}
	raw, err := json.MarshalIndent(evidence, "", "  ")
	if err != nil {
		return evidence, errors.New("sandbox evidence could not be encoded")
	}
	if err := atomicWrite(filepath.Join(evidenceDir, "sandbox_evidence.json"), raw, 0o600); err != nil {
		return evidence, errors.New("sandbox evidence could not be persisted")
	}
	if runErr != nil {
		return evidence, errors.New("sandbox build/test did not pass; candidate must not be signed")
	}
	return evidence, nil
}

func runnerNeedsFallback(output []byte, err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, exec.ErrNotFound) || strings.Contains(strings.ToLower(err.Error()), "executable file not found") {
		return true
	}
	text := strings.ToLower(string(output) + " " + err.Error())
	for _, marker := range []string{
		"cannot connect to the docker daemon",
		"is the docker daemon running",
		"docker daemon is not running",
		"no such image",
		"docker: command not found",
	} {
		if strings.Contains(text, marker) {
			return true
		}
	}
	return false
}

func maxInt(a, b int) int {
	if a > b { return a }
	return b
}
