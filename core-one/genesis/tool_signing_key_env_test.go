package genesis

import (
	"encoding/base64"
	"testing"
)

func TestRegistrySigningKeyRequiresBase64Ed25519Material(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "")
	if _, err := registrySigningKey(); err == nil {
		t.Fatal("expected missing signing key to fail closed")
	}

	t.Setenv("GENESIS_SIGNING_KEY", "render-generated-arbitrary-string")
	if _, err := registrySigningKey(); err == nil {
		t.Fatal("expected non-base64 signing key to fail")
	}

	seed := []byte("01234567890123456789012345678901")
	t.Setenv("GENESIS_SIGNING_KEY", base64.StdEncoding.EncodeToString(seed))
	privateKey, err := registrySigningKey()
	if err != nil {
		t.Fatalf("valid 32-byte Ed25519 seed rejected: %v", err)
	}
	if len(privateKey) != 64 {
		t.Fatalf("expected 64-byte Ed25519 private key, got %d", len(privateKey))
	}
}
