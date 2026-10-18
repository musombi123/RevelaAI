package genesis

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func generatedGoSDK(spec ToolSpec) string {
	pkg := slugName(spec.Name + "client")
	source := fmt.Sprintf(`// Generated standard-library-only Go SDK proposal for %s.
package %s

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Request struct { Action string <<BT>>json:"action"<<BT>>; Inputs map[string]string <<BT>>json:"inputs,omitempty"<<BT>>; Consent bool <<BT>>json:"consent,omitempty"<<BT>> }
type Result struct { Status string <<BT>>json:"status"<<BT>>; Tool string <<BT>>json:"tool"<<BT>>; Summary string <<BT>>json:"summary"<<BT>> }
type Client struct { BaseURL string; Token string; HTTP *http.Client }
func New(baseURL, token string) (*Client,error) {
	u,err:=url.Parse(strings.TrimRight(baseURL,"/"));if err!=nil||u.Host==""||(u.Scheme!="https"&&u.Scheme!="http"){return nil,errors.New("base URL must be http(s)")}
	if u.Scheme=="http"&&u.Hostname()!="localhost"&&u.Hostname()!="127.0.0.1"&&u.Hostname()!="::1"{return nil,errors.New("HTTPS is required off localhost")}
	return &Client{BaseURL:strings.TrimRight(baseURL,"/"),Token:token,HTTP:&http.Client{Timeout:10*time.Second}},nil
}
func (c *Client) Plan(ctx context.Context, in Request) (Result,error) {
	if strings.TrimSpace(in.Action)==""{return Result{},errors.New("action is required")};body,_:=json.Marshal(in);req,err:=http.NewRequestWithContext(ctx,http.MethodPost,c.BaseURL+"/v1/<<TOOL>>/plan",bytes.NewReader(body));if err!=nil{return Result{},err};req.Header.Set("Content-Type","application/json");if c.Token!=""{req.Header.Set("Authorization","Bearer "+c.Token)};client:=c.HTTP;if client==nil{client=http.DefaultClient};resp,err:=client.Do(req);if err!=nil{return Result{},err};defer resp.Body.Close();if resp.StatusCode<200||resp.StatusCode>=300{return Result{},errors.New("Genesis tool endpoint returned a non-success status")};var out Result;err=json.NewDecoder(resp.Body).Decode(&out);return out,err
}
`, spec.Name, pkg)
	source = strings.ReplaceAll(source, "<<BT>>", string(rune('`')))
	return strings.ReplaceAll(source, "<<TOOL>>", spec.Name)
}

func generatedPythonSDK(spec ToolSpec) string {
	return fmt.Sprintf(`"""Generated standard-library Python SDK proposal for %s."""
import json
import urllib.error
import urllib.request

class Client:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://localhost") and not self.base_url.startswith("http://127.0.0.1"):
            raise ValueError("HTTPS is required off localhost")
        self.token = token

    def plan(self, action: str, inputs=None, consent: bool = False):
        if not action or not action.strip():
            raise ValueError("action is required")
        body = json.dumps({"action": action, "inputs": inputs or {}, "consent": consent}).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base_url + "/v1/%s/plan", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
`, spec.Name, spec.Name)
}

func generatedJavaScriptSDK(spec ToolSpec) string {
	source := fmt.Sprintf(`// Generated browser/Node fetch SDK proposal for %s.
export class Client {
  constructor(baseUrl, token = "") {
    this.baseUrl = String(baseUrl).replace(/\\/+$/, "");
    const url = new URL(this.baseUrl);
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.host))) {
      throw new Error("HTTPS is required off localhost");
    }
    this.token = token;
  }
  async plan({ action, inputs = {}, consent = false }) {
    if (!action || !String(action).trim()) throw new Error("action is required");
    const headers = { "Content-Type": "application/json" };
    if (this.token) headers.Authorization = "Bearer " + this.token;
    const response = await fetch(this.baseUrl + "/v1/<<TOOL>>/plan", {
      method: "POST", headers, body: JSON.stringify({ action, inputs, consent })
    });
    if (!response.ok) throw new Error("Genesis endpoint returned HTTP " + response.status);
    return response.json();
  }
}
`, spec.Name)
	return strings.ReplaceAll(source, "<<TOOL>>", spec.Name)
}

func writeIntegrityManifest(dir string) error {
	hashes := map[string]string{}
	err := filepath.WalkDir(dir, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		if entry.Name() == "artifact_hashes.json" {
			return nil
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(raw)
		hashes[filepath.ToSlash(rel)] = hex.EncodeToString(sum[:])
		return nil
	})
	if err != nil {
		return err
	}
	manifest := map[string]any{"algorithm": "SHA-256", "files": hashes, "purpose": "tamper-evident integrity manifest; not copy prevention", "created_at": time.Now().UTC()}
	if key := os.Getenv("GENESIS_SIGNING_KEY"); key != "" {
		b, _ := json.Marshal(manifest)
		mac := hmac.New(sha256.New, []byte(key))
		_, _ = mac.Write(b)
		manifest["hmac_sha256"] = hex.EncodeToString(mac.Sum(nil))
	}
	return writeJSON(filepath.Join(dir, "artifact_hashes.json"), manifest)
}

func mustJSON(v any) []byte {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return []byte(`{"error":"encoding failed"}`)
	}
	return append(b, '\n')
}
