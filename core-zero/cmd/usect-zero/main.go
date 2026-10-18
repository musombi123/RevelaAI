package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"usect-zero.local/core-zero/heal"
	"usect-zero.local/core-zero/internal/api"
	"usect-zero.local/core-zero/internal/kernel"
)

func main() {
	mode := flag.String("mode", "serve", "serve | scan | baseline | heal-propose")
	root := flag.String("root", ".", "host repository root")
	listen := flag.String("listen", "127.0.0.1:8780", "HTTP listen address; loopback is the safe default")
	flag.Parse()
	resolved := *root
	if env := os.Getenv("USECT_ZERO_REPO_ROOT"); env != "" && *root == "." {
		resolved = env
	}
	abs, err := filepath.Abs(resolved)
	if err != nil {
		log.Fatal(err)
	}
	k, err := kernel.New(abs)
	if err != nil {
		log.Fatal(err)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	switch *mode {
	case "scan":
		s, e := k.SaveEvidence()
		if e != nil { log.Fatal(e) }
		if e = enc.Encode(s); e != nil { log.Fatal(e) }
	case "baseline":
		b, e := k.RecordBaseline()
		if e != nil { log.Fatal(e) }
		if e = enc.Encode(b); e != nil { log.Fatal(e) }
	case "heal-propose":
		p, e := heal.ProposeMissing(k)
		if e != nil { log.Fatal(e) }
		if e = enc.Encode(p); e != nil { log.Fatal(e) }
	case "serve":
		evidence, scanErr := k.SaveEvidence()
		if scanErr != nil { log.Fatal("startup pre-check failed: ", scanErr) }
		fmt.Fprintf(os.Stderr, "USECT-ZERO startup pre-check: %d files, manifest %s\n", evidence.FileCount, evidence.ManifestSHA256)
		if os.Getenv("USECT_ZERO_ADMIN_TOKEN") == "" { fmt.Fprintln(os.Stderr, "WARNING: USECT_ZERO_ADMIN_TOKEN is unset; human approval endpoints will fail closed.") }
		fmt.Fprintf(os.Stderr, "USECT-ZERO listening at http://%s (loopback recommended)\n", *listen)
		server := &http.Server{Addr: *listen, Handler: api.New(k), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
		if err = server.ListenAndServe(); err != nil { log.Fatal(err) }
	default:
		log.Fatalf("unknown mode %q", *mode)
	}
}
