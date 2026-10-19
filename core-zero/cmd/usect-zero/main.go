package main

import (
	"context"
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

	"usect-zero.local/core-zero/heal"
	"usect-zero.local/core-zero/internal/api"
	"usect-zero.local/core-zero/internal/kernel"
)

const (
	defaultLocalAddress = "127.0.0.1:8780"
	shutdownTimeout     = 10 * time.Second
)

func main() {
	mode := flag.String(
		"mode",
		"serve",
		"serve | scan | baseline | heal-propose",
	)
	root := flag.String("root", ".", "host repository root")
	listen := flag.String(
		"listen",
		"",
		"HTTP listen address; defaults to USECT_ZERO_LISTEN, PORT, or loopback",
	)
	flag.Parse()

	resolvedRoot, err := resolveRepositoryRoot(*root)
	if err != nil {
		log.Fatal(err)
	}

	k, err := kernel.New(resolvedRoot)
	if err != nil {
		log.Fatalf("initialize USECT-ZERO kernel: %v", err)
	}

	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")

	switch *mode {
	case "scan":
		evidence, err := k.SaveEvidence()
		if err != nil {
			log.Fatalf("save scan evidence: %v", err)
		}

		if err := encoder.Encode(evidence); err != nil {
			log.Fatalf("encode scan evidence: %v", err)
		}

	case "baseline":
		baseline, err := k.RecordBaseline()
		if err != nil {
			log.Fatalf("record baseline: %v", err)
		}

		if err := encoder.Encode(baseline); err != nil {
			log.Fatalf("encode baseline: %v", err)
		}

	case "heal-propose":
		proposal, err := heal.ProposeMissing(k)
		if err != nil {
			log.Fatalf("propose recovery: %v", err)
		}

		if err := encoder.Encode(proposal); err != nil {
			log.Fatalf("encode recovery proposal: %v", err)
		}

	case "serve":
		if err := requireAdminToken(); err != nil {
			log.Fatal(err)
		}

		address, err := resolveListenAddress(*listen)
		if err != nil {
			log.Fatal(err)
		}

		evidence, err := k.SaveEvidence()
		if err != nil {
			log.Fatalf("startup pre-check failed: %v", err)
		}

		log.Printf(
			"USECT-ZERO startup pre-check passed: %d files, manifest %s",
			evidence.FileCount,
			evidence.ManifestSHA256,
		)

		log.Print(
			"USECT-ZERO admin token is configured; token value is not logged",
		)

		if token := os.Getenv("USECT_ZERO_ADMIN_TOKEN"); len(token) < 32 {
			log.Print(
				"WARNING: USECT_ZERO_ADMIN_TOKEN is shorter than 32 bytes; " +
					"use a long, randomly generated secret",
			)
		}

		host, _, _ := net.SplitHostPort(address)
		if !isLoopbackHost(host) {
			log.Print(
				"WARNING: server is bound to a non-loopback address; " +
					"restrict network access and use a trusted HTTPS reverse proxy",
			)
		}

		server := &http.Server{
			Addr:              address,
			Handler:           api.New(k),
			ReadHeaderTimeout: 5 * time.Second,
			ReadTimeout:       15 * time.Second,
			WriteTimeout:      30 * time.Second,
			IdleTimeout:       60 * time.Second,
			MaxHeaderBytes:    1 << 20,
		}

		log.Printf("USECT-ZERO listening on %s", address)

		if err := serveHTTP(server); err != nil {
			log.Fatalf("USECT-ZERO server stopped with an error: %v", err)
		}

	default:
		log.Fatalf(
			"unknown mode %q; supported modes: serve, scan, baseline, heal-propose",
			*mode,
		)
	}
}

// requireAdminToken prevents the HTTP server from starting in a misleading
// degraded state when administrator authentication has not been configured.
//
// api.New(k) must use this same server-side environment variable for its
// admin authentication checks.
func requireAdminToken() error {
	token, exists := os.LookupEnv("USECT_ZERO_ADMIN_TOKEN")

	if !exists || strings.TrimSpace(token) == "" {
		return errors.New(
			"admin authentication is not configured: set USECT_ZERO_ADMIN_TOKEN " +
				"on the server before starting in serve mode",
		)
	}

	if token != strings.TrimSpace(token) {
		return errors.New(
			"USECT_ZERO_ADMIN_TOKEN contains leading or trailing whitespace; " +
				"set the exact secret value without surrounding whitespace",
		)
	}

	if strings.ContainsAny(token, "\r\n\x00") {
		return errors.New(
			"USECT_ZERO_ADMIN_TOKEN contains invalid control characters",
		)
	}

	return nil
}

func resolveRepositoryRoot(rootFlag string) (string, error) {
	resolved := strings.TrimSpace(rootFlag)
	if resolved == "" {
		return "", errors.New("repository root cannot be empty")
	}

	if envRoot := strings.TrimSpace(os.Getenv("USECT_ZERO_REPO_ROOT")); envRoot != "" &&
		rootFlag == "." {
		resolved = envRoot
	}

	absoluteRoot, err := filepath.Abs(resolved)
	if err != nil {
		return "", fmt.Errorf("resolve repository root: %w", err)
	}

	info, err := os.Stat(absoluteRoot)
	if err != nil {
		return "", fmt.Errorf("inspect repository root: %w", err)
	}

	if !info.IsDir() {
		return "", errors.New("repository root must be a directory")
	}

	return filepath.Clean(absoluteRoot), nil
}

func resolveListenAddress(listenFlag string) (string, error) {
	address := strings.TrimSpace(listenFlag)

	// An explicit CLI argument takes precedence over environment settings.
	if address == "" {
		address = strings.TrimSpace(os.Getenv("USECT_ZERO_LISTEN"))
	}

	// Hosting platforms commonly supply PORT. Bind to all interfaces in
	// that case because their reverse proxy routes requests to that port.
	if address == "" {
		if portValue := strings.TrimSpace(os.Getenv("PORT")); portValue != "" {
			port, err := strconv.Atoi(portValue)
			if err != nil || port < 1 || port > 65535 {
				return "", errors.New(
					"PORT must be a valid TCP port between 1 and 65535",
				)
			}

			address = net.JoinHostPort("0.0.0.0", strconv.Itoa(port))
		}
	}

	if address == "" {
		address = defaultLocalAddress
	}

	host, portValue, err := net.SplitHostPort(address)
	if err != nil {
		return "", fmt.Errorf(
			"invalid listen address %q; use a valid host:port address: %w",
			address,
			err,
		)
	}

	port, err := strconv.Atoi(portValue)
	if err != nil || port < 1 || port > 65535 {
		return "", errors.New(
			"listen port must be a valid TCP port between 1 and 65535",
		)
	}

	// Rebuild the address from validated components.
	return net.JoinHostPort(host, strconv.Itoa(port)), nil
}

func isLoopbackHost(host string) bool {
	host = strings.TrimSpace(strings.ToLower(host))

	if host == "localhost" {
		return true
	}

	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func serveHTTP(server *http.Server) error {
	signalContext, stop := signal.NotifyContext(
		context.Background(),
		os.Interrupt,
		syscall.SIGTERM,
	)
	defer stop()

	serverErrors := make(chan error, 1)

	go func() {
		serverErrors <- server.ListenAndServe()
	}()

	select {
	case err := <-serverErrors:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err

	case <-signalContext.Done():
		shutdownContext, cancel := context.WithTimeout(
			context.Background(),
			shutdownTimeout,
		)
		defer cancel()

		if err := server.Shutdown(shutdownContext); err != nil {
			_ = server.Close()
			return fmt.Errorf("graceful shutdown failed: %w", err)
		}

		err := <-serverErrors
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return err
		}

		log.Print("USECT-ZERO stopped cleanly")
		return nil
	}
}
