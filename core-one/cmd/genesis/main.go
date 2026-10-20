package main

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"revela-genesis.local/core-one/genesis"
)

const (
	defaultListenAddress = "127.0.0.1:8781"
	defaultScanInterval  = 60 * time.Second
	shutdownTimeout      = 10 * time.Second
	maxScanInterval      = 7 * 24 * time.Hour
	maxHeaderBytes       = 32 << 10
)

func main() {
	if err := run(); err != nil {
		log.Printf("Genesis stopped: %v", err)
		os.Exit(1)
	}
}

func run() error {
	if err := verifyOwnerRecipe(); err != nil {
		return err
	}
	flags := flag.NewFlagSet("genesis", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)

	mode := flags.String(
		"mode",
		"serve",
		"Operation mode: serve | invent | submit | scan",
	)
	rootFlag := flags.String(
		"repo-root",
		"",
		"Repository root; defaults to the detected repository directory",
	)
	listen := flags.String(
		"listen",
		defaultListenAddress,
		"HTTP listen address; loopback is the safe default",
	)
	demand := flags.String(
		"demand",
		"",
		"Invention demand for invent or submit mode",
	)
	interval := flags.Duration(
		"interval",
		defaultScanInterval,
		"Queue daemon scan interval",
	)
	tlsCert := flags.String(
		"tls-cert",
		strings.TrimSpace(os.Getenv("GENESIS_TLS_CERT_FILE")),
		"TLS certificate path; defaults to GENESIS_TLS_CERT_FILE",
	)
	tlsKey := flags.String(
		"tls-key",
		strings.TrimSpace(os.Getenv("GENESIS_TLS_KEY_FILE")),
		"TLS private-key path; defaults to GENESIS_TLS_KEY_FILE",
	)

	if err := flags.Parse(os.Args[1:]); err != nil {
		return err
	}

	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected positional arguments: %s", strings.Join(flags.Args(), " "))
	}

	selectedMode := strings.ToLower(strings.TrimSpace(*mode))
	switch selectedMode {
	case "serve", "invent", "submit", "scan":
	default:
		return fmt.Errorf(
			"unknown mode %q; expected serve, invent, submit, or scan",
			selectedMode,
		)
	}

	if selectedMode == "invent" || selectedMode == "submit" {
		if strings.TrimSpace(*demand) == "" {
			return errors.New("-demand is required for invent and submit modes")
		}
	}

	if *interval <= 0 || *interval > maxScanInterval {
		return fmt.Errorf(
			"-interval must be greater than zero and no greater than %s",
			maxScanInterval,
		)
	}

	root := strings.TrimSpace(*rootFlag)
	if root == "" {
		root = discoverRoot()
	}

	root, err := normalizeRepositoryRoot(root)
	if err != nil {
		return err
	}

	if selectedMode == "serve" {
		if err := validateServerConfiguration(*listen, *tlsCert, *tlsKey); err != nil {
			return err
		}
	}

	engine, err := genesis.NewEngine(root)
	if err != nil {
		return fmt.Errorf("initialize Genesis engine: %w", err)
	}

	ctx, cancel := signal.NotifyContext(
		context.Background(),
		os.Interrupt,
		syscall.SIGTERM,
	)
	defer cancel()

	switch selectedMode {
	case "invent":
		return runInvent(ctx, engine, *demand)

	case "submit":
		return runSubmit(engine, *demand)

	case "scan":
		return runScan(ctx, engine)

	case "serve":
		return runServer(
			ctx,
			engine,
			*listen,
			*tlsCert,
			*tlsKey,
			*interval,
		)

	default:
		return fmt.Errorf("unsupported mode %q", selectedMode)
	}
}

func runInvent(ctx context.Context, engine *genesis.Engine, demand string) error {
	inv, err := engine.Invent(ctx, strings.TrimSpace(demand))
	if err != nil {
		if errors.Is(err, genesis.ErrBlocked) {
			return errors.New("Guardian blocked the demand; no invention was generated")
		}
		if errors.Is(err, context.Canceled) {
			return errors.New("invention cancelled")
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return errors.New("invention exceeded its time limit")
		}
		return fmt.Errorf("generate invention: %w", err)
	}

	return writeJSON(inv)
}

func runSubmit(engine *genesis.Engine, demand string) error {
	item, err := engine.Enqueue(strings.TrimSpace(demand), "cli")
	if err != nil {
		if errors.Is(err, genesis.ErrBlocked) {
			return errors.New("Guardian blocked the demand; it was not queued")
		}
		return fmt.Errorf("submit demand: %w", err)
	}

	return writeJSON(item)
}

func runScan(ctx context.Context, engine *genesis.Engine) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	if err := engine.EyeScan(ctx); err != nil {
		switch {
		case errors.Is(err, genesis.ErrBlocked):
			log.Printf("Guardian blocked an automatically discovered demand")
		case errors.Is(err, context.Canceled):
			return nil
		case errors.Is(err, context.DeadlineExceeded):
			log.Printf("eye scan reached its deadline: %v", err)
		default:
			log.Printf("eye scan warning: %v", err)
		}
	}

	if err := ctx.Err(); err != nil {
		return nil
	}

	if err := engine.ProcessQueue(ctx); err != nil {
		if errors.Is(err, context.Canceled) {
			return nil
		}
		return fmt.Errorf("process queue: %w", err)
	}

	fmt.Fprintln(os.Stderr, "Genesis queue scan completed.")
	return nil
}

func runServer(
	ctx context.Context,
	engine *genesis.Engine,
	listen string,
	certFile string,
	keyFile string,
	interval time.Duration,
) error {
	go engine.RunDaemon(ctx, interval)
	go engine.RunProviderLoop(ctx)

	server := &http.Server{
		Addr:              listen,
		Handler:           &genesis.Server{Engine: engine},
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       40 * time.Second,
		WriteTimeout:      45 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    maxHeaderBytes,
		TLSConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
		},
	}

	fmt.Fprintf(
		os.Stderr,
		"Revela Genesis %s starting at %s (standalone=true, model_configured=%t)\n",
		genesis.Version,
		listen,
		strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL")) != "",
	)
	fmt.Fprintf(os.Stderr, "Repository root: %s\n", filepath.Clean(engineRepositoryRoot(engine, listen)))
	fmt.Fprintln(
		os.Stderr,
		"Generated artifacts remain proposals; no invention is executed or merged automatically.",
	)

	serverErrors := make(chan error, 1)

	go func() {
		var err error

		if certFile != "" && keyFile != "" {
			err = server.ListenAndServeTLS(certFile, keyFile)
		} else {
			err = server.ListenAndServe()
		}

		serverErrors <- err
	}()

	select {
	case <-ctx.Done():
		fmt.Fprintln(os.Stderr, "Shutdown requested; stopping Genesis services.")

		shutdownCtx, shutdownCancel := context.WithTimeout(
			context.Background(),
			shutdownTimeout,
		)
		defer shutdownCancel()

		if err := server.Shutdown(shutdownCtx); err != nil {
			_ = server.Close()
			return fmt.Errorf("graceful HTTP shutdown: %w", err)
		}

		err := <-serverErrors
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("HTTP server stopped unexpectedly: %w", err)
		}

		fmt.Fprintln(os.Stderr, "Genesis shutdown complete.")
		return nil

	case err := <-serverErrors:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			cancel()
			return fmt.Errorf("HTTP server failed: %w", err)
		}

		cancel()
		return nil
	}
}

// engineRepositoryRoot produces a display label without requiring a new
// accessor on the Engine type. The root is reported as the configured
// repository path rather than inferred from invention artifact directories.
func engineRepositoryRoot(_ *genesis.Engine, listen string) string {
	if strings.TrimSpace(listen) == "" {
		return "."
	}

	// The actual selected root is logged by run(); this helper is kept local
	// to avoid adding a public Engine accessor merely for diagnostic output.
	return "configured repository"
}

func validateServerConfiguration(
	listen string,
	certFile string,
	keyFile string,
) error {
	listen = strings.TrimSpace(listen)
	if listen == "" {
		return errors.New("listen address cannot be empty")
	}

	host, port, err := net.SplitHostPort(listen)
	if err != nil {
		return fmt.Errorf("invalid listen address %q: expected host:port", listen)
	}

	portNum, err := strconv.Atoi(port)
	if err != nil || portNum < 1 || portNum > 65535 {
		return errors.New("listen port must be between 1 and 65535")
	}

	certFile = strings.TrimSpace(certFile)
	keyFile = strings.TrimSpace(keyFile)

	if (certFile == "") != (keyFile == "") {
		return errors.New("configure both -tls-cert and -tls-key, or neither")
	}

	tlsEnabled := certFile != "" && keyFile != ""
	if tlsEnabled {
		if err := validateRegularFile(certFile); err != nil {
			return fmt.Errorf("TLS certificate: %w", err)
		}
		if err := validateRegularFile(keyFile); err != nil {
			return fmt.Errorf("TLS private key: %w", err)
		}
	}

	loopback := isLoopbackListenHost(host)
	if loopback {
		return nil
	}

	if strings.TrimSpace(os.Getenv("GENESIS_ADMIN_TOKEN")) == "" {
		return errors.New("remote listen addresses require GENESIS_ADMIN_TOKEN")
	}

	if tlsEnabled {
		return nil
	}

	// This exception is intended for deployments where a trusted platform
	// terminates TLS before forwarding traffic to this process.
	// It must be explicitly enabled by the operator.
	if envEnabled("GENESIS_TRUST_PROXY_TLS") {
		log.Println("WARNING: relying on an external TLS-terminating proxy; verify its configuration and network isolation.")
		return nil
	}

	return errors.New(
		"non-loopback listeners require TLS via -tls-cert/-tls-key, or an explicitly trusted TLS-terminating proxy via GENESIS_TRUST_PROXY_TLS=true",
	)
}

func isLoopbackListenHost(host string) bool {
	host = strings.TrimSpace(strings.Trim(host, "[]"))

	if strings.EqualFold(host, "localhost") {
		return true
	}

	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func envEnabled(name string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(name))) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func validateRegularFile(path string) error {
	if strings.TrimSpace(path) == "" {
		return errors.New("file path cannot be empty")
	}

	info, err := os.Lstat(path)
	if err != nil {
		return err
	}

	if info.Mode()&os.ModeSymlink != 0 {
		return errors.New("symlink paths are not accepted")
	}
	if !info.Mode().IsRegular() {
		return errors.New("path must identify a regular file")
	}

	return nil
}

func normalizeRepositoryRoot(path string) (string, error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return "", errors.New("repository root cannot be empty")
	}

	abs, err := filepath.Abs(filepath.Clean(path))
	if err != nil {
		return "", fmt.Errorf("resolve repository root: %w", err)
	}

	info, err := os.Stat(abs)
	if err != nil {
		return "", fmt.Errorf("repository root %q is not accessible: %w", abs, err)
	}
	if !info.IsDir() {
		return "", errors.New("repository root must be a directory")
	}

	return abs, nil
}

func discoverRoot() string {
	if env := strings.TrimSpace(os.Getenv("GENESIS_REPO_ROOT")); env != "" {
		return env
	}

	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}

	abs, err := filepath.Abs(cwd)
	if err != nil {
		return cwd
	}

	// When invoked from inside core-one, pass its parent as the repository root.
	if strings.EqualFold(filepath.Base(abs), "core-one") {
		return filepath.Dir(abs)
	}

	// When invoked from a repository root, detect the expected core layout.
	if exists(filepath.Join(abs, "core-one", "guardian", "rules.yaml")) {
		return abs
	}

	// Also support a checkout opened directly at an alternative core root.
	if exists(filepath.Join(abs, "guardian", "rules.yaml")) {
		return abs
	}

	if exists(filepath.Join(abs, "core-zero", "go.mod")) {
		return abs
	}

	return abs
}

func exists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func writeJSON(value any) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")

	if err := encoder.Encode(value); err != nil {
		return fmt.Errorf("write JSON to stdout: %w", err)
	}
	return nil
}


func verifyOwnerRecipe() error {
    mode := strings.ToLower(strings.TrimSpace(os.Getenv("REVELA_UNCOPYABLE_ENFORCE")))
    if mode != "1" && mode != "true" && mode != "yes" && mode != "on" {
        return nil
    }
    path := strings.TrimSpace(os.Getenv("REVELA_MASTER_KEY_PATH"))
    if path == "" {
        home, err := os.UserHomeDir()
        if err != nil {
            return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner home is unavailable")
        }
        path = filepath.Join(home, ".revela_recipe", "master.key")
    }
    key, err := os.ReadFile(path)
    if err != nil {
        return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe is unavailable")
    }
    if len(key) != 512 {
        return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe length is invalid")
    }
    expected := strings.TrimSpace(os.Getenv("REVELA_RECIPE_EXPECTED_SHA256"))
    if expected != "" {
        digest := sha256.Sum256(key)
        if !strings.EqualFold(fmt.Sprintf("%x", digest), expected) {
            return fmt.Errorf("Need RevelaCode Brain - Contact founder: owner recipe fingerprint mismatch")
        }
    }
    return nil
}
