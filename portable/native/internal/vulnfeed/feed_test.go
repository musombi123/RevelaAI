package vulnfeed

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"testing"
	"time"
)

func signedEnvelope(t *testing.T, now time.Time) ([]byte, ed25519.PublicKey, string) {
	t.Helper()
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil { t.Fatal(err) }
	feed := Feed{
		SchemaVersion: FeedSchema, FeedID: "test-feed-2026-10",
		Provider: "Revela Security Test Publisher",
		IssuedAt: now.Add(-time.Hour), ExpiresAt: now.Add(24*time.Hour),
		Advisories: []Advisory{{
			ID: "CVE-2026-12345", PackageURL: "pkg:npm/example-lib@1.2.3",
			AffectedVersions: []string{"1.2.3"}, FixedVersions: []string{"1.2.4"},
			Severity: "high", Summary: "Test advisory for the offline fixture.",
			References: []string{"https://example.org/advisories/CVE-2026-12345"},
		}},
	}
	payload, err := json.Marshal(feed)
	if err != nil { t.Fatal(err) }
	envelope := Envelope{
		SchemaVersion: EnvelopeSchema,
		PayloadBase64: base64.StdEncoding.EncodeToString(payload),
		SignatureHex: hex.EncodeToString(ed25519.Sign(private, payload)),
	}
	encoded, err := json.Marshal(envelope)
	if err != nil { t.Fatal(err) }
	return encoded, public, Fingerprint(public)
}

func TestVerifySignedFeedAndExactPackageMatch(t *testing.T) {
	now := time.Date(2026, 10, 31, 12, 0, 0, 0, time.UTC)
	encoded, key, fingerprint := signedEnvelope(t, now)
	verified, err := VerifyEnvelope(encoded, key, fingerprint, now)
	if err != nil { t.Fatal(err) }
	if verified.AdvisoryCount != 1 || verified.Feed.FeedID == "" || verified.PayloadSHA256 == "" {
		t.Fatalf("unexpected verification result: %+v", verified)
	}
	manifest, err := ParseManifest([]byte(`{
		"schema_version":"revela-package-manifest/1",
		"generated_at":"2026-10-31T11:00:00Z",
		"source":"fixture",
		"packages":[
			{"ecosystem":"npm","name":"example-lib","version":"1.2.3","package_url":"pkg:npm/example-lib@1.2.3"},
			{"ecosystem":"npm","name":"safe-lib","version":"2.0.0","package_url":"pkg:npm/safe-lib@2.0.0"}
		]
	}`))
	if err != nil { t.Fatal(err) }
	matches := MatchExact(manifest, verified.Feed)
	if len(matches) != 1 || matches[0].Advisory.ID != "CVE-2026-12345" {
		t.Fatalf("expected one exact match, got %+v", matches)
	}
}

func TestRejectsWrongFingerprintExpiredFeedAndTampering(t *testing.T) {
	now := time.Date(2026, 10, 31, 12, 0, 0, 0, time.UTC)
	encoded, key, fingerprint := signedEnvelope(t, now)
	if _, err := VerifyEnvelope(encoded, key, "00"+fingerprint[2:], now); err == nil { t.Fatal("wrong fingerprint must be rejected") }
	if _, err := VerifyEnvelope(encoded, key, fingerprint, now.Add(48*time.Hour)); err == nil { t.Fatal("expired feed must be rejected") }
	encoded[len(encoded)-5] ^= 1
	if _, err := VerifyEnvelope(encoded, key, fingerprint, now); err == nil { t.Fatal("tampered envelope must be rejected") }
}

func TestRejectsUnsignedOrMalformedFeedAndManifest(t *testing.T) {
	now := time.Now().UTC()
	encoded, key, fingerprint := signedEnvelope(t, now)
	var envelope Envelope
	if err := json.Unmarshal(encoded, &envelope); err != nil { t.Fatal(err) }
	envelope.SignatureHex = hex.EncodeToString(make([]byte, ed25519.SignatureSize))
	bad, _ := json.Marshal(envelope)
	if _, err := VerifyEnvelope(bad, key, fingerprint, now); err == nil { t.Fatal("invalid signature must be rejected") }
	if _, err := ParseManifest([]byte(`{"schema_version":"wrong"}`)); err == nil { t.Fatal("wrong manifest schema must be rejected") }
}

func TestMatchIsExactAndDoesNotGuessVersionRanges(t *testing.T) {
	manifest := Manifest{Packages: []Package{
		{PackageURL:"pkg:npm/example-lib@1.2.3", Version:"1.2.3"},
		{PackageURL:"pkg:npm/example-lib@1.2.4", Version:"1.2.4"},
	}}
	feed := Feed{Advisories: []Advisory{{
		ID:"CVE-2026-12345", PackageURL:"pkg:npm/example-lib@1.2.3",
		AffectedVersions:[]string{"1.2.3"}, Severity:"high", Summary:"fixture",
	}}}
	if len(MatchExact(manifest,feed)) != 1 { t.Fatal("only exact package URL/version should match") }
}

func TestParsePublicKeyRejectsInvalidKey(t *testing.T) {
	if _, err := ParsePublicKey([]byte("not a public key")); err == nil { t.Fatal("invalid public key must be rejected") }
}
