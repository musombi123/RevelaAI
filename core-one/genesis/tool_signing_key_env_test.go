package genesis

import (
	"encoding/base64"
	"testing"
)

func TestRegistrySigningKeyAcceptsEncodedAndRenderGeneratedMaterial(t *testing.T) {
	t.Setenv("GENESIS_SIGNING_KEY", "")
	if _, err := registrySigningKey(); err == nil {
		t.Fatal("expected missing signing key to fail closed")
	}

	t.Setenv("GENESIS_SIGNING_KEY", "too-short")
	if _, err := registrySigningKey(); err == nil {
		t.Fatal("expected short signing material to fail")
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

	generated := "render-generated-opaque-secret-material-256-bits"
	t.Setenv("GENESIS_SIGNING_KEY", generated)
	generatedKey, err := registrySigningKey()
	if err != nil {
		t.Fatalf("Render-generated opaque secret was rejected: %v", err)
	}
	again, err := registrySigningKey()
	if err != nil {
		t.Fatalf("same generated secret was rejected on second read: %v", err)
	}
	if string(generatedKey) != string(again) {
		t.Fatal("the same generated secret must produce a stable Ed25519 key")
	}
	if string(generatedKey) == string(privateKey) {
		t.Fatal("different secret material unexpectedly produced the same signing key")
	}
}
