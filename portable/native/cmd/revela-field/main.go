// Command revela-field is the model-free, local-first USB Field Engine.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/musombi123/revela-field-engine/internal/contract"
	"github.com/musombi123/revela-field-engine/internal/guardian"
	"github.com/musombi123/revela-field-engine/internal/inventory"
	"github.com/musombi123/revela-field-engine/internal/simulate"
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
	case "sync":
		err = runSync(os.Args[2:])
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
  sync --finding FILE --url ORIGIN
                               Send one finding to Meta Engineer (REVELA_ADMIN_BEARER required)
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
	if parsed.Scheme != "https" && !loopback {
		return "", errors.New("non-loopback Meta Engineer host must use HTTPS")
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
	info, err := os.Lstat(*findingPath)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() > 65536 {
		return errors.New("finding must be a regular JSON file no larger than 64 KiB")
	}
	data, err := os.ReadFile(*findingPath)
	if err != nil {
		return fmt.Errorf("read finding: %w", err)
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

func runCoreStatus() error {
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
		case "0":
			return nil
		default:
			fmt.Println("Choose one of the listed options.")
		}
	}
}
