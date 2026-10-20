package mind

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	candidateCompileTimeout = 30 * time.Second
	maxCandidateTestBytes   = 256 * 1024
	maxCompilerOutputBytes  = 12 * 1024
)

// runCandidateTest preserves its existing API for callers, but now performs
// a compile-only validation. No candidate test binary is executed.
//
// Only source that exactly matches a static entry in candidateCatalog is
// accepted. Repository-sourced invention code is not accepted.
//
// Important: compilation is not a behavioral test and is not an OS sandbox.
func runCandidateTest(
	parent context.Context,
	spec candidateSpec,
) error {
	if parent == nil {
		parent = context.Background()
	}

	if err := parent.Err(); err != nil {
		return err
	}

	if !isExactAllowlistedCandidate(spec) {
		return fmt.Errorf(
			"candidate %q does not exactly match an allowlisted static template",
			limitLabel(spec.ID, 80),
		)
	}

	if len(spec.Source) == 0 ||
		len(spec.Source) > maxCandidateSourceBytes ||
		!utf8.ValidString(spec.Source) {
		return fmt.Errorf(
			"candidate %q source is empty, oversized, or invalid UTF-8",
			spec.ID,
		)
	}

	if len(sharedCandidateTest) == 0 ||
		len(sharedCandidateTest) > maxCandidateTestBytes ||
		!utf8.ValidString(sharedCandidateTest) {
		return errors.New(
			"shared candidate test template is empty, oversized, or invalid UTF-8",
		)
	}

	if err := validateCandidateSource(spec); err != nil {
		return fmt.Errorf(
			"candidate %q failed source validation: %w",
			spec.ID,
			err,
		)
	}

	goPath, err := exec.LookPath("go")
	if err != nil {
		return fmt.Errorf("Go compiler tool is unavailable: %w", err)
	}

	goInfo, err := os.Stat(goPath)
	if err != nil {
		return fmt.Errorf("inspect Go compiler tool: %w", err)
	}
	if !goInfo.Mode().IsRegular() {
		return errors.New("Go compiler tool is not a regular file")
	}

	ctx, cancel := context.WithTimeout(
		parent,
		candidateCompileTimeout,
	)
	defer cancel()

	root, err := os.MkdirTemp("", "revela-mind-candidate-compile-")
	if err != nil {
		return fmt.Errorf("create disposable compile directory: %w", err)
	}
	defer os.RemoveAll(root)

	moduleRoot := filepath.Join(root, "module")
	if err := os.Mkdir(moduleRoot, 0o700); err != nil {
		return fmt.Errorf("create candidate module directory: %w", err)
	}

	// Compilation uses a temporary module containing only:
	//  1. the exact allowlisted source;
	//  2. the fixed shared test source;
	//  3. the module declaration.
	//
	// The module declares the Go language version and prohibits dependency
	// retrieval. The actual installed compiler is not pinned by this file.
	files := []struct {
		name    string
		content string
	}{
		{
			name: "go.mod",
			content: "module candidate.fixture\n\n" +
				"go 1.23\n",
		},
		{
			name:    "library.go",
			content: spec.Source,
		},
		{
			name:    "library_test.go",
			content: sharedCandidateTest,
		},
	}

	for _, file := range files {
		if err := ctx.Err(); err != nil {
			return err
		}

		path := filepath.Join(moduleRoot, file.name)
		if err := os.WriteFile(
			path,
			[]byte(file.content),
			0o600,
		); err != nil {
			return fmt.Errorf(
				"write temporary candidate file %q: %w",
				file.name,
				err,
			)
		}
	}

	// go test -c builds the test binary but does not launch it.
	// CGO is disabled and module downloads are disabled in the environment.
	compiledTestPath := filepath.Join(root, "candidate.test")

	cmd := exec.CommandContext(
		ctx,
		goPath,
		"test",
		"-c",
		"-o",
		compiledTestPath,
		".",
	)
	cmd.Dir = moduleRoot
	cmd.Env = offlineGoEnvironment(root)
	cmd.WaitDelay = time.Second

	output := &boundedCompilerOutput{
		limit: maxCompilerOutputBytes,
	}
	cmd.Stdout = output
	cmd.Stderr = output

	if err := cmd.Run(); err != nil {
		details := strings.TrimSpace(output.String())

		if ctx.Err() != nil {
			return fmt.Errorf(
				"candidate %q compile-only check exceeded its bounded runtime: %w",
				spec.ID,
				ctx.Err(),
			)
		}

		if details == "" {
			details = "compiler returned an error without diagnostic output"
		}

		return fmt.Errorf(
			"compile-only check rejected candidate %q: %w: %s",
			spec.ID,
			err,
			details,
		)
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	// A regular test executable may now exist inside the temporary directory,
	// but this function never runs it. Deferred cleanup removes the directory.
	return nil
}

// offlineGoEnvironment constructs a minimal build environment rather than
// forwarding the process environment wholesale.
//
// This blocks ordinary module downloading and prevents inherited credentials,
// GOFLAGS, proxy credentials, and unrelated application environment variables
// from being forwarded to the compiler process. It does not create an
// operating-system security sandbox.
func offlineGoEnvironment(tempRoot string) []string {
	env := make([]string, 0, 20)

	for _, key := range []string{
		"PATH",
		"GOROOT",
		"GOOS",
		"GOARCH",
	} {
		if value := os.Getenv(key); value != "" {
			env = append(env, key+"="+value)
		}
	}

	// A shared Go build cache avoids recompiling the entire standard library
	// for every catalog entry. No candidate test binary is executed, and
	// external module downloads remain disabled.
	cache := strings.TrimSpace(os.Getenv("GOCACHE"))
	if cache == "" {
		if userCache, err := os.UserCacheDir(); err == nil {
			cache = filepath.Join(userCache, "go-build")
		}
	}

	if cache != "" {
		env = append(env, "GOCACHE="+cache)
	}

	env = append(env,
		"HOME="+tempRoot,
		"TMPDIR="+tempRoot,
		"TMP="+tempRoot,
		"TEMP="+tempRoot,
		"GOPATH="+filepath.Join(tempRoot, "gopath"),
		"GOMODCACHE="+filepath.Join(tempRoot, "gomodcache"),
		"GOTMPDIR="+tempRoot,
		"GOTOOLCHAIN=local",
		"GOPROXY=off",
		"GOSUMDB=off",
		"GOWORK=off",
		"GOENV=off",
		"CGO_ENABLED=0",
	)

	return env
}

type boundedCompilerOutput struct {
	mu        sync.Mutex
	buf       bytes.Buffer
	limit     int
	truncated bool
}

func (w *boundedCompilerOutput) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()

	originalLength := len(p)
	remaining := w.limit - w.buf.Len()

	if remaining > 0 {
		if len(p) > remaining {
			_, _ = w.buf.Write(p[:remaining])
			w.truncated = true
		} else {
			_, _ = w.buf.Write(p)
		}
	} else if originalLength > 0 {
		w.truncated = true
	}

	// Report the entire write as consumed so a large compiler diagnostic
	// cannot cause the child process to fail merely because output is capped.
	return originalLength, nil
}

func (w *boundedCompilerOutput) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()

	result := w.buf.String()
	if w.truncated {
		result += "\n[compiler output truncated]"
	}
	return result
}
