package genesis

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// OpenAICompatibleAdapter is optional. The engine remains fully operational when no model is configured.
// Model output is treated as untrusted metadata; model-generated source is never executed or copied into code files.
type OpenAICompatibleAdapter struct {
	Endpoint string
	APIKey   string
	Model    string
	Client   *http.Client
}

func NewConfiguredModelAdapter() ModelAdapter {
	endpoint := strings.TrimSpace(os.Getenv("GENESIS_MODEL_BASE_URL"))
	if endpoint == "" {
		return nil
	}
	if !strings.HasSuffix(endpoint, "/chat/completions") {
		endpoint = strings.TrimRight(endpoint, "/")
		if strings.HasSuffix(endpoint, "/v1") {
			endpoint += "/chat/completions"
		} else {
			endpoint += "/v1/chat/completions"
		}
	}
	model := strings.TrimSpace(os.Getenv("GENESIS_MODEL_NAME"))
	if model == "" {
		model = "existing-revelaai-model"
	}
	return &OpenAICompatibleAdapter{Endpoint: endpoint, APIKey: strings.TrimSpace(os.Getenv("GENESIS_MODEL_API_KEY")), Model: model, Client: &http.Client{Timeout: 20 * time.Second}}
}

func (a *OpenAICompatibleAdapter) Suggest(ctx context.Context, demand string, evidence ResearchEvidence, fallback ToolSpec) (ToolSpec, error) {
	if a == nil || a.Endpoint == "" {
		return fallback, nil
	}
	u, err := url.Parse(a.Endpoint)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" {
		return fallback, errors.New("model endpoint must be a valid http(s) URL")
	}
	if u.Scheme == "http" && u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1" && u.Hostname() != "::1" {
		return fallback, errors.New("non-local model endpoints must use HTTPS")
	}
	evidenceJSON, _ := json.Marshal(map[string]any{"query": evidence.Query, "findings": evidence.Findings, "sources": evidence.Sources[:min(8, len(evidence.Sources))]})
	fallbackJSON, _ := json.Marshal(fallback)
	prompt := "Return ONLY JSON with keys title, purpose, capabilities, inputs, outputs, category, industry, safeguards. Do not return source code or commands. Demand: " + limitText(demand, 1000) + "\nFallback specification: " + string(fallbackJSON) + "\nResearch evidence: " + limitText(string(evidenceJSON), 6000) + "\nRules: no weapons, warfare, malware, privacy violations, or illegal operation; hardware requires human review and consent. Keep string fields concise."
	body, _ := json.Marshal(map[string]any{"model": a.Model, "temperature": 0, "messages": []any{map[string]string{"role": "system", "content": "You assist a safe tool-specification engine. Output JSON metadata only; do not provide executable source."}, map[string]string{"role": "user", "content": prompt}}, "response_format": map[string]string{"type": "json_object"}})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.Endpoint, bytes.NewReader(body))
	if err != nil {
		return fallback, err
	}
	req.Header.Set("Content-Type", "application/json")
	if a.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+a.APIKey)
	}
	client := a.Client
	if client == nil {
		client = &http.Client{Timeout: 20 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return fallback, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fallback, fmt.Errorf("model endpoint returned HTTP %d", resp.StatusCode)
	}
	var envelope struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&envelope); err != nil {
		return fallback, err
	}
	if len(envelope.Choices) == 0 {
		return fallback, errors.New("model response contained no choices")
	}
	var suggestion struct {
		Title        string   `json:"title"`
		Purpose      string   `json:"purpose"`
		Category     string   `json:"category"`
		Industry     string   `json:"industry"`
		Capabilities []string `json:"capabilities"`
		Inputs       []string `json:"inputs"`
		Outputs      []string `json:"outputs"`
		Safeguards   []string `json:"safeguards"`
	}
	if err := json.Unmarshal([]byte(envelope.Choices[0].Message.Content), &suggestion); err != nil {
		return fallback, err
	}
	out := fallback
	if v := cleanModelString(suggestion.Title, 120); v != "" {
		out.Title = v
	}
	if v := cleanModelString(suggestion.Purpose, 500); v != "" {
		out.Purpose = v
	}
	// Category, industry, and hardware-guide requirements stay anchored to the deterministic demand classification.
	// A model may enrich metadata, but cannot reclassify the hardware/safety boundary.
	out.Capabilities = cleanModelList(suggestion.Capabilities, 8, 120, fallback.Capabilities)
	out.Inputs = cleanModelList(suggestion.Inputs, 8, 120, fallback.Inputs)
	out.Outputs = cleanModelList(suggestion.Outputs, 8, 120, fallback.Outputs)
	out.Safeguards = cleanModelList(suggestion.Safeguards, 8, 180, fallback.Safeguards)
	out.ModelAssisted = true
	out.ModelNote = "Model contributed bounded specification metadata; executable source was generated from reviewed templates."
	return out, nil
}

func cleanModelString(s string, max int) string {
	s = limitText(s, max)
	if len(s) == 0 {
		return ""
	}
	for _, r := range s {
		if r < 32 && r != '\t' {
			return ""
		}
	}
	return s
}
func cleanModelList(in []string, maxItems, maxLen int, fallback []string) []string {
	out := make([]string, 0, min(maxItems, len(in)))
	for _, raw := range in {
		v := cleanModelString(raw, maxLen)
		if v != "" {
			out = append(out, v)
		}
		if len(out) >= maxItems {
			break
		}
	}
	if len(out) == 0 {
		return append([]string{}, fallback...)
	}
	return out
}
