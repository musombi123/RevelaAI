// Package vulnfeed verifies a signed offline advisory snapshot and matches it
// against an explicitly supplied local package manifest. It performs no network
// requests and never changes installed packages.
package vulnfeed

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

const (
	EnvelopeSchema = "revela-vulnerability-feed-envelope/1"
	FeedSchema     = "revela-vulnerability-feed/1"
	ManifestSchema = "revela-package-manifest/1"
	MaxFeedBytes   = 10 << 20
	MaxManifestBytes = 10 << 20
	MaxAdvisories  = 100000
	MaxPackages    = 100000
)

var hex64 = regexp.MustCompile(`^[a-fA-F0-9]{64}$`)

type Envelope struct {
	SchemaVersion string `json:"schema_version"`
	PayloadBase64 string `json:"payload_base64"`
	SignatureHex  string `json:"signature_ed25519"`
}

type Advisory struct {
	ID               string   `json:"id"`
	PackageURL       string   `json:"package_url"`
	AffectedVersions []string `json:"affected_versions"`
	FixedVersions    []string `json:"fixed_versions,omitempty"`
	Severity         string   `json:"severity"`
	Summary          string   `json:"summary"`
	References       []string `json:"references,omitempty"`
}

type Feed struct {
	SchemaVersion string     `json:"schema_version"`
	FeedID        string     `json:"feed_id"`
	Provider      string     `json:"provider"`
	IssuedAt      time.Time  `json:"issued_at"`
	ExpiresAt     time.Time  `json:"expires_at"`
	Advisories    []Advisory `json:"advisories"`
}

type Package struct {
	Ecosystem string `json:"ecosystem"`
	Name      string `json:"name"`
	Version   string `json:"version"`
	PackageURL string `json:"package_url"`
}

type Manifest struct {
	SchemaVersion string    `json:"schema_version"`
	GeneratedAt   time.Time `json:"generated_at"`
	Source        string    `json:"source"`
	Packages      []Package `json:"packages"`
}

type VerifiedFeed struct {
	Feed               Feed
	PayloadSHA256      string
	PublicKeySHA256    string
	AdvisoryCount      int
	VerifiedAt         time.Time
}

type Match struct {
	Package  Package
	Advisory Advisory
}

func ReadRegularFile(path string, max int64) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("inspect %s: %w", path, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() > max {
		return nil, fmt.Errorf("%s must be a regular non-symlink file no larger than %d bytes", path, max)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || opened.Size() > max {
		return nil, fmt.Errorf("%s changed or is not a bounded regular file", path)
	}
	data := make([]byte, opened.Size())
	n, err := file.Read(data)
	if err != nil && n != len(data) {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	if n != len(data) {
		return nil, fmt.Errorf("%s changed during read", path)
	}
	return data, nil
}

func ParsePublicKey(value []byte) (ed25519.PublicKey, error) {
	text := strings.TrimSpace(string(value))
	if !hex64.MatchString(text) {
		return nil, errors.New("public key must be a 64-character hexadecimal Ed25519 key")
	}
	raw, err := hex.DecodeString(text)
	if err != nil || len(raw) != ed25519.PublicKeySize {
		return nil, errors.New("invalid Ed25519 public key")
	}
	return ed25519.PublicKey(raw), nil
}

func Fingerprint(key ed25519.PublicKey) string {
	sum := sha256.Sum256(key)
	return hex.EncodeToString(sum[:])
}

func VerifyEnvelope(envelopeBytes []byte, key ed25519.PublicKey, expectedFingerprint string, now time.Time) (VerifiedFeed, error) {
	if len(envelopeBytes) == 0 || len(envelopeBytes) > MaxFeedBytes {
		return VerifiedFeed{}, fmt.Errorf("feed envelope must be between 1 and %d bytes", MaxFeedBytes)
	}
	if len(key) != ed25519.PublicKeySize {
		return VerifiedFeed{}, errors.New("invalid Ed25519 public key length")
	}
	expectedFingerprint = strings.ToLower(strings.TrimSpace(expectedFingerprint))
	actualFingerprint := Fingerprint(key)
	if !hex64.MatchString(expectedFingerprint) || expectedFingerprint != actualFingerprint {
		return VerifiedFeed{}, errors.New("trusted public-key fingerprint mismatch")
	}

	var envelope Envelope
	if err := json.Unmarshal(envelopeBytes, &envelope); err != nil {
		return VerifiedFeed{}, fmt.Errorf("decode feed envelope: %w", err)
	}
	if envelope.SchemaVersion != EnvelopeSchema {
		return VerifiedFeed{}, errors.New("unsupported feed envelope schema")
	}
	payload, err := base64.StdEncoding.DecodeString(envelope.PayloadBase64)
	if err != nil || len(payload) == 0 || len(payload) > MaxFeedBytes {
		return VerifiedFeed{}, errors.New("invalid or oversized signed feed payload")
	}
	signature, err := hex.DecodeString(envelope.SignatureHex)
	if err != nil || len(signature) != ed25519.SignatureSize {
		return VerifiedFeed{}, errors.New("invalid Ed25519 signature encoding")
	}
	if !ed25519.Verify(key, payload, signature) {
		return VerifiedFeed{}, errors.New("feed signature verification failed")
	}

	var feed Feed
	if err := json.Unmarshal(payload, &feed); err != nil {
		return VerifiedFeed{}, fmt.Errorf("decode signed feed payload: %w", err)
	}
	if feed.SchemaVersion != FeedSchema {
		return VerifiedFeed{}, errors.New("unsupported vulnerability feed schema")
	}
	if strings.TrimSpace(feed.FeedID) == "" || strings.TrimSpace(feed.Provider) == "" {
		return VerifiedFeed{}, errors.New("feed ID and provider are required")
	}
	if feed.IssuedAt.IsZero() || feed.ExpiresAt.IsZero() || !feed.ExpiresAt.After(feed.IssuedAt) {
		return VerifiedFeed{}, errors.New("feed issue and expiry timestamps are invalid")
	}
	if feed.IssuedAt.After(now.UTC().Add(10 * time.Minute)) {
		return VerifiedFeed{}, errors.New("feed issue time is unexpectedly in the future")
	}
	if !feed.ExpiresAt.After(now.UTC()) {
		return VerifiedFeed{}, errors.New("vulnerability feed has expired; refresh it from its trusted publisher")
	}
	if len(feed.Advisories) > MaxAdvisories {
		return VerifiedFeed{}, errors.New("feed contains too many advisories")
	}
	for index, advisory := range feed.Advisories {
		if err := validateAdvisory(advisory); err != nil {
			return VerifiedFeed{}, fmt.Errorf("advisory %d: %w", index, err)
		}
	}

	payloadHash := sha256.Sum256(payload)
	return VerifiedFeed{
		Feed: feed,
		PayloadSHA256: hex.EncodeToString(payloadHash[:]),
		PublicKeySHA256: actualFingerprint,
		AdvisoryCount: len(feed.Advisories),
		VerifiedAt: now.UTC(),
	}, nil
}

func validateAdvisory(item Advisory) error {
	if strings.TrimSpace(item.ID) == "" || len(item.ID) > 100 {
		return errors.New("advisory ID is missing or too long")
	}
	if !strings.HasPrefix(item.PackageURL, "pkg:") || len(item.PackageURL) > 512 {
		return errors.New("advisory package_url must be a bounded Package URL")
	}
	if len(item.AffectedVersions) == 0 || len(item.AffectedVersions) > 500 {
		return errors.New("affected_versions must contain 1-500 exact versions")
	}
	for _, version := range item.AffectedVersions {
		if strings.TrimSpace(version) == "" || len(version) > 128 {
			return errors.New("affected version is invalid")
		}
	}
	switch strings.ToLower(item.Severity) {
	case "informational", "low", "medium", "high", "critical":
	default:
		return errors.New("unsupported severity")
	}
	if strings.TrimSpace(item.Summary) == "" || len(item.Summary) > 4000 {
		return errors.New("summary is missing or too long")
	}
	if len(item.References) > 20 {
		return errors.New("too many advisory references")
	}
	for _, reference := range item.References {
		if !strings.HasPrefix(reference, "https://") || len(reference) > 2048 {
			return errors.New("advisory references must be HTTPS URLs")
		}
	}
	return nil
}

func ParseManifest(data []byte) (Manifest, error) {
	if len(data) == 0 || len(data) > MaxManifestBytes {
		return Manifest{}, fmt.Errorf("package manifest must be between 1 and %d bytes", MaxManifestBytes)
	}
	var manifest Manifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return Manifest{}, fmt.Errorf("decode package manifest: %w", err)
	}
	if manifest.SchemaVersion != ManifestSchema {
		return Manifest{}, errors.New("unsupported package manifest schema")
	}
	if strings.TrimSpace(manifest.Source) == "" || manifest.GeneratedAt.IsZero() {
		return Manifest{}, errors.New("manifest source and generated_at are required")
	}
	if len(manifest.Packages) > MaxPackages {
		return Manifest{}, errors.New("manifest contains too many packages")
	}
	for index, item := range manifest.Packages {
		if strings.TrimSpace(item.Ecosystem) == "" || strings.TrimSpace(item.Name) == "" ||
			strings.TrimSpace(item.Version) == "" || !strings.HasPrefix(item.PackageURL, "pkg:") {
			return Manifest{}, fmt.Errorf("package %d is missing ecosystem, name, version or Package URL", index)
		}
		if len(item.PackageURL) > 512 || len(item.Version) > 128 {
			return Manifest{}, fmt.Errorf("package %d exceeds supported identifier limits", index)
		}
	}
	return manifest, nil
}

// MatchExact deliberately matches exact package URLs and exact version strings.
// It does not interpret ranges, aliases, distro backports or version ordering.
func MatchExact(manifest Manifest, feed Feed) []Match {
	type packageVersion struct{ purl, version string }
	packages := make(map[packageVersion]Package, len(manifest.Packages))
	for _, item := range manifest.Packages {
		packages[packageVersion{item.PackageURL, item.Version}] = item
	}
	matches := []Match{}
	for _, advisory := range feed.Advisories {
		for _, version := range advisory.AffectedVersions {
			if item, ok := packages[packageVersion{advisory.PackageURL, version}]; ok {
				matches = append(matches, Match{Package: item, Advisory: advisory})
			}
		}
	}
	return matches
}
