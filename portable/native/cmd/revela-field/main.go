// Command revela-field is the model-free, local-first USB Field Engine.
package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/musombi123/revela-field-engine/internal/contract"
	"github.com/musombi123/revela-field-engine/internal/guardian"
	"github.com/musombi123/revela-field-engine/internal/inventory"
	"github.com/musombi123/revela-field-engine/internal/simulate"
	"github.com/musombi123/revela-field-engine/internal/vulnfeed"
)

const version = "0.3.0"

type networkInterface struct {
	Name       string   `json:"name"`
	Up         bool     `json:"up"`
	Loopback   bool     `json:"loopback"`
	Addresses  int      `json:"address_count"`
	TunnelHint bool     `json:"possible_tunnel_interface"`
	Note       string   `json:"note,omitempty"`
}

type systemSnapshot struct {
	CollectedAt time.Time `json:"collected_at"`
	Hostname    string    `json:"hostname"`
	OS          string    `json:"os"`
	Architecture string   `json:"architecture"`
	GoRuntime   string    `json:"go_runtime"`
	CPUCores    int       `json:"cpu_cores"`
}

type coreCheck struct {
	Name       string `json:"name"`
	Endpoint   string `json:"endpoint"`
	Reachable  bool   `json:"reachable"`
	StatusCode int    `json:"status_code,omitempty"`
	Note       string `json:"note"`
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "version":
		fmt.Println("Revela Field Engine", version)
	case "menu":
		err = runMenu()
	case "doctor":
		err = runDoctor()
	case "system":
		err = runSystem()
	case "network":
		err = runNetwork()
	case "audit":
		err = runAudit(os.Args[2:])
	case "simulate":
		err = runSimulate(os.Args[2:])
	case "guardian":
		err = runGuardian(os.Args[2:])
	case "core-status":
		err = runCoreStatus()
	case "core-start":
		err = runCoreStart(os.Args[2:])
	case "sync":
		err = runSync(os.Args[2:])
	case "feed":
		err = runFeed(os.Args[2:])
	case "vuln":
		err = runVulnerabilityScan(os.Args[2:])
	case "help", "-h", "--help":
		usage()
	default:
		usage()
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "ERROR:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Printf(`REVELA FIELD ENGINE %s
Local-first system inspection, evidence triage and safe defence validation.

Commands:
  menu                         Interactive local menu
  doctor                       Check runtime and bundled core executables
  system                       Read a minimal host-system snapshot
  network                      Inspect local interfaces and VPN/proxy indicators
  audit --root DIR --authorized
                               Hash regular files in an explicitly authorised directory
  simulate --scenario NAME     Run an inert synthetic detection exercise
  guardian --action ACTION --scope local|lab --authorized
                               Evaluate a request using the fail-closed policy
  core-status                  Probe only the local ZERO/ONE/TWO health endpoints
  core-start --authorized      Start bundled ZERO/ONE/TWO services on loopback
  sync --finding FILE --url ORIGIN
                               Send one finding to Meta Engineer (REVELA_ADMIN_BEARER required)
  feed verify --file FEED --public-key KEY --fingerprint SHA256
                               Verify an offline Ed25519-signed advisory feed
  vuln scan --manifest FILE --feed FILE --public-key KEY --fingerprint SHA256 --authorized
                               Match a local package manifest against the verified offline feed
  version                      Print version

Safe simulation scenarios:
  auth-failure-burst
  startup-entry
  vpn-observation

No command exploits a vulnerability, bypasses a VPN, extracts credentials,
disables security controls, scans external networks, or modifies host settings.
`, version)
}

func emit(value any) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(true)
	return enc.Encode(value)
}

func runDoctor() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	dir := filepath.Dir(exe)
	suffix := ""
	if runtime.GOOS == "windows" {
		suffix = ".exe"
	}
	type component struct {
		Name   string `json:"name"`
		Path   string `json:"path"`
		Present bool  `json:"present"`
		Meaning string `json:"meaning"`
	}
	items := []component{}
	for _, item := range []struct{name, binary string}{
		{"Core-ZERO / USECT", "usect-zero"},
		{"Core-ONE / Genesis", "revela-genesis"},
		{"Core-TWO / Infinite Mind", "revela-mind"},
	} {
		path := filepath.Join(dir, item.binary+suffix)
		_, statErr := os.Stat(path)
		items = append(items, component{
			Name: item.name, Path: path, Present: statErr == nil,
			Meaning: "binary presence only; this is not a runtime health or integration test",
		})
	}
	return emit(map[string]any{
		"product": "Revela Field Engine", "version": version,
		"platform": runtime.GOOS + "/" + runtime.GOARCH,
		"executable_directory": dir,
		"go_runtime": runtime.Version(),
		"core_binaries": items,
		"model_required": false,
		"ollama_required": false,
		"mode": "local_read_only_and_lab_simulation",
	})
}

func runSystem() error {
	host, err := os.Hostname()
	if err != nil {
		host = "unavailable"
	}
	return emit(systemSnapshot{
		CollectedAt: time.Now().UTC(), Hostname: host,
		OS: runtime.GOOS, Architecture: runtime.GOARCH,
		GoRuntime: runtime.Version(), CPUCores: runtime.NumCPU(),
	})
}

func looksLikeTunnel(name string) bool {
	value := strings.ToLower(name)
	for _, hint := range []string{"tun", "tap", "wg", "wireguard", "tailscale", "zerotier", "utun", "ppp", "vpn", "openvpn"} {
		if strings.Contains(value, hint) {
			return true
		}
	}
	return false
}

func runNetwork() error {
	decision := guardian.Evaluate(guardian.Request{Action: "network_metadata", Scope: "local", Authorized: true})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}
	ifaces, err := net.Interfaces()
	if err != nil {
		return err
	}
	sort.Slice(ifaces, func(i, j int) bool { return ifaces[i].Name < ifaces[j].Name })
	out := []networkInterface{}
	for _, iface := range ifaces {
		addrs, _ := iface.Addrs()
		hint := looksLikeTunnel(iface.Name)
		note := ""
		if hint {
			note = "interface name suggests a tunnel; confirm with the device owner and approved network configuration"
		}
		out = append(out, networkInterface{
			Name: iface.Name, Up: iface.Flags&net.FlagUp != 0,
			Loopback: iface.Flags&net.FlagLoopback != 0,
			Addresses: len(addrs), TunnelHint: hint, Note: note,
		})
	}
	proxyVars := []string{"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}
	present := []string{}
	for _, name := range proxyVars {
		if strings.TrimSpace(os.Getenv(name)) != "" {
			present = append(present, name)
		}
	}
	return emit(map[string]any{
		"collected_at": time.Now().UTC(),
		"interfaces": out,
		"proxy_environment_variables_present": present,
		"proxy_values_collected": false,
		"external_requests_made": false,
		"interpretation": "VPN/tunnel indicators are observations only. They do not imply malicious activity and are not used to bypass the tunnel or identify a person.",
	})
}

func runAudit(args []string) error {
	fs := flag.NewFlagSet("audit", flag.ContinueOnError)
	root := fs.String("root", "", "explicit local directory to inventory")
	authorized := fs.Bool("authorized", false, "confirm that you own or are authorised to inspect this directory")
	maxFiles := fs.Int("max-files", inventory.DefaultMaxFiles, "maximum regular files to inventory (1-10000)")
	if err := fs.Parse(args); err != nil { return err }
	decision := guardian.Evaluate(guardian.Request{Action:"file_inventory", Scope:"local", Authorized:*authorized})
	if !decision.Allowed { return errors.New(decision.Reason) }
	if strings.TrimSpace(*root) == "" { return errors.New("--root is required") }
	result, err := inventory.Scan(*root, *maxFiles)
	if err != nil { return err }
	return emit(map[string]any{
		"status":"complete", "guardian":decision, "inventory":result,
		"assessment_boundary":"This is a metadata and SHA-256 inventory, not malware detection, a disk image, or proof that a file is safe.",
	})
}

func runSimulate(args []string) error {
	fs := flag.NewFlagSet("simulate", flag.ContinueOnError)
	name := fs.String("scenario", "", "one of the documented synthetic scenarios")
	findingOut := fs.String("finding-out", "", "optional path to save only the versioned finding JSON for later Meta Engineer sync")
	if err := fs.Parse(args); err != nil { return err }
	decision := guardian.Evaluate(guardian.Request{Action:"adversary_emulation", Scope:"lab", Authorized:true})
	if !decision.Allowed { return errors.New(decision.Reason) }
	report, err := simulate.Run(*name)
	if err != nil { return err }
	if strings.TrimSpace(*findingOut) != "" {
		data, marshalErr := json.MarshalIndent(report.Finding, "", "  ")
		if marshalErr != nil { return marshalErr }
		file, openErr := os.OpenFile(*findingOut, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if openErr != nil { return fmt.Errorf("create finding export without overwriting an existing path: %w", openErr) }
		if _, writeErr := file.Write(append(data, '\n')); writeErr != nil {
			_ = file.Close()
			return fmt.Errorf("write finding export: %w", writeErr)
		}
		if closeErr := file.Close(); closeErr != nil { return closeErr }
	}
	return emit(map[string]any{"guardian":decision, "report":report})
}

func runGuardian(args []string) error {
	fs := flag.NewFlagSet("guardian", flag.ContinueOnError)
	action := fs.String("action", "", "registered action identifier")
	scope := fs.String("scope", "", "local or lab")
	authorized := fs.Bool("authorized", false, "explicit operator authorization")
	if err := fs.Parse(args); err != nil { return err }
	result := guardian.Evaluate(guardian.Request{Action:*action, Scope:*scope, Authorized:*authorized})
	if err := emit(result); err != nil { return err }
	if !result.Allowed { return errors.New("Guardian denied the requested action") }
	return nil
}


func syncHostAllowed(host string) bool {
	host = strings.ToLower(strings.TrimSpace(host))
	if host == "revelaai.onrender.com" {
		return true
	}
	for _, candidate := range strings.Split(os.Getenv("REVELA_FIELD_ALLOWED_SYNC_HOSTS"), ",") {
		if strings.EqualFold(strings.TrimSpace(candidate), host) && host != "" {
			return true
		}
	}
	return false
}


func loadVerifiedFeed(feedPath, publicKeyPath, fingerprint string) (vulnfeed.VerifiedFeed, error) {
	feedBytes, err := vulnfeed.ReadRegularFile(feedPath, vulnfeed.MaxFeedBytes)
	if err != nil {
		return vulnfeed.VerifiedFeed{}, err
	}
	keyBytes, err := vulnfeed.ReadRegularFile(publicKeyPath, 4096)
	if err != nil {
		return vulnfeed.VerifiedFeed{}, err
	}
	publicKey, err := vulnfeed.ParsePublicKey(keyBytes)
	if err != nil {
		return vulnfeed.VerifiedFeed{}, err
	}
	return vulnfeed.VerifyEnvelope(feedBytes, publicKey, fingerprint, time.Now().UTC())
}

func runFeed(args []string) error {
	if len(args) == 0 || args[0] != "verify" {
		return errors.New("usage: feed verify --file FEED --public-key KEY --fingerprint SHA256 --authorized")
	}
	fs := flag.NewFlagSet("feed verify", flag.ContinueOnError)
	feedPath := fs.String("file", "", "signed offline advisory feed envelope")
	keyPath := fs.String("public-key", "", "trusted Ed25519 public key file (hex)")
	fingerprint := fs.String("fingerprint", "", "trusted SHA-256 public-key fingerprint from a separate channel")
	authorized := fs.Bool("authorized", false, "confirm you are authorised to assess this local data")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	decision := guardian.Evaluate(guardian.Request{Action: "safe_vulnerability_check", Scope: "local", Authorized: *authorized})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}
	if *feedPath == "" || *keyPath == "" || *fingerprint == "" {
		return errors.New("--file, --public-key and --fingerprint are required")
	}
	verified, err := loadVerifiedFeed(*feedPath, *keyPath, *fingerprint)
	if err != nil {
		return err
	}
	return emit(map[string]any{
		"status": "verified",
		"feed_id": verified.Feed.FeedID,
		"provider": verified.Feed.Provider,
		"issued_at": verified.Feed.IssuedAt,
		"expires_at": verified.Feed.ExpiresAt,
		"advisory_count": verified.AdvisoryCount,
		"payload_sha256": verified.PayloadSHA256,
		"public_key_sha256": verified.PublicKeySHA256,
		"verified_at": verified.VerifiedAt,
		"guardian": decision,
	})
}

func findingSeverity(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "critical":
		return "critical"
	case "high":
		return "high"
	case "medium":
		return "medium"
	case "low":
		return "low"
	default:
		return "informational"
	}
}

func buildVulnerabilityFinding(match vulnfeed.Match, feed vulnfeed.VerifiedFeed, manifestPath, manifestHash string, manifestBytes int64, now time.Time) contract.Finding {
	identity := feed.Feed.FeedID + "|" + match.Advisory.ID + "|" + match.Package.PackageURL + "|" + match.Package.Version
	sum := sha256.Sum256([]byte(identity))
	recommendation := "Review the vendor advisory and update this package to a supported, remediated release after change approval."
	if len(match.Advisory.FixedVersions) > 0 {
		recommendation = "Review the vendor advisory and plan an update to one of these reported fixed versions: " +
			strings.Join(match.Advisory.FixedVersions, ", ") + ". Validate application compatibility and approve the change before installation."
	}
	summary := match.Advisory.Summary
	if len(match.Advisory.References) > 0 {
		summary += " References: " + strings.Join(match.Advisory.References, " ")
	}
	return contract.Finding{
		SchemaVersion: contract.SchemaVersion,
		ID: "field-" + hex.EncodeToString(sum[:8]),
		Source: "revela-field-engine",
		ObservedAt: now.UTC(),
		Target: match.Package.PackageURL,
		Category: "software_vulnerability",
		Severity: findingSeverity(match.Advisory.Severity),
		Title: match.Advisory.ID + " affects " + match.Package.Name + " " + match.Package.Version,
		Summary: summary,
		Evidence: []contract.Evidence{
			{Kind: "local_package_manifest", Ref: manifestPath + "#" + match.Package.PackageURL, SHA256: manifestHash, Bytes: manifestBytes, Note: "Exact package URL and version found in the supplied local manifest."},
			{Kind: "signed_vulnerability_feed", Ref: "feed://" + feed.Feed.FeedID, SHA256: feed.PayloadSHA256, Note: "Ed25519 signature and pinned public-key fingerprint verified; feed is within its validity period."},
		},
		Recommendation: recommendation,
		Scope: "local",
		Simulated: false,
	}
}

func writeFindings(outDir string, findings []contract.Finding) ([]string, error) {
	if strings.TrimSpace(outDir) == "" {
		return nil, errors.New("output directory is required for file export")
	}
	if err := os.MkdirAll(outDir, 0700); err != nil {
		return nil, fmt.Errorf("create finding output directory: %w", err)
	}
	info, err := os.Lstat(outDir)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return nil, errors.New("finding output directory must be a real directory, not a symlink")
	}
	written := []string{}
	for _, finding := range findings {
		path := filepath.Join(outDir, finding.ID+".json")
		data, err := json.MarshalIndent(finding, "", "  ")
		if err != nil {
			return written, err
		}
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return written, fmt.Errorf("create finding without overwriting an existing file: %w", err)
		}
		if _, err := file.Write(append(data, '\n')); err != nil {
			_ = file.Close()
			return written, err
		}
		if err := file.Close(); err != nil {
			return written, err
		}
		written = append(written, path)
	}
	return written, nil
}

func runVulnerabilityScan(args []string) error {
	if len(args) == 0 || args[0] != "scan" {
		return errors.New("usage: vuln scan --manifest FILE --feed FILE --public-key KEY --fingerprint SHA256 --authorized")
	}
	fs := flag.NewFlagSet("vuln scan", flag.ContinueOnError)
	manifestPath := fs.String("manifest", "", "explicit local package manifest JSON")
	feedPath := fs.String("feed", "", "signed local vulnerability feed")
	keyPath := fs.String("public-key", "", "trusted Ed25519 public key file (hex)")
	fingerprint := fs.String("fingerprint", "", "trusted SHA-256 public-key fingerprint from a separate channel")
	outDir := fs.String("out-dir", "", "optional directory to write one JSON finding per exact match")
	authorized := fs.Bool("authorized", false, "confirm you are authorised to assess this local manifest")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	decision := guardian.Evaluate(guardian.Request{Action: "safe_vulnerability_check", Scope: "local", Authorized: *authorized})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}
	if *manifestPath == "" || *feedPath == "" || *keyPath == "" || *fingerprint == "" {
		return errors.New("--manifest, --feed, --public-key and --fingerprint are required")
	}
	manifestBytes, err := vulnfeed.ReadRegularFile(*manifestPath, vulnfeed.MaxManifestBytes)
	if err != nil {
		return err
	}
	manifest, err := vulnfeed.ParseManifest(manifestBytes)
	if err != nil {
		return err
	}
	verified, err := loadVerifiedFeed(*feedPath, *keyPath, *fingerprint)
	if err != nil {
		return err
	}
	matches := vulnfeed.MatchExact(manifest, verified.Feed)
	manifestSum := sha256.Sum256(manifestBytes)
	now := time.Now().UTC()
	findings := make([]contract.Finding, 0, len(matches))
	for _, match := range matches {
		findings = append(findings, buildVulnerabilityFinding(match, verified, *manifestPath, hex.EncodeToString(manifestSum[:]), int64(len(manifestBytes)), now))
	}
	response := map[string]any{
		"status": "assessment_complete",
		"guardian": decision,
		"feed_id": verified.Feed.FeedID,
		"feed_provider": verified.Feed.Provider,
		"feed_expires_at": verified.Feed.ExpiresAt,
		"feed_payload_sha256": verified.PayloadSHA256,
		"manifest_sha256": hex.EncodeToString(manifestSum[:]),
		"packages_assessed": len(manifest.Packages),
		"advisories_in_feed": verified.AdvisoryCount,
		"exact_matches": len(findings),
		"matching_mode": "exact Package URL and exact version string only",
		"finding_records": findings,
		"software_modified": false,
		"assessment_boundary": "No package ranges, distro backports, aliases or transitive dependency resolution were interpreted. No software was installed, updated, removed or disabled. No network requests were made.",
	}
	if strings.TrimSpace(*outDir) != "" {
		written, err := writeFindings(*outDir, findings)
		if err != nil {
			return err
		}
		response["finding_files"] = written
		delete(response, "finding_records")
	}
	return emit(response)
}

func validateSyncOrigin(raw string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", errors.New("URL must be a clean HTTPS origin or a loopback HTTP origin")
	}
	if parsed.Path != "" && parsed.Path != "/" {
		return "", errors.New("provide the API origin only; the Field Engine appends the Meta Engineer route")
	}
	host := strings.Trim(parsed.Hostname(), "[]")
	loopback := strings.EqualFold(host, "localhost")
	if ip := net.ParseIP(host); ip != nil && ip.IsLoopback() {
		loopback = true
	}
	if parsed.Scheme != "https" && !(parsed.Scheme == "http" && loopback) {
		return "", errors.New("remote Meta Engineer connections require HTTPS; plain HTTP is allowed only for loopback testing")
	}
	if !loopback {
		if parsed.Scheme != "https" {
			return "", errors.New("non-loopback Meta Engineer host must use HTTPS")
		}
		if port := parsed.Port(); port != "" && port != "443" {
			return "", errors.New("remote Meta Engineer connections must use the standard HTTPS port")
		}
		if !syncHostAllowed(host) {
			return "", errors.New("remote Meta Engineer host is not on the approved destination allowlist")
		}
	}
	return strings.TrimRight(parsed.String(), "/"), nil
}

func runSync(args []string) error {
	fs := flag.NewFlagSet("sync", flag.ContinueOnError)
	findingPath := fs.String("finding", "", "path to a single Field Engine finding JSON file")
	origin := fs.String("url", "", "RevelaAI API origin, e.g. https://revelaai.example")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(*findingPath) == "" {
		return errors.New("--finding is required")
	}
	if strings.TrimSpace(*origin) == "" {
		return errors.New("--url is required")
	}
	token := strings.TrimSpace(os.Getenv("REVELA_ADMIN_BEARER"))
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return errors.New("set REVELA_ADMIN_BEARER to an existing authorised RevelaCode administrator bearer session")
	}
	base, err := validateSyncOrigin(*origin)
	if err != nil {
		return err
	}
	parsedBase, _ := url.Parse(base)
	scope := "remote"
	host := strings.Trim(parsedBase.Hostname(), "[]")
	if strings.EqualFold(host, "localhost") {
		scope = "local"
	} else if ip := net.ParseIP(host); ip != nil && ip.IsLoopback() {
		scope = "local"
	}
	decision := guardian.Evaluate(guardian.Request{
		Action: "meta_engineer_sync", Scope: scope, Authorized: true,
	})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}
	info, err := os.Lstat(*findingPath)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() > 65536 {
		return errors.New("finding must be a regular JSON file no larger than 64 KiB")
	}
	input, err := os.Open(*findingPath)
	if err != nil {
		return fmt.Errorf("open finding: %w", err)
	}
	defer input.Close()
	openedInfo, err := input.Stat()
	if err != nil || !openedInfo.Mode().IsRegular() || openedInfo.Size() > 65536 {
		return errors.New("opened finding must be a regular file no larger than 64 KiB")
	}
	data, err := io.ReadAll(io.LimitReader(input, 65537))
	if err != nil {
		return fmt.Errorf("read finding: %w", err)
	}
	if len(data) > 65536 {
		return errors.New("finding exceeded the 64 KiB read limit")
	}
	var finding contract.Finding
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&finding); err != nil {
		return fmt.Errorf("decode finding contract: %w", err)
	}
	idSuffix := strings.TrimPrefix(finding.ID, "field-")
	validID := len(idSuffix) == 16
	for _, r := range idSuffix {
		if !strings.ContainsRune("0123456789abcdef", r) {
			validID = false
			break
		}
	}
	if finding.SchemaVersion != contract.SchemaVersion || finding.Source != "revela-field-engine" ||
		!validID || finding.Title == "" || finding.Target == "" || finding.Recommendation == "" {
		return errors.New("finding does not match the supported Field Engine contract")
	}
	if (finding.Simulated && finding.Scope != "lab") || (!finding.Simulated && finding.Scope != "local") {
		return errors.New("finding scope does not match its simulated/observed state")
	}
	if len(finding.Evidence) > 50 || len(finding.Title) > 240 || len(finding.Summary) > 4000 {
		return errors.New("finding exceeds the supported evidence or text limits")
	}

	endpoint := base + "/api/meta-engineer/fieldkit/findings"
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("create Meta Engineer request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	client := &http.Client{
		Timeout: 12 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("Meta Engineer sync failed: %w", err)
	}
	defer resp.Body.Close()
	responseBody, readErr := io.ReadAll(io.LimitReader(resp.Body, 16385))
	if readErr != nil {
		return fmt.Errorf("read Meta Engineer response: %w", readErr)
	}
	if len(responseBody) > 16384 {
		return errors.New("Meta Engineer response exceeded the 16 KiB limit")
	}
	if resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("Meta Engineer rejected the finding (HTTP %d); verify administrator access and the API deployment", resp.StatusCode)
	}
	return emit(map[string]any{
		"status": "submitted_for_review",
		"http_status": resp.StatusCode,
		"finding_id": finding.ID,
		"simulated": finding.Simulated,
		"repair_executed": false,
		"response": strings.TrimSpace(string(responseBody)),
	})
}


type coreServiceSpec struct {
	Name string
	Binary string
	Args []string
	Endpoint string
}

func randomSecret() (string, error) {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

func portableRootFromExecutable() (string, string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", "", err
	}
	binDir := filepath.Dir(exe)
	platformDir := filepath.Base(binDir)
	if platformDir != "windows-amd64" && platformDir != "linux-amd64" {
		return "", "", fmt.Errorf("unsupported USB binary directory %q", platformDir)
	}
	// Executable layout: portable/bin/<os>-<arch>/revela-field[.exe]
	root := filepath.Dir(filepath.Dir(binDir))
	return root, platformDir, nil
}

func minimalCoreEnvironment(overrides map[string]string) []string {
	allowed := map[string]bool{
		"PATH": true, "HOME": true, "USERPROFILE": true, "HOMEDRIVE": true, "HOMEPATH": true,
		"SystemRoot": true, "WINDIR": true, "COMSPEC": true, "PATHEXT": true,
		"TEMP": true, "TMP": true, "TMPDIR": true, "APPDATA": true, "LOCALAPPDATA": true,
		"LANG": true, "LC_ALL": true, "TZ": true,
		// Preserve the existing owner-recipe enforcement gate; never copy the key itself.
		"REVELA_UNCOPYABLE_ENFORCE": true, "REVELA_MASTER_KEY_PATH": true, "REVELA_RECIPE_EXPECTED_SHA256": true,
	}
	values := map[string]string{}
	for _, item := range os.Environ() {
		key, value, ok := strings.Cut(item, "=")
		if ok && allowed[key] {
			values[key] = value
		}
	}
	for key, value := range overrides {
		values[key] = value
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	env := make([]string, 0, len(keys))
	for _, key := range keys {
		env = append(env, key+"="+values[key])
	}
	return env
}

func waitForCoreHealth(ctx context.Context, name, endpoint string, exits <-chan error) error {
	deadline := time.NewTimer(40 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	client := &http.Client{
		Timeout: 900 * time.Millisecond,
		Transport: &http.Transport{Proxy: nil},
	}
	for {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		if req != nil {
			resp, err := client.Do(req)
			if err == nil {
				_ = resp.Body.Close()
				if resp.StatusCode >= 200 && resp.StatusCode < 300 {
					return nil
				}
			}
		}
		select {
		case err := <-exits:
			return fmt.Errorf("%s exited before becoming healthy: %w", name, err)
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			return fmt.Errorf("%s health check timed out at %s", name, endpoint)
		case <-ticker.C:
		}
	}
}

func runCoreStart(args []string) error {
	fs := flag.NewFlagSet("core-start", flag.ContinueOnError)
	authorized := fs.Bool("authorized", false, "confirm you are authorised to start local RevelaAI core services on this computer")
	if err := fs.Parse(args); err != nil {
		return err
	}
	decision := guardian.Evaluate(guardian.Request{Action: "start_local_core_services", Scope: "local", Authorized: *authorized})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}

	root, platformDir, err := portableRootFromExecutable()
	if err != nil {
		return err
	}
	runtimeRoot := filepath.Join(root, "runtime-source")
	for _, required := range []string{
		filepath.Join(runtimeRoot, "core-zero", "go.mod"),
		filepath.Join(runtimeRoot, "core-zero", "guardian", "rules.yaml"),
		filepath.Join(runtimeRoot, "core-zero", "guardian", "worldwide_rules.yaml"),
		filepath.Join(runtimeRoot, "core-one", "go.mod"),
		filepath.Join(runtimeRoot, "core-one", "guardian", "rules.yaml"),
		filepath.Join(runtimeRoot, "core-two", "go.mod"),
		filepath.Join(runtimeRoot, "core-two", "guardian", "rules.yaml"),
	} {
		if info, statErr := os.Stat(required); statErr != nil || info.IsDir() {
			return fmt.Errorf("USB core runtime source is incomplete; missing %s", required)
		}
	}
	suffix := ""
	if runtime.GOOS == "windows" {
		suffix = ".exe"
	}

	zeroToken, err := randomSecret()
	if err != nil { return err }
	genesisToken, err := randomSecret()
	if err != nil { return err }
	mindToken, err := randomSecret()
	if err != nil { return err }

	logDir := filepath.Join(root, "data", "logs")
	zeroDataDir := filepath.Join(root, "data", "runtime", "core-zero")
	for _, dir := range []string{logDir, zeroDataDir} {
		if err := os.MkdirAll(dir, 0700); err != nil {
			return fmt.Errorf("prepare USB runtime directory: %w", err)
		}
	}

	overrides := map[string]string{
		"USECT_ZERO_ADMIN_TOKEN": zeroToken,
		"GENESIS_ADMIN_TOKEN": genesisToken,
		"MIND_ADMIN_TOKEN": mindToken,
		"USECT_ZERO_DATA_DIR": zeroDataDir,
		"USECT_ZERO_BASE_URL": "http://127.0.0.1:8780",
		"GENESIS_BASE_URL": "http://127.0.0.1:8781",
		"MIND_AUTO_EVOLVE": "0",
	}
	childEnv := minimalCoreEnvironment(overrides)
	specs := []coreServiceSpec{
		{
			Name: "Core-ZERO", Binary: "usect-zero" + suffix,
			Args: []string{"-mode", "serve", "-root", runtimeRoot, "-listen", "127.0.0.1:8780"},
			Endpoint: "http://127.0.0.1:8780/v1/health",
		},
		{
			Name: "Core-ONE / Genesis", Binary: "revela-genesis" + suffix,
			Args: []string{"-mode", "serve", "-repo-root", runtimeRoot, "-listen", "127.0.0.1:8781"},
			Endpoint: "http://127.0.0.1:8781/v1/genesis/health",
		},
		{
			Name: "Core-TWO / Infinite Mind", Binary: "revela-mind" + suffix,
			Args: []string{"-daemon", "-repo-root", runtimeRoot, "-listen", "127.0.0.1:8782", "-interval", "24h"},
			Endpoint: "http://127.0.0.1:8782/v1/mind/health",
		},
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	exits := make(chan error, len(specs))
	var waiters sync.WaitGroup
	children := []*exec.Cmd{}
	shutdown := func() {
		cancel()
		for _, child := range children {
			if child.Process != nil {
				_ = child.Process.Kill()
			}
		}
		waiters.Wait()
	}

	for _, spec := range specs {
		binaryPath := filepath.Join(root, "bin", platformDir, spec.Binary)
		if info, statErr := os.Stat(binaryPath); statErr != nil || !info.Mode().IsRegular() {
			shutdown()
			return fmt.Errorf("required bundled core binary is missing: %s", binaryPath)
		}
		logPath := filepath.Join(logDir, strings.ToLower(strings.ReplaceAll(spec.Name, " / ", "-"))+".log")
		logFile, openErr := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if openErr != nil {
			shutdown()
			return fmt.Errorf("open core log for %s: %w", spec.Name, openErr)
		}
		cmd := exec.CommandContext(ctx, binaryPath, spec.Args...)
		cmd.Dir = runtimeRoot
		cmd.Env = childEnv
		cmd.Stdout = logFile
		cmd.Stderr = logFile
		if startErr := cmd.Start(); startErr != nil {
			_ = logFile.Close()
			shutdown()
			return fmt.Errorf("start %s: %w", spec.Name, startErr)
		}
		children = append(children, cmd)
		waiters.Add(1)
		go func(name string, child *exec.Cmd, logHandle *os.File) {
			defer waiters.Done()
			waitErr := child.Wait()
			_ = logHandle.Close()
			if waitErr != nil {
				exits <- fmt.Errorf("%s stopped: %w", name, waitErr)
			} else {
				exits <- fmt.Errorf("%s stopped unexpectedly", name)
			}
		}(spec.Name, cmd, logFile)

		if healthErr := waitForCoreHealth(ctx, spec.Name, spec.Endpoint, exits); healthErr != nil {
			shutdown()
			return healthErr
		}
		fmt.Printf("%s healthy at %s\n", spec.Name, spec.Endpoint)
	}

	fmt.Println("All three USECT cores are reachable on loopback. No provider credentials were inherited.")
	fmt.Println("Guardian remains enabled; Mind auto-evolution is disabled. Press Ctrl+C to stop the local stack.")
	select {
	case <-ctx.Done():
		fmt.Println("Stopping local USECT core stack...")
		shutdown()
		return nil
	case childErr := <-exits:
		shutdown()
		return childErr
	}
}

func runCoreStatus() error {
	decision := guardian.Evaluate(guardian.Request{
		Action: "core_health_probe", Scope: "local", Authorized: true,
	})
	if !decision.Allowed {
		return errors.New(decision.Reason)
	}
	type target struct{name, address, path string}
	targets := []target{
		{"Core-ZERO", "127.0.0.1:8780", "/v1/health"},
		{"Core-ONE / Genesis", "127.0.0.1:8781", "/v1/genesis/health"},
		{"Core-TWO / Infinite Mind", "127.0.0.1:8782", "/v1/mind/health"},
	}
	client := &http.Client{
		Timeout: 1200 * time.Millisecond,
		Transport: &http.Transport{Proxy:nil},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	checks := []coreCheck{}
	for _, target := range targets {
		endpoint := "http://" + target.address + target.path
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		resp, err := client.Do(req)
		check := coreCheck{Name:target.name, Endpoint:endpoint, Note:"loopback probe only"}
		if err != nil {
			check.Note = "not reachable; this does not prove the core binary is broken"
		} else {
			check.StatusCode = resp.StatusCode
			check.Reachable = resp.StatusCode >= 200 && resp.StatusCode < 300
			_ = resp.Body.Close()
			if !check.Reachable { check.Note = "endpoint responded but did not return a successful status" }
		}
		checks = append(checks, check)
	}
	return emit(map[string]any{
		"checked_at":time.Now().UTC(), "targets":"loopback only",
		"checks":checks,
		"warning":"Reachability is not proof of Guardian enforcement, authenticated write access, or cross-core correctness. Run the repository CI and integration tests for that.",
	})
}

func runMenu() error {
	reader := bufio.NewReader(os.Stdin)
	for {
		fmt.Println()
		fmt.Println("REVELA FIELD ENGINE", version)
		fmt.Println("1) System snapshot")
		fmt.Println("2) Network / VPN visibility")
		fmt.Println("3) Synthetic adversary-emulation exercise")
		fmt.Println("4) Inventory an authorised local directory")
		fmt.Println("5) Core health status (loopback only)")
		fmt.Println("6) Start bundled ZERO/ONE/TWO locally")
		fmt.Println("0) Exit")
		fmt.Print("Select: ")
		value, err := reader.ReadString('\n')
		if err != nil { return err }
		switch strings.TrimSpace(value) {
		case "1":
			if err := runSystem(); err != nil { return err }
		case "2":
			if err := runNetwork(); err != nil { return err }
		case "3":
			fmt.Println("Scenarios: auth-failure-burst | startup-entry | vpn-observation")
			fmt.Print("Scenario: ")
			scenarioName, readErr := reader.ReadString('\n')
			if readErr != nil { return readErr }
			if err := runSimulate([]string{"--scenario", strings.TrimSpace(scenarioName)}); err != nil { fmt.Println(err) }
		case "4":
			fmt.Print("Directory path (must be yours or explicitly authorised): ")
			path, readErr := reader.ReadString('\n')
			if readErr != nil { return readErr }
			fmt.Print("Type AUTHORISED to confirm the scope: ")
			confirmation, readErr := reader.ReadString('\n')
			if readErr != nil { return readErr }
			if strings.TrimSpace(confirmation) != "AUTHORISED" { fmt.Println("Cancelled."); continue }
			if err := runAudit([]string{"--root", strings.TrimSpace(path), "--authorized"}); err != nil { fmt.Println(err) }
		case "5":
			if err := runCoreStatus(); err != nil { return err }
		case "6":
			fmt.Print("Starting services on loopback will write runtime logs/state to this USB. Type START to continue: ")
			confirmation, readErr := reader.ReadString('\n')
			if readErr != nil { return readErr }
			if strings.TrimSpace(confirmation) != "START" { fmt.Println("Cancelled."); continue }
			if err := runCoreStart([]string{"--authorized"}); err != nil { fmt.Println(err) }
		case "0":
			return nil
		default:
			fmt.Println("Choose one of the listed options.")
		}
	}
}
