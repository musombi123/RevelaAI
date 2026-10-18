package genesis

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
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

// RunProviderLoop is opt-in: when RevelaCodeProvider URL is not set, standalone mode makes no
// provider calls. Updates received from the provider are stored as proposals; policy rules are never
// weakened by an inbound graph/law document.
func (e *Engine) RunProviderLoop(ctx context.Context) {
	base := strings.TrimRight(strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_URL")), "/")
	if base == "" {
		return
	}
	interval := 24 * time.Hour
	if raw := strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_INTERVAL")); raw != "" {
		if parsed, err := time.ParseDuration(raw); err == nil && parsed >= time.Minute {
			interval = parsed
		}
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		_ = e.providerHeartbeat(ctx, base)
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (e *Engine) providerHeartbeat(ctx context.Context, base string) error {
	items, _ := e.ListInventions()
	pending := 0
	for _, item := range items {
		if item["status"] == "await_merge" {
			pending++
		}
	}
	policy := sha256String(defaultGuardianRules)
	payload := providerHeartbeat{Core: "REVELA-GENESIS", Version: Version, At: time.Now().UTC(), Mode: "standalone-compatible", ModelConfigured: os.Getenv("GENESIS_MODEL_BASE_URL") != "", PendingInventions: pending, GuardianPolicy: policy}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/v1/genesis/provider/heartbeat", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "RevelaGenesis/"+Version)
	if key := strings.TrimSpace(os.Getenv("REVELACODE_PROVIDER_KEY")); key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
	}
	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		e.publish(Event{Type: "provider_unavailable", At: time.Now().UTC(), Message: "Optional RevelaCode provider heartbeat failed; standalone operation remains available.", Status: "retry_on_next_interval"})
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("provider heartbeat returned HTTP %d", resp.StatusCode)
	}
	var updates providerResponse
	if err := json.NewDecoder(resp.Body).Decode(&updates); err != nil {
		return err
	}
	if len(updates.Demands) > 0 {
		for _, d := range updates.Demands {
			if _, err := e.Enqueue(d.Demand, "revelacode-provider"); err != nil {
				e.publish(Event{Type: "provider_demand_rejected", At: time.Now().UTC(), Message: "Provider demand rejected by local Guardian or queue validation.", Status: "blocked_or_invalid"})
			}
		}
	}
	if len(updates.Graph) > 0 || len(updates.Laws) > 0 {
		proposal := map[string]any{"received_at": time.Now().UTC(), "graph": updates.Graph, "laws": updates.Laws, "status": "pending_human_review", "note": "Provider updates are proposed only; they are not merged into executable code or used to weaken Guardian rules."}
		if err := writeJSON(filepath.Join(e.CoreRoot, "state", "provider", "updates_"+time.Now().UTC().Format("20060102T150405Z")+".json"), proposal); err != nil {
			return err
		}
	}
	e.publish(Event{Type: "provider_heartbeat", At: time.Now().UTC(), Message: "Optional RevelaCode provider synchronization completed.", Status: "ok"})
	return nil
}
