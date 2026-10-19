package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/netip"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"revela-mind.local/core-two/mind"
)

func main() {
	repoRoot := flag.String("repo-root", "..", "repository root containing core-zero, core-one, and core-two")
	listen := flag.String("listen", "127.0.0.1:8782", "Mind HTTP listener; loopback is the safe default")
	daemon := flag.Bool("daemon", false, "run the 24-hour Mirror → Mutator → Judge cycle")
	interval := flag.Duration("interval", 24*time.Hour, "daemon cycle interval; default 24h")
	flag.Parse()

	root, err := filepath.Abs(*repoRoot)
	if err != nil { log.Fatal(err) }
	host, _, splitErr := net.SplitHostPort(*listen)
	if splitErr != nil { log.Fatalf("invalid listen address %q: %v", *listen, splitErr) }
	loopback := strings.EqualFold(host, "localhost")
	if ip, parseErr := netip.ParseAddr(strings.Trim(host, "[]")); parseErr == nil && ip.IsLoopback() { loopback = true }
	if !loopback && strings.TrimSpace(os.Getenv("MIND_ADMIN_TOKEN")) == "" {
		log.Fatal("refusing a non-loopback listener without MIND_ADMIN_TOKEN; set a long random secret or bind to 127.0.0.1")
	}
	service, err := mind.NewService(root)
	if err != nil { log.Fatal(err) }
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if *daemon { go service.RunDaemon(ctx, *interval) }
	server := &http.Server{Addr:*listen, Handler:service.WithTelemetry(service), ReadHeaderTimeout:5*time.Second, ReadTimeout:30*time.Second, WriteTimeout:0, IdleTimeout:60*time.Second, MaxHeaderBytes:1<<20}
	go func(){ <-ctx.Done(); shutdown,cancel:=context.WithTimeout(context.Background(),8*time.Second); defer cancel(); _=server.Shutdown(shutdown) }()
	fmt.Fprintf(os.Stderr,"USECT-TWO %s listening on %s; model_free=true; daemon=%t; auto_merge=false\n",mind.Version,*listen,*daemon)
	fmt.Fprintln(os.Stderr,"Evolutions are review-only. Set MIND_ADMIN_TOKEN for authenticated mutations; keep public exposure behind TLS and rate limits.")
	if err:=server.ListenAndServe();err!=nil&&err!=http.ErrServerClosed{log.Fatal(err)}
}
