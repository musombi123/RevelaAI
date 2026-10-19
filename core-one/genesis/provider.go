package genesis

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	providerHeartbeatPath = "/v1/genesis/provider/heartbeat"

	defaultProviderInterval = 24 * time.Hour
	minProviderInterval     = time.Minute
	maxProviderInterval     = 30 * 24 * time.Hour
	providerRequestTimeout  = 8 * time.Second

	maxProviderResponseBytes = 1 << 20
	maxProviderDemandCount   = 32
	maxProviderDemandBytes   = 4000
	maxProviderGraphBytes    = 256 * 1024
	maxProviderLawsBytes     = 256 * 1024
	maxProviderKeyBytes      = 16 * 1024
)

type providerHeartbeat struct {
	Core              string    `json:"core"`
	Version           string    `json:"version"`
	At                time.Time `json:"at"`
	Mode              string    `json:"mode"`
	ModelConfigured   bool      `json:"model_configured"`
	PendingInventions int       `json:"pending_inventions"`
	GuardianPolicy    string    `json:"guardian_policy"`
}

type providerResponse struct {
	Demands []struct {
		Demand string `json:"demand"`
		Source string `json:"source"`
	} `json:"demands"`

	Graph json.RawMessage `json:"graph,omitempty"`
	Laws  json.RawMessage `json:"laws,omitempty"`
}

// RunProviderLoop enables optional provider synchronization only when
// REVELACODE_PROVIDER_URL is configured.
//
// Incoming demands still pass through the local queue and its Guardian
// validation. Graph and law documents are stored only as review proposals.
// Provider content is never applied directly to executable code or local
// Guardian policy.
func (e *Engine) RunProviderLoop(ctx context.Context) {
	if e == nil {
		return
	}

	if ctx == nil {
		ctx = context.Background()
	}

	rawBase := strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_URL"))
	if rawBase == "" {
		// Standalone mode: do not make provider network calls.
		return
	}

	base, err := validateProviderBaseURL(rawBase)
	if err != nil {
		e.publish(Event{
			Type:    "provider_configuration_invalid",
			At:      time.Now().UTC(),
			Message: "Optional provider synchronization is disabled because its URL configuration is invalid.",
			Status:  "configuration_error",
		})
		return
	}

	interval := configuredProviderInterval(
		os.Getenv("REVELACODE_PROVIDER_INTERVAL"),
	)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		if ctx.Err() != nil {
			return
		}

		_ = e.providerHeartbeat(ctx, base)

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func configuredProviderInterval(raw string) time.Duration {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return defaultProviderInterval
	}

	parsed, err := time.ParseDuration(raw)
	if err != nil {
		return defaultProviderInterval
	}

	if parsed < minProviderInterval || parsed > maxProviderInterval {
		return defaultProviderInterval
	}

	return parsed
}

// validateProviderBaseURL checks the base URL before any credentials or
// heartbeat data are sent to it.
func validateProviderBaseURL(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("provider URL is empty")
	}

	u, err := url.Parse(raw)
	if err != nil {
		return "", errors.New("provider URL is malformed")
	}

	scheme := strings.ToLower(u.Scheme)
	if scheme != "https" && scheme != "http" {
		return "", errors.New("provider URL must use HTTP or HTTPS")
	}

	if u.Opaque != "" || u.Host == "" || u.Hostname() == "" {
		return "", errors.New("provider URL must contain a valid hostname")
	}

	if u.User != nil {
		return "", errors.New("provider URL must not contain embedded credentials")
	}

	if u.RawQuery != "" || u.ForceQuery {
		return "", errors.New("provider base URL must not contain a query string")
	}

	if u.Fragment != "" {
		return "", errors.New("provider base URL must not contain a fragment")
	}

	if strings.ContainsAny(u.Host, "\r\n\t ") {
		return "", errors.New("provider URL contains invalid host characters")
	}

	if scheme == "http" && !isLocalProviderHost(u.Hostname()) {
		return "", errors.New("remote provider URLs must use HTTPS")
	}

	u.Scheme = scheme
	u.Path = strings.TrimRight(u.Path, "/")
	u.RawPath = ""

	normalized := strings.TrimRight(u.String(), "/")
	if normalized == "" {
		return "", errors.New("provider URL is invalid")
	}

	return normalized, nil
}

func isLocalProviderHost(host string) bool {
	host = strings.TrimSpace(strings.Trim(host, "[]"))

	if strings.EqualFold(host, "localhost") {
		return true
	}

	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// providerHeartbeat synchronizes the heartbeat and processes bounded,
// untrusted provider data. Any failure is reported without disrupting the
// rest of Genesis's standalone operation.
func (e *Engine) providerHeartbeat(
	ctx context.Context,
	base string,
) (retErr error) {
	if e == nil {
		return errors.New("provider heartbeat requires an initialized engine")
	}

	defer func() {
		if retErr != nil {
			e.publish(Event{
				Type:    "provider_sync_failed",
				At:      time.Now().UTC(),
				Message: "Optional provider synchronization failed; local standalone operation remains available.",
				Status:  "retry_on_next_interval",
			})
		}
	}()

	if ctx == nil {
		ctx = context.Background()
	}

	base, err := validateProviderBaseURL(base)
	if err != nil {
		return fmt.Errorf("validate provider URL: %w", err)
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	items, listErr := e.ListInventions()
	pending := 0

	if listErr == nil {
		for _, item := range items {
			if item["status"] == "await_merge" {
				pending++
			}
		}
	}

	payload := providerHeartbeat{
		Core:              "REVELA-GENESIS",
		Version:           Version,
		At:                time.Now().UTC(),
		Mode:              "standalone-compatible",
		ModelConfigured:   strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL")) != "",
		PendingInventions: pending,
		GuardianPolicy:    sha256String(defaultGuardianRules),
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode provider heartbeat: %w", err)
	}

	endpoint := base + providerHeartbeatPath

	requestCtx, cancel := context.WithTimeout(ctx, providerRequestTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(
		requestCtx,
		http.MethodPost,
		endpoint,
		bytes.NewReader(body),
	)
	if err != nil {
		return fmt.Errorf("create provider heartbeat request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "RevelaGenesis/"+Version)

	key := strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_KEY"))
	if strings.ContainsAny(key, "\r\n") {
		return errors.New("provider API key contains invalid header characters")
	}
	if len(key) > maxProviderKeyBytes {
		return errors.New("provider API key exceeds the safe size limit")
	}
	if key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
	}

	client := newProviderHTTPClient()

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("send provider heartbeat: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK ||
		resp.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("provider heartbeat returned HTTP %d", resp.StatusCode)
	}

	if resp.ContentLength > maxProviderResponseBytes {
		return errors.New("provider response exceeds the safe size limit")
	}

	responseBytes, err := io.ReadAll(
		io.LimitReader(resp.Body, maxProviderResponseBytes+1),
	)
	if err != nil {
		return fmt.Errorf("read provider response: %w", err)
	}

	if len(responseBytes) > maxProviderResponseBytes {
		return errors.New("provider response exceeds the safe size limit")
	}

	if !utf8.Valid(responseBytes) {
		return errors.New("provider response is not valid UTF-8")
	}

	var updates providerResponse
	if err := json.Unmarshal(responseBytes, &updates); err != nil {
		return fmt.Errorf("decode provider response: %w", err)
	}

	if len(updates.Demands) > maxProviderDemandCount {
		e.publish(Event{
			Type:    "provider_demands_truncated",
			At:      time.Now().UTC(),
			Message: "Provider response exceeded the demand count limit; excess demands were rejected.",
			Status:  "rejected",
		})

		updates.Demands = updates.Demands[:maxProviderDemandCount]
	}

	// Provider-supplied source labels are intentionally not trusted as local
	// provenance. Every imported demand is attributed to the configured
	// integration, and Enqueue remains the local validation boundary.
	for _, incoming := range updates.Demands {
		demand, valid := validateProviderDemand(incoming.Demand)
		if !valid {
			e.publish(Event{
				Type:    "provider_demand_rejected",
				At:      time.Now().UTC(),
				Message: "Provider demand was rejected because its content was empty, malformed, or exceeded local limits.",
				Status:  "blocked_or_invalid",
			})
			continue
		}

		if _, err := e.Enqueue(demand, "revelacode-provider"); err != nil {
			e.publish(Event{
				Type:    "provider_demand_rejected",
				At:      time.Now().UTC(),
				Message: "Provider demand rejected by local Guardian or queue validation.",
				Status:  "blocked_or_invalid",
			})
		}
	}

	if len(updates.Graph) > 0 || len(updates.Laws) > 0 {
		if len(updates.Graph) > maxProviderGraphBytes {
			return errors.New("provider graph proposal exceeds the safe size limit")
		}
		if len(updates.Laws) > maxProviderLawsBytes {
			return errors.New("provider law proposal exceeds the safe size limit")
		}

		proposal := map[string]any{
			"schema_version": 1,
			"received_at":    time.Now().UTC(),
			"received_from":  "revelacode-provider",
			"graph":          updates.Graph,
			"laws":           updates.Laws,
			"status":         "pending_human_review",
			"trust":          "untrusted_external_proposal",
			"note": "Provider updates are proposals only. They are not merged into executable code, " +
				"not treated as verified policy, and cannot weaken local Guardian rules automatically.",
		}

		if _, err := e.writeProviderProposal(proposal); err != nil {
			return fmt.Errorf("store provider review proposal: %w", err)
		}
	}

	e.publish(Event{
		Type:    "provider_heartbeat",
		At:      time.Now().UTC(),
		Message: "Optional RevelaCode provider synchronization completed.",
		Status:  "ok",
	})

	return nil
}

// newProviderHTTPClient enforces request timeouts and disables redirects.
// A provider must answer from the configured endpoint instead of redirecting
// requests carrying potentially sensitive heartbeat data or credentials.
func newProviderHTTPClient() *http.Client {
	return &http.Client{
		Timeout: providerRequestTimeout,
		CheckRedirect: func(
			_ *http.Request,
			_ []*http.Request,
		) error {
			return http.ErrUseLastResponse
		},
	}
}

func validateProviderDemand(raw string) (string, bool) {
	if !utf8.ValidString(raw) {
		return "", false
	}

	raw = strings.TrimSpace(raw)
	if raw == "" || len(raw) > maxProviderDemandBytes {
		return "", false
	}

	for _, r := range raw {
		if unicode.IsControl(r) && r != '\n' && r != '\r' && r != '\t' {
			return "", false
		}
	}

	// Normalize whitespace without changing the core wording of the demand.
	raw = strings.Join(strings.Fields(raw), " ")
	if raw == "" {
		return "", false
	}

	return raw, true
}

// writeProviderProposal stores an external graph/law update in an exclusive,
// review-only file. O_EXCL prevents a timestamp collision from overwriting a
// previously received proposal.
func (e *Engine) writeProviderProposal(
	proposal map[string]any,
) (string, error) {
	if e == nil || strings.TrimSpace(e.CoreRoot) == "" {
		return "", errors.New("engine core root is not configured")
	}

	directory := filepath.Join(e.CoreRoot, "state", "provider")

	if err := os.MkdirAll(directory, 0o700); err != nil {
		return "", fmt.Errorf("create provider proposal directory: %w", err)
	}

	info, err := os.Lstat(directory)
	if err != nil {
		return "", fmt.Errorf("inspect provider proposal directory: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("provider proposal directory must be a regular directory, not a symlink")
	}

	raw, err := json.MarshalIndent(proposal, "", "  ")
	if err != nil {
		return "", fmt.Errorf("encode provider proposal: %w", err)
	}
	if len(raw) > maxProviderGraphBytes+maxProviderLawsBytes+(64*1024) {
		return "", errors.New("combined provider proposal exceeds the safe size limit")
	}

	stamp := time.Now().UTC().Format("20060102T150405.000000000Z")

	for attempt := 0; attempt < 3; attempt++ {
		suffix := ""
		if attempt > 0 {
			suffix = fmt.Sprintf("_%d", attempt)
		}

		name := "updates_" + stamp + suffix + ".json"
		path := filepath.Join(directory, name)

		file, err := os.OpenFile(
			path,
			os.O_CREATE|os.O_EXCL|os.O_WRONLY,
			0o600,
		)
		if err != nil {
			if errors.Is(err, os.ErrExist) {
				continue
			}
			return "", fmt.Errorf("create provider proposal file: %w", err)
		}

		if err := file.Chmod(0o600); err != nil {
			_ = file.Close()
			_ = os.Remove(path)
			return "", fmt.Errorf("secure provider proposal permissions: %w", err)
		}

		_, writeErr := file.Write(append(raw, '\n'))
		if writeErr == nil {
			writeErr = file.Sync()
		}
		closeErr := file.Close()

		if writeErr != nil {
			_ = os.Remove(path)
			return "", fmt.Errorf("write provider proposal: %w", writeErr)
		}
		if closeErr != nil {
			_ = os.Remove(path)
			return "", fmt.Errorf("close provider proposal: %w", closeErr)
		}

		return path, nil
	}

	return "", errors.New("could not allocate a unique provider proposal filename")
}
