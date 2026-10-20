package genesis

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestDockerSandboxCannotAccessNetworkOrHostSecrets(t *testing.T) {
	if _, err := exec.LookPath("docker"); err != nil {
		t.Skip("Docker CLI not available; isolation integration test requires a configured container runtime")
	}
	if err := exec.Command("docker", "info").Run(); err != nil {
		t.Skip("Docker daemon is unavailable")
	}
	if err := exec.Command("docker", "image", "inspect", "python:3.12-alpine").Run(); err != nil {
		t.Skip("python:3.12-alpine image is not preloaded; sandbox policy requires --pull=never")
	}

	root := t.TempDir()
	candidate := filepath.Join(root, "candidate")
	if err := os.Mkdir(candidate, 0o700); err != nil {
		t.Fatal(err)
	}
	script := `import os
import socket
import unittest

class SandboxBoundaryTest(unittest.TestCase):
    def test_host_secrets_are_not_inherited(self):
        for name in ("GEMINI_API_KEY", "HF_TOKEN", "MVI_API_KEY", "GENESIS_SIGNING_KEY", "GENESIS_ADMIN_TOKEN"):
            self.assertNotIn(name, os.environ)

    def test_network_is_unavailable(self):
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            with self.assertRaises(OSError):
                sock.connect(("1.1.1.1", 443))
        finally:
            sock.close()

if __name__ == "__main__":
    unittest.main()
`
	if err := os.WriteFile(filepath.Join(candidate, "test_sandbox_security.py"), []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest := ToolManifest{
		SchemaVersion: ToolManifestSchemaVersion,
		Name: "sandbox_boundary_test", Version: "1.0.0", Language: "python",
		Entrypoint: "test_sandbox_security.py",
		InputSchema: json.RawMessage("{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"),
		OutputSchema: json.RawMessage("{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"),
		RiskTier: 0, Permissions: ToolPermissions{}, TimeoutMillis: 10000, MemoryBytes: 128 << 20,
	}
	if _, err := RunCandidateSandbox(context.Background(), candidate, filepath.Join(root, "evidence"), manifest); err != nil {
		t.Fatalf("sandbox boundary checks failed: %v", err)
	}
}
