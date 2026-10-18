package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"revela-genesis.local/core-one/genesis"
)

func main() {
	mode := flag.String("mode", "serve", "serve | invent | submit | scan")
	rootFlag := flag.String("repo-root", "", "repository root; defaults to detected parent directory")
	listen := flag.String("listen", "127.0.0.1:8781", "HTTP listen address (loopback is the safe default)")
	demand := flag.String("demand", "", "invention demand for invent/submit mode")
	interval := flag.Duration("interval", 60*time.Second, "daemon queue scan interval")
	flag.Parse()
	root := strings.TrimSpace(*rootFlag)
	if root == "" {
		root = discoverRoot()
	}
	engine, err := genesis.NewEngine(root)
	if err != nil {
		log.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	switch *mode {
	case "invent":
		inv, err := engine.Invent(ctx, *demand)
		if err != nil {
			if errors.Is(err, genesis.ErrBlocked) {
				log.Fatalf("GUARDIAN BLOCKED demand; no invention generated")
			}
			log.Fatal(err)
		}
		writeJSON(inv)
	case "submit":
		item, err := engine.Enqueue(*demand, "cli")
		if err != nil {
			if errors.Is(err, genesis.ErrBlocked) {
				log.Fatalf("GUARDIAN BLOCKED demand; it was not queued")
			}
			log.Fatal(err)
		}
		writeJSON(item)
	case "scan":
		if err := engine.EyeScan(ctx); err != nil && !errors.Is(err, genesis.ErrBlocked) {
			log.Printf("eye scan warning: %v", err)
		}
		if err := engine.ProcessQueue(ctx); err != nil {
			log.Fatal(err)
		}
		fmt.Fprintln(os.Stderr, "Queue scan completed.")
	case "serve":
		go engine.RunDaemon(ctx, *interval)
		go engine.RunProviderLoop(ctx)
		server := &http.Server{Addr: *listen, Handler: &genesis.Server{Engine: engine}, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 40 * time.Second, WriteTimeout: 45 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 1 << 20}
		fmt.Fprintf(os.Stderr, "Revela Genesis %s listening on %s (standalone=%t, model_configured=%t)\n", genesis.Version, *listen, true, os.Getenv("GENESIS_MODEL_BASE_URL") != "")
		fmt.Fprintln(os.Stderr, "Generated artifacts are proposals only; no invention is executed or merged automatically.")
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	default:
		log.Fatalf("unknown mode %q; expected serve, invent, submit, or scan", *mode)
	}
}

func discoverRoot() string {
	if env := strings.TrimSpace(os.Getenv("GENESIS_REPO_ROOT")); env != "" {
		return env
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	abs, _ := filepath.Abs(cwd)
	if _, err := os.Stat(filepath.Join(abs, "core-one", "guardian", "rules.yaml")); err == nil {
		return abs
	}
	if filepath.Base(abs) == "core-one" {
		return filepath.Dir(abs)
	}
	if _, err := os.Stat(filepath.Join(abs, "core-zero", "go.mod")); err == nil {
		return abs
	}
	return abs
}
func writeJSON(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		log.Fatal(err)
	}
}
