package heal

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	gitCommandTimeout = 45 * time.Second
	gitMaxOutputBytes = 256 << 20 // 256 MiB
	gitMaxStderrBytes = 64 << 10  // 64 KiB
	gitMaxArgumentLen = 1 << 20   // 1 MiB per argument
	gitMaxArguments   = 128
)

var errGitOutputTooLarge = errors.New("git command output exceeded the configured limit")

// boundedGitBuffer captures command output without allowing an unlimited
// amount of data to accumulate in memory.
type boundedGitBuffer struct {
	buffer   bytes.Buffer
	limit    int
	cancel   context.CancelFunc
	exceeded bool
}

func newBoundedGitBuffer(limit int, cancel context.CancelFunc) *boundedGitBuffer {
	return &boundedGitBuffer{
		limit:  limit,
		cancel: cancel,
	}
}

func (b *boundedGitBuffer) Write(p []byte) (int, error) {
	if b.exceeded {
		return 0, errGitOutputTooLarge
	}

	remaining := b.limit - b.buffer.Len()
	if remaining <= 0 {
		b.exceeded = true
		b.cancel()
		return 0, errGitOutputTooLarge
	}

	if len(p) > remaining {
		written, _ := b.buffer.Write(p[:remaining])
		b.exceeded = true
		b.cancel()
		return written, errGitOutputTooLarge
	}

	return b.buffer.Write(p)
}

func (b *boundedGitBuffer) Bytes() []byte {
	return b.buffer.Bytes()
}

// runGit executes Git directly without a shell.
//
// It is intended for bounded, local Git operations such as inspecting
// commits, reading tracked files, and examining repository metadata.
// It rejects invalid roots and excessive arguments, disables interactive
// prompting, and terminates commands that exceed the time or output limits.
func runGit(root string, args ...string) ([]byte, error) {
	if strings.TrimSpace(root) == "" {
		return nil, errors.New("git repository root is empty")
	}

	if len(args) == 0 {
		return nil, errors.New("git command arguments are required")
	}

	if len(args) > gitMaxArguments {
		return nil, fmt.Errorf(
			"git command has too many arguments: %d (maximum %d)",
			len(args),
			gitMaxArguments,
		)
	}

	totalArgumentBytes := 0
	for i, arg := range args {
		if strings.IndexByte(arg, 0) >= 0 {
			return nil, fmt.Errorf("git argument %d contains a NUL byte", i)
		}

		if len(arg) > gitMaxArgumentLen {
			return nil, fmt.Errorf(
				"git argument %d exceeds the %d-byte limit",
				i,
				gitMaxArgumentLen,
			)
		}

		totalArgumentBytes += len(arg)
		if totalArgumentBytes > gitMaxArgumentLen {
			return nil, fmt.Errorf(
				"combined git arguments exceed the %d-byte limit",
				gitMaxArgumentLen,
			)
		}
	}

	absoluteRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve git repository root: %w", err)
	}
	absoluteRoot = filepath.Clean(absoluteRoot)

	info, err := os.Stat(absoluteRoot)
	if err != nil {
		return nil, fmt.Errorf("inspect git repository root: %w", err)
	}
	if !info.IsDir() {
		return nil, errors.New("git repository root is not a directory")
	}

	ctx, cancel := context.WithTimeout(context.Background(), gitCommandTimeout)
	defer cancel()

	cmdArgs := make([]string, 0, len(args)+2)
	cmdArgs = append(cmdArgs, "-C", absoluteRoot)
	cmdArgs = append(cmdArgs, args...)

	cmd := exec.CommandContext(ctx, "git", cmdArgs...)
	cmd.WaitDelay = 2 * time.Second

	// Prevent terminal prompts and background Git lock refreshes. Remove
	// inherited repository-location overrides so ambient variables cannot
	// redirect ordinary Git operations to another work tree or index.
	cmd.Env = safeGitEnvironment(os.Environ())

	stdout := newBoundedGitBuffer(gitMaxOutputBytes, cancel)
	stderr := newBoundedGitBuffer(gitMaxStderrBytes, cancel)

	cmd.Stdout = stdout
	cmd.Stderr = stderr

	runErr := cmd.Run()

	if stdout.exceeded {
		return nil, errGitOutputTooLarge
	}
	if stderr.exceeded {
		return nil, errors.New("git command stderr exceeded the configured limit")
	}

	if ctx.Err() == context.DeadlineExceeded {
		return nil, fmt.Errorf("git command timed out after %s", gitCommandTimeout)
	}

	if runErr != nil {
		detail := strings.TrimSpace(string(stderr.Bytes()))
		if detail != "" {
			return nil, fmt.Errorf(
				"git %q failed: %w: %s",
				args[0],
				runErr,
				detail,
			)
		}

		return nil, fmt.Errorf("git %q failed: %w", args[0], runErr)
	}

	return bytes.Clone(stdout.Bytes()), nil
}

// safeGitEnvironment removes environment variables that can redirect Git
// to a different repository, index, object database, or replacement refs.
// Other environment variables are retained for compatibility.
func safeGitEnvironment(environment []string) []string {
	blocked := map[string]struct{}{
		"GIT_DIR":                          {},
		"GIT_WORK_TREE":                    {},
		"GIT_COMMON_DIR":                   {},
		"GIT_INDEX_FILE":                   {},
		"GIT_OBJECT_DIRECTORY":              {},
		"GIT_ALTERNATE_OBJECT_DIRECTORIES": {},
		"GIT_REPLACE_REF_BASE":             {},
		"GIT_TERMINAL_PROMPT":              {},
		"GIT_OPTIONAL_LOCKS":               {},
		"GIT_NO_REPLACE_OBJECTS":           {},
		"GCM_INTERACTIVE":                  {},
	}

	result := make([]string, 0, len(environment)+5)

	for _, entry := range environment {
		key, _, found := strings.Cut(entry, "=")
		if !found {
			continue
		}

		if _, remove := blocked[key]; remove {
			continue
		}

		result = append(result, entry)
	}

	result = append(
		result,
		"GIT_TERMINAL_PROMPT=0",
		"GIT_OPTIONAL_LOCKS=0",
		"GIT_NO_REPLACE_OBJECTS=1",
		"GCM_INTERACTIVE=Never",
	)

	return result
}
