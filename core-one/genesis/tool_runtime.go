package genesis

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const maxToolInvocationBytes = 32 * 1024

// RunSignedToolInvocation executes only a verified signed artifact through the
// same constrained Docker boundary. No generated code runs in this process.
func RunSignedToolInvocation(ctx context.Context, coreRoot, name, version, artifactHash string, input []byte, confirmationToken string) ([]byte, error) {
	if len(input) == 0 || len(input) > 64*1024 || !json.Valid(input) {
		return nil, errors.New("tool input must be valid JSON within the size limit")
	}
	record, err := loadSignedToolArtifact(coreRoot, name, version, artifactHash)
	if err != nil {
		return nil, err
	}
	root, err := registryRoot(coreRoot)
	if err != nil {
		return nil, err
	}
	pointer, err := readActivePointer(root, name)
	if err != nil || !pointer.Active || pointer.Version != version || pointer.ArtifactHash != artifactHash {
		return nil, errors.New("tool version is not the active signed version")
	}
	if record.Manifest.RiskTier > 0 && !constantTimeStringEqual(pointer.OwnerApprovalHash, artifactHash) {
		return nil, errors.New("tool version lacks owner approval bound to the active artifact hash")
	}
	if record.Manifest.RiskTier == 2 {
		if err := consumeToolActionConfirmation(confirmationToken, name, version, artifactHash, input); err != nil {
			return nil, err
		}
	}

	artifactDir := filepath.Join(root, "versions", name, version, "artifact"
	ctx, cancel := context.WithTimeout(ctx, time.Duration(record.Manifest.TimeoutMillis)*time.Millisecond)
	defer cancel()
	image := "golang:1.23-alpine"
	script := goToolInvocationScript
	if record.Manifest.Language == "python" {
		image = "python:3.12-alpine"
		entrypoint := record.Manifest.Entrypoint
		script = "exec python /candidate/" + shellQuote(entrypoint)
	}
	args := []string{
		"run", "-i", "--rm", "--pull=never",
		"--network=none", "--read-only",
		"--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
		"--memory", strconv.FormatInt(record.Manifest.MemoryBytes, 10),
		"--memory-swap", strconv.FormatInt(record.Manifest.MemoryBytes, 10),
		"--cpus", "1", "--pids-limit", "64",
		"--user", "65534:65534", "--cap-drop=ALL",
		"--security-opt=no-new-privileges",
		"--mount", "type=bind,src="+artifactDir+",dst=/candidate,readonly",
		"--workdir", "/tmp",
		"--env", "PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin",
		"--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
		"--env", "GOTOOLCHAIN=local",
		image, "sh", "-lc", script,
	}
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=/tmp", "TMPDIR=/tmp"}
	cmd.Stdin = bytes.NewReader(input)
	var out boundedBuffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	runErr := cmd.Run()
	result := out.Bytes()
	if len(result) > maxToolInvocationBytes {
		return nil, errors.New("tool result exceeded the size limit")
	}
	if runErr != nil {
		if ctx.Err() != nil {
			return nil, errors.New("tool execution timed out")
		}
		return nil, errors.New("sandboxed tool execution failed")
	}
	if !json.Valid(result) {
		return nil, errors.New("sandboxed tool returned invalid JSON")
	}
	return append([]byte(nil), result...), nil
}

const goToolInvocationScript = "set -eu; mkdir -p /tmp/work/toolimpl /tmp/gocache; cp /candidate/code.go /candidate/library.go /tmp/work/toolimpl/; chmod -R u+rwX /tmp/work; printf 'module genesiscandidate\\n\\ngo 1.23\\n' > /tmp/work/go.mod; cat > /tmp/work/main.go <<'GENESIS_MAIN'\npackage main\nimport (\"encoding/json\"; \"os\"; toolimpl \"genesiscandidate/toolimpl\")\nfunc main() { var in struct { Action string; Inputs map[string]string; Consent bool }; if json.NewDecoder(os.Stdin).Decode(&in) != nil { os.Exit(2) }; out, err := (toolimpl.Tool{}).Run(toolimpl.Request{Action: in.Action, Inputs: in.Inputs, Consent: in.Consent}); if err != nil { _ = json.NewEncoder(os.Stdout).Encode(map[string]string{\"status\":\"error\",\"error_class\":\"tool_rejected\"}); os.Exit(3) }; _ = json.NewEncoder(os.Stdout).Encode(out) }\nGENESIS_MAIN\ncd /tmp/work; GOCACHE=/tmp/gocache go run ."

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
}
