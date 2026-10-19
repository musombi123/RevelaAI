package genesis

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	maxSDKRouteBytes       = 80
	maxSDKActionBytes      = 2000
	maxSDKInputCount       = 100
	maxSDKInputKeyBytes    = 100
	maxSDKInputValueBytes  = 4000
	maxSDKRequestBytes     = 256 * 1024
	maxSDKResponseBytes    = 1 << 20
	maxSDKTokenBytes       = 16 * 1024
	maxIntegrityFileCount  = 10000
	maxIntegrityTotalBytes = int64(512 << 20)
	minIntegrityKeyBytes   = 32
)

// generatedGoSDK produces a standard-library-only Go SDK proposal.
// Generated output uses bounded identifiers and does not interpolate raw,
// untrusted invention names into executable source.
func generatedGoSDK(spec ToolSpec) string {
	route := sdkRouteName(spec.Name)
	display := sdkDisplayName(spec.Name)
	pkg := sdkGoPackageName(route)

	source := `// Generated standard-library-only Go SDK proposal for <<DISPLAY>>.
package <<PACKAGE>>

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
	"strings"
	"time"
	"unicode/utf8"
)

const (
	maxRequestBytes = 256 * 1024
	maxResponseBytes = 1 << 20
	maxActionBytes = 2000
	maxInputCount = 100
	maxInputKeyBytes = 100
	maxInputValueBytes = 4000
	maxTokenBytes = 16 * 1024
)

type Request struct {
	Action  string            <<BT>>json:"action"<<BT>>
	Inputs  map[string]string <<BT>>json:"inputs,omitempty"<<BT>>
	Consent bool              <<BT>>json:"consent,omitempty"<<BT>>
}

type Result struct {
	Status  string <<BT>>json:"status"<<BT>>
	Tool    string <<BT>>json:"tool"<<BT>>
	Summary string <<BT>>json:"summary"<<BT>>
}

type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func New(baseURL, token string) (*Client, error) {
	normalized, err := validateBaseURL(baseURL)
	if err != nil {
		return nil, err
	}
	if strings.ContainsAny(token, "\r\n") || len(token) > maxTokenBytes {
		return nil, errors.New("invalid or oversized API token")
	}

	return &Client{
		BaseURL: normalized,
		Token:   token,
		HTTP: &http.Client{
			Timeout: 10 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}, nil
}

func validateBaseURL(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.Hostname() == "" {
		return "", errors.New("base URL must contain a valid HTTP(S) host")
	}
	if u.Scheme != "https" && u.Scheme != "http" {
		return "", errors.New("base URL must use HTTPS or HTTP")
	}
	if u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return "", errors.New("base URL must not contain credentials, query, or fragment")
	}
	if u.Scheme == "http" && !isLoopback(u.Hostname()) {
		return "", errors.New("HTTPS is required for non-local endpoints")
	}
	u.Path = strings.TrimRight(u.Path, "/")
	u.RawPath = ""
	return strings.TrimRight(u.String(), "/"), nil
}

func isLoopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(strings.Trim(host, "[]"))
	return ip != nil && ip.IsLoopback()
}

func (c *Client) Plan(ctx context.Context, in Request) (Result, error) {
	if c == nil {
		return Result{}, errors.New("client is nil")
	}
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return Result{}, err
	}

	base, err := validateBaseURL(c.BaseURL)
	if err != nil {
		return Result{}, err
	}
	if strings.ContainsAny(c.Token, "\r\n") || len(c.Token) > maxTokenBytes {
		return Result{}, errors.New("invalid or oversized API token")
	}

	in.Action = strings.TrimSpace(in.Action)
	if in.Action == "" || !utf8.ValidString(in.Action) || len(in.Action) > maxActionBytes {
		return Result{}, errors.New("action is empty, invalid, or too large")
	}
	if len(in.Inputs) > maxInputCount {
		return Result{}, errors.New("too many input fields")
	}
	for key, value := range in.Inputs {
		if strings.TrimSpace(key) == "" || len(key) > maxInputKeyBytes ||
			!utf8.ValidString(key) || !utf8.ValidString(value) ||
			len(value) > maxInputValueBytes {
			return Result{}, errors.New("invalid or oversized input field")
		}
	}

	body, err := json.Marshal(in)
	if err != nil {
		return Result{}, fmt.Errorf("encode request: %w", err)
	}
	if len(body) > maxRequestBytes {
		return Result{}, errors.New("request exceeds the size limit")
	}

	endpoint := base + "/v1/<<TOOL>>/plan"
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		endpoint,
		bytes.NewReader(body),
	)
	if err != nil {
		return Result{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}

	client := safeHTTPClient(c.HTTP)
	resp, err := client.Do(req)
	if err != nil {
		return Result{}, err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return Result{}, fmt.Errorf("Genesis tool endpoint returned HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > maxResponseBytes {
		return Result{}, errors.New("response exceeds the size limit")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return Result{}, err
	}
	if len(raw) > maxResponseBytes {
		return Result{}, errors.New("response exceeds the size limit")
	}

	var out Result
	if err := json.Unmarshal(raw, &out); err != nil {
		return Result{}, fmt.Errorf("decode response: %w", err)
	}
	return out, nil
}

func safeHTTPClient(source *http.Client) *http.Client {
	client := &http.Client{Timeout: 10 * time.Second}
	if source != nil {
		copy := *source
		client = &copy
		if client.Timeout <= 0 || client.Timeout > 10*time.Second {
			client.Timeout = 10 * time.Second
		}
	}
	client.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return client
}
`
	source = strings.ReplaceAll(source, "<<BT>>", "`")
	source = strings.ReplaceAll(source, "<<DISPLAY>>", display)
	source = strings.ReplaceAll(source, "<<PACKAGE>>", pkg)
	source = strings.ReplaceAll(source, "<<TOOL>>", route)
	return source
}

// generatedPythonSDK produces a standard-library-only Python SDK proposal.
func generatedPythonSDK(spec ToolSpec) string {
	route := sdkRouteName(spec.Name)
	display := sdkDisplayName(spec.Name)

	source := `"""Generated standard-library Python SDK proposal for <<DISPLAY>>."""
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ACTION_BYTES = 2000
MAX_INPUT_COUNT = 100
MAX_INPUT_KEY_BYTES = 100
MAX_INPUT_VALUE_BYTES = 4000
MAX_TOKEN_BYTES = 16 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_base_url(value):
    parsed = urllib.parse.urlsplit(str(value).strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("base URL must contain a valid HTTP(S) host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, query, or fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError("HTTPS is required for non-local endpoints")
    return urllib.parse.urlunsplit((
        parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""
    ))


class Client:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = _validate_base_url(base_url)
        if "\r" in token or "\n" in token or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            raise ValueError("invalid or oversized API token")
        self.token = token
        self._opener = urllib.request.build_opener(_NoRedirect())

    def plan(self, action: str, inputs=None, consent: bool = False):
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action is required")
        if len(action.encode("utf-8")) > MAX_ACTION_BYTES:
            raise ValueError("action exceeds the size limit")

        if inputs is None:
            inputs = {}
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a dictionary")
        if len(inputs) > MAX_INPUT_COUNT:
            raise ValueError("too many input fields")

        for key, value in inputs.items():
            if not isinstance(key, str) or not key.strip() or len(key.encode("utf-8")) > MAX_INPUT_KEY_BYTES:
                raise ValueError("invalid input key")
            if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_INPUT_VALUE_BYTES:
                raise ValueError("invalid input value")

        body = json.dumps({
            "action": action.strip(),
            "inputs": inputs,
            "consent": bool(consent),
        }).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds the size limit")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        request = urllib.request.Request(
            self.base_url + "/v1/<<TOOL>>/plan",
            data=body,
            headers=headers,
            method="POST",
        )

        with self._opener.open(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds the size limit")
            return json.loads(raw.decode("utf-8"))
`
	source = strings.ReplaceAll(source, "<<DISPLAY>>", display)
	source = strings.ReplaceAll(source, "<<TOOL>>", route)
	return source
}

// generatedJavaScriptSDK produces a browser/Node-compatible fetch SDK proposal.
func generatedJavaScriptSDK(spec ToolSpec) string {
	route := sdkRouteName(spec.Name)
	display := sdkDisplayName(spec.Name)

	source := `// Generated browser/Node fetch SDK proposal for <<DISPLAY>>.
const MAX_REQUEST_BYTES = 256 * 1024;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_ACTION_BYTES = 2000;
const MAX_INPUT_COUNT = 100;
const MAX_INPUT_KEY_BYTES = 100;
const MAX_INPUT_VALUE_BYTES = 4000;
const MAX_TOKEN_BYTES = 16 * 1024;

function isLoopback(host) {
  host = String(host).toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host === "::1") return true;

  if (/^127(?:\.\d{1,3}){3}$/.test(host)) {
    return host.split(".").slice(1).every(part => Number(part) <= 255);
  }
  return false;
}

function validateBaseUrl(value) {
  let url;
  try {
    url = new URL(String(value));
  } catch {
    throw new Error("base URL must be a valid HTTP(S) URL");
  }

  if (url.protocol !== "https:" &&
      !(url.protocol === "http:" && isLoopback(url.hostname))) {
    throw new Error("HTTPS is required for non-local endpoints");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("base URL must not contain credentials, query, or fragment");
  }
  return url.toString().replace(/\/+$/, "");
}

export class Client {
  constructor(baseUrl, token = "") {
    if (typeof token !== "string" ||
        token.includes("\r") ||
        token.includes("\n") ||
        new TextEncoder().encode(token).length > MAX_TOKEN_BYTES) {
      throw new Error("invalid or oversized API token");
    }
    this.baseUrl = validateBaseUrl(baseUrl);
    this.token = token;
  }

  async plan({ action, inputs = {}, consent = false } = {}) {
    if (typeof action !== "string" || !action.trim()) {
      throw new Error("action is required");
    }
    if (new TextEncoder().encode(action).length > MAX_ACTION_BYTES) {
      throw new Error("action exceeds the size limit");
    }
    if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) {
      throw new Error("inputs must be an object");
    }

    const entries = Object.entries(inputs);
    if (entries.length > MAX_INPUT_COUNT) {
      throw new Error("too many input fields");
    }
    for (const [key, value] of entries) {
      if (!key.trim() ||
          new TextEncoder().encode(key).length > MAX_INPUT_KEY_BYTES) {
        throw new Error("invalid input key");
      }
      if (typeof value !== "string" ||
          new TextEncoder().encode(value).length > MAX_INPUT_VALUE_BYTES) {
        throw new Error("invalid input value");
      }
    }

    const body = JSON.stringify({
      action: action.trim(),
      inputs,
      consent: Boolean(consent)
    });
    if (new TextEncoder().encode(body).length > MAX_REQUEST_BYTES) {
      throw new Error("request exceeds the size limit");
    }

    const headers = { "Content-Type": "application/json", "Accept": "application/json" };
    if (this.token) headers.Authorization = "Bearer " + this.token;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);

    try {
      const response = await fetch(this.baseUrl + "/v1/<<TOOL>>/plan", {
        method: "POST",
        headers,
        body,
        redirect: "error",
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error("Genesis endpoint returned HTTP " + response.status);
      }

      const raw = await response.text();
      if (new TextEncoder().encode(raw).length > MAX_RESPONSE_BYTES) {
        throw new Error("response exceeds the size limit");
      }
      return JSON.parse(raw);
    } finally {
      clearTimeout(timer);
    }
  }
}
`
	source = strings.ReplaceAll(source, "<<DISPLAY>>", display)
	source = strings.ReplaceAll(source, "<<TOOL>>", route)
	return source
}

func sdkRouteName(name string) string {
	name = strings.ToLower(strings.TrimSpace(name))

	var builder strings.Builder
	builder.Grow(len(name))

	lastSeparator := false
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			builder.WriteRune(r)
			lastSeparator = false
		case r == '-' || r == '_':
			if builder.Len() > 0 && !lastSeparator {
				builder.WriteRune(r)
				lastSeparator = true
			}
		default:
			if builder.Len() > 0 && !lastSeparator {
				builder.WriteByte('-')
				lastSeparator = true
			}
		}

		if builder.Len() >= maxSDKRouteBytes {
			break
		}
	}

	result := strings.Trim(builder.String(), "-_")
	if result == "" {
		return "genesis-tool"
	}
	if len(result) > maxSDKRouteBytes {
		result = result[:maxSDKRouteBytes]
		result = strings.TrimRight(result, "-_")
	}
	if result == "" || result == "." || result == ".." {
		return "genesis-tool"
	}
	return result
}

func sdkDisplayName(name string) string {
	name = strings.TrimSpace(name)
	var builder strings.Builder
	builder.Grow(minInt(len(name), 120))

	space := false
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z',
			r >= 'A' && r <= 'Z',
			r >= '0' && r <= '9',
			r == '-' || r == '_' || r == '.':
			builder.WriteRune(r)
			space = false
		case r == ' ' || r == '\t':
			if builder.Len() > 0 && !space {
				builder.WriteByte(' ')
				space = true
			}
		default:
			// Drop punctuation/control characters to keep generated comments
			// and docstrings single-line and non-executable.
		}
		if builder.Len() >= 120 {
			break
		}
	}

	result := strings.TrimSpace(builder.String())
	if result == "" {
		return "Genesis tool"
	}
	return result
}

func sdkGoPackageName(route string) string {
	var builder strings.Builder
	for _, r := range route {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			builder.WriteRune(r)
		} else {
			builder.WriteByte('_')
		}
	}
	return builder.String() + "_client"
}

// writeIntegrityManifest writes SHA-256 hashes for regular files in an artifact
// directory. Symlinks and special files are rejected to prevent a manifest from
// silently hashing content outside the artifact bundle.
func writeIntegrityManifest(dir string) error {
	if strings.TrimSpace(dir) == "" {
		return errors.New("integrity manifest directory cannot be empty")
	}

	root, err := filepath.Abs(dir)
	if err != nil {
		return fmt.Errorf("resolve artifact directory: %w", err)
	}

	rootInfo, err := os.Lstat(root)
	if err != nil {
		return fmt.Errorf("inspect artifact directory: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return errors.New("integrity manifest root must be a regular directory, not a symlink")
	}

	hashes := make(map[string]string)
	var totalBytes int64
	fileCount := 0

	err = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}

		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("symlink is not permitted in integrity manifest tree: %s", path)
		}
		if info.IsDir() {
			return nil
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("non-regular artifact file is not permitted: %s", path)
		}

		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)

		// Exclude only the root manifest itself; nested files with the same
		// name must still be included in the integrity hashes.
		if rel == "artifact_hashes.json" {
			return nil
		}

		fileCount++
		if fileCount > maxIntegrityFileCount {
			return errors.New("artifact exceeds the maximum integrity-manifest file count")
		}
		if info.Size() < 0 || info.Size() > maxIntegrityTotalBytes-totalBytes {
			return errors.New("artifact exceeds the maximum integrity-manifest byte count")
		}

		file, err := os.Open(path)
		if err != nil {
			return err
		}

		openedInfo, statErr := file.Stat()
		if statErr != nil {
			_ = file.Close()
			return statErr
		}
		if !openedInfo.Mode().IsRegular() || !os.SameFile(info, openedInfo) {
			_ = file.Close()
			return fmt.Errorf("artifact changed while generating integrity manifest: %s", rel)
		}

		hasher := sha256.New()
		remaining := maxIntegrityTotalBytes - totalBytes
		n, copyErr := io.Copy(hasher, io.LimitReader(file, remaining+1))
		closeErr := file.Close()

		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
		if n > remaining {
			return errors.New("artifact exceeds the maximum integrity-manifest byte count")
		}

		afterInfo, err := os.Stat(path)
		if err != nil {
			return err
		}
		if afterInfo.Size() != openedInfo.Size() || n != openedInfo.Size() {
			return fmt.Errorf("artifact changed while hashing: %s", rel)
		}

		totalBytes += n
		hashes[rel] = hex.EncodeToString(hasher.Sum(nil))
		return nil
	})
	if err != nil {
		return err
	}

	manifest := map[string]any{
		"schema_version": 2,
		"algorithm":      "SHA-256",
		"files":          hashes,
		"file_count":     fileCount,
		"total_bytes":    totalBytes,
		"purpose":        "tamper-evident integrity manifest; not copy prevention",
		"created_at":     time.Now().UTC(),
	}

	if key := os.Getenv("GENESIS_SIGNING_KEY"); strings.TrimSpace(key) != "" {
		if len([]byte(key)) < minIntegrityKeyBytes {
			manifest["hmac_warning"] = "GENESIS_SIGNING_KEY is shorter than 32 bytes; use a strong random secret of at least 32 bytes."
		}

		unsigned, err := json.Marshal(manifest)
		if err != nil {
			return fmt.Errorf("encode unsigned integrity manifest: %w", err)
		}

		mac := hmac.New(sha256.New, []byte(key))
		if _, err := mac.Write(unsigned); err != nil {
			return fmt.Errorf("calculate integrity manifest HMAC: %w", err)
		}

		manifest["hmac_algorithm"] = "HMAC-SHA-256"
		manifest["hmac_sha256"] = hex.EncodeToString(mac.Sum(nil))
	}

	return writeJSON(filepath.Join(root, "artifact_hashes.json"), manifest)
}

func mustJSON(v any) []byte {
	raw, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return []byte("{\"error\":\"encoding failed\"}\n")
	}
	return append(raw, '\n')
}
