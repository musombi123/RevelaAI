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
	CandidateHash   string    `json:"candidate_hash"`
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
// limited Docker container. If Docker or the preloaded image is unavailable,
// the candidate fails closed and is never signed.
func RunCandidateSandbox(ctx context.Context, candidateDir, evidenceDir string, manifest ToolManifest) (SandboxEvidence, error) {
	return runCandidateSandboxWithValidator(ctx, candidateDir, evidenceDir, manifest, runSandboxCommand, nil)
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
	limits := fmt.Sprintf("ulimit -t %d; ulimit -v %d; ulimit -f 65536; ulimit -u 64; ", timeoutSeconds, memoryBytes/1024)
	if language == "python" {
		return "set -eu; " + limits + "mkdir -p /tmp/work && cp -R /candidate/. /tmp/work/ && chmod -R u+rwX /tmp/work && cd /tmp/work && echo GENESIS_TESTS_BEGIN && python -m compileall -q . && python -m unittest discover -v"
	}
	return "set -eu; " + limits + "mkdir -p /tmp/work/toolimpl /tmp/gocache && cp -R /candidate/. /tmp/work/toolimpl/ && chmod -R u+rwX /tmp/work && if [ -f /tmp/work/toolimpl/test.go ]; then mv /tmp/work/toolimpl/test.go /tmp/work/toolimpl/candidate_generated_test.go; fi && printf 'module genesiscandidate\\n\\ngo 1.23\\n' > /tmp/work/go.mod && cat > /tmp/work/main.go <<'GENESIS_MAIN'\npackage main\nimport (\"encoding/json\"; \"os\"; toolimpl \"genesiscandidate/toolimpl\")\nfunc main() { var in struct { Action string; Inputs map[string]string; Consent bool }; if json.NewDecoder(os.Stdin).Decode(&in) != nil { os.Exit(2) }; out, err := (toolimpl.Tool{}).Run(toolimpl.Request{Action: in.Action, Inputs: in.Inputs, Consent: in.Consent}); if err != nil { _ = json.NewEncoder(os.Stdout).Encode(map[string]string{\"status\":\"error\",\"error_class\":\"tool_rejected\"}); os.Exit(3) }; _ = json.NewEncoder(os.Stdout).Encode(map[string]any{\"status\": out.Status, \"tool\": out.Tool, \"summary\": out.Summary, \"created_at\": out.CreatedAt, \"evidence\": out.Evidence}) }\nGENESIS_MAIN\ncd /tmp/work && echo GENESIS_TESTS_BEGIN && GOTOOLCHAIN=local GOCACHE=/tmp/gocache go test ./... && echo GENESIS_BUILD_BEGIN && GOTOOLCHAIN=local GOCACHE=/tmp/gocache go build -o /tmp/genesis-candidate .
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

func runCandidateSandbox(ctx context.Context, candidateDir, evidenceDir string, manifest ToolManifest, runner sandboxCommandRunner) (SandboxEvidence, error) {
	return runCandidateSandboxWithValidator(ctx, candidateDir, evidenceDir, manifest, runner, nil)
}

func runCandidateSandboxWithValidator(
	ctx context.Context,
	candidateDir,
	evidenceDir string,
	manifest ToolManifest,
	runner sandboxCommandRunner,
	validateStaged func(string) error,
) (SandboxEvidence, error) {
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

	// Copy into a private staging directory and seal it read-only for the
	// non-root sandbox UID. Do not bind the original repository path: its parent
	// permissions may deny access, and the sandbox must only see the candidate.
	sourceDir, cleanupSource, err := prepareSandboxSource(candidateDir, evidenceDir)
	if err != nil {
		return SandboxEvidence{}, err
	}
	defer cleanupSource()
	if err := validateSandboxCandidate(sourceDir, manifest); err != nil {
		return SandboxEvidence{}, err
	}
	// Re-run Guardian against the exact private snapshot that will be sandboxed.
	// A mutable invention directory cannot swap in content between screening
	// and sandbox staging without this staged-snapshot check seeing the change.
	if validateStaged != nil {
		if err := validateStaged(sourceDir); err != nil {
			return SandboxEvidence{}, errors.New("Guardian refused staged candidate snapshot before sandbox execution")
		}
	}

	started := time.Now().UTC()
	log, runErr := runner(ctx, "docker", dockerSandboxArgs(sourceDir, manifest)...)
	isolation := "docker_constraints_requested_host_enforcement_unverified"
	if runErr != nil && dockerUnavailable(log, runErr) {
		isolation = "docker_unavailable_fail_closed"
	}
	finished := time.Now().UTC()
	if len(log) > maxSandboxLogBytes {
		log = log[:maxSandboxLogBytes]
	}
	manifestJSON, _ := json.Marshal(manifest)
	manifestDigest := sha256.Sum256(manifestJSON)
	candidateDigest, candidateErr := hashArtifactTree(sourceDir)
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
		if isolation == "docker_unavailable_fail_closed" {
			errorClass = "sandbox_unavailable"
		}
	}
	evidence := SandboxEvidence{
		ToolName: manifest.Name,
		CandidateHash: candidateDigest,
		ManifestHash: hex.EncodeToString(manifestDigest[:]),
		StartedAt: started,
		FinishedAt: finished,
		Passed: runErr == nil && candidateErr == nil && candidateDigest != "",
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
	if runErr != nil || candidateErr != nil || candidateDigest == "" {
		return evidence, errors.New("sandbox build/test or candidate hashing did not pass; candidate must not be signed")
	}
	return evidence, nil
}

func prepareSandboxSource(candidateDir, parent string) (string, func(), error) {
	stage, err := os.MkdirTemp(parent, ".candidate-source-*")
	if err != nil {
		return "", func() {}, errors.New("could not create a private sandbox source directory")
	}
	cleanup := func() {
		_ = makeTreeWritable(stage)
		_ = os.RemoveAll(stage)
	}
	var total int64
	fileCount := 0
	err = filepath.WalkDir(candidateDir, func(source string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("candidate symlinks are forbidden")
		}
		rel, err := filepath.Rel(candidateDir, source)
		if err != nil {
			return err
		}
		target := filepath.Join(stage, rel)
		if entry.IsDir() {
			if rel == "." {
				return nil
			}
			return os.MkdirAll(target, 0o700)
		}
		if !entry.Type().IsRegular() {
			return errors.New("candidate contains a non-regular file")
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		total += info.Size()
		fileCount++
		if total > maxRegistryBytes || fileCount > maxRegistryFiles {
			return errors.New("candidate exceeds sandbox size limits")
		}
		raw, err := os.ReadFile(source)
		if err != nil {
			return err
		}
		if err := os.WriteFile(target, raw, 0o600); err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		cleanup()
		return "", func() {}, errors.New("could not stage candidate safely for sandboxing")
	}
	if err := sealTreeForSandbox(stage); err != nil {
		cleanup()
		return "", func() {}, errors.New("could not seal sandbox candidate read-only")
	}
	return stage, cleanup, nil
}

func sealTreeForSandbox(root string) error {
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return os.Chmod(path, 0o555)
		}
		return os.Chmod(path, 0o444)
	})
}

func makeTreeWritable(root string) error {
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return os.Chmod(path, 0o700)
		}
		return os.Chmod(path, 0o600)
	})
}

func validateSandboxCandidate(root string, manifest ToolManifest) error {
	entry := filepath.Join(root, filepath.FromSlash(manifest.Entrypoint))
	info, err := os.Lstat(entry)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("manifest entrypoint must exist as a regular file in the staged candidate")
	}
	if manifest.Language == "go" {
		if manifest.Entrypoint != "code.go" || filepath.Ext(entry) != ".go" {
			return errors.New("Go manifest entrypoint must be code.go")
		}
		for _, required := range []string{"code.go", "library.go"} {
			requiredPath := filepath.Join(root, required)
			requiredInfo, statErr := os.Lstat(requiredPath)
			if statErr != nil || requiredInfo.Mode()&os.ModeSymlink != 0 || !requiredInfo.Mode().IsRegular() {
				return errors.New("Go candidate must include regular code.go and library.go runtime sources")
			}
		}
		hasTest := false
		err = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.IsDir() {
				return nil
			}
			if strings.HasSuffix(entry.Name(), "_test.go") || entry.Name() == "test.go" {
				hasTest = true
			}
			return nil
		})
		if err != nil || !hasTest {
			return errors.New("Go candidate must include a test.go or *_test.go test suite")
		}
		return nil
	}
	if filepath.Ext(entry) != ".py" {
		return errors.New("Python manifest entrypoint must be a .py file")
	}
	hasTest := false
	err = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		if strings.HasSuffix(entry.Name(), ".py") && strings.HasPrefix(entry.Name(), "test") {
			hasTest = true
		}
		return nil
	})
	if err != nil || !hasTest {
		return errors.New("Python candidate must include at least one test*.py suite")
	}
	return nil
}

func dockerUnavailable(output []byte, err error) bool {
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
