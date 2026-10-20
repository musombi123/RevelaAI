
package candidate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

const CandidateID = "canonical-spec-cache"

const (
	CanonicalSchemaVersion = 1
	MaxEntries             = 100
	MaxKeyBytes            = 256
	MaxValueBytes          = 4096
	MaxCanonicalBytes      = 1 << 20
)

var (
	ErrInvalidSpec = errors.New("invalid canonical specification")
	ErrTooLarge    = errors.New("canonical specification exceeds size limits")
	ErrUnstable    = errors.New("unstable canonical fingerprint")
)

type canonicalEnvelope struct {
	SchemaVersion int               `json:"schema_version"`
	Spec           map[string]string `json:"spec"`
}

// CanonicalJSON validates and serializes a specification deterministically.
// encoding/json sorts string map keys, producing stable output for identical
// maps. Original keys and values are preserved; they are not silently trimmed.
func CanonicalJSON(v map[string]string) ([]byte, error) {
	if v == nil {
		return nil, fmt.Errorf("%w: specification is nil", ErrInvalidSpec)
	}

	if len(v) > MaxEntries {
		return nil, fmt.Errorf(
			"%w: maximum %d entries permitted",
			ErrTooLarge,
			MaxEntries,
		)
	}

	// Copy the caller's map before serialization.
	spec := make(map[string]string, len(v))

	for key, value := range v {
		if !utf8.ValidString(key) || !utf8.ValidString(value) {
			return nil, fmt.Errorf(
				"%w: invalid UTF-8",
				ErrInvalidSpec,
			)
		}

		if strings.TrimSpace(key) == "" {
			return nil, fmt.Errorf(
				"%w: empty specification key",
				ErrInvalidSpec,
			)
		}

		if len(key) > MaxKeyBytes {
			return nil, fmt.Errorf(
				"%w: key exceeds %d bytes",
				ErrTooLarge,
				MaxKeyBytes,
			)
		}

		if len(value) > MaxValueBytes {
			return nil, fmt.Errorf(
				"%w: value exceeds %d bytes",
				ErrTooLarge,
				MaxValueBytes,
			)
		}

		if hasUnsupportedControl(key, false) ||
			hasUnsupportedControl(value, true) {
			return nil, fmt.Errorf(
				"%w: unsupported control character",
				ErrInvalidSpec,
			)
		}

		spec[key] = value
	}

	raw, err := json.Marshal(canonicalEnvelope{
		SchemaVersion: CanonicalSchemaVersion,
		Spec:          spec,
	})
	if err != nil {
		return nil, fmt.Errorf(
			"%w: JSON serialization failed: %v",
			ErrInvalidSpec,
			err,
		)
	}

	if len(raw) > MaxCanonicalBytes {
		return nil, ErrTooLarge
	}

	return raw, nil
}

// FingerprintWithError returns a lowercase SHA-256 digest of canonical JSON.
// Use this API when callers need to distinguish invalid input from valid data.
func FingerprintWithError(v map[string]string) (string, error) {
	raw, err := CanonicalJSON(v)
	if err != nil {
		return "", err
	}

	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

// Fingerprint preserves the original API.
// Invalid input returns an empty string rather than a misleading fingerprint.
func Fingerprint(v map[string]string) string {
	fingerprint, err := FingerprintWithError(v)
	if err != nil {
		return ""
	}

	return fingerprint
}

// VerifyFingerprint checks that the supplied fingerprint is a valid lowercase
// SHA-256 hex digest and matches the canonical representation of the input.
func VerifyFingerprint(v map[string]string, expected string) error {
	if len(expected) != sha256.Size*2 {
		return ErrUnstable
	}

	decoded, err := hex.DecodeString(expected)
	if err != nil || hex.EncodeToString(decoded) != expected {
		return ErrUnstable
	}

	actual, err := FingerprintWithError(v)
	if err != nil {
		return err
	}

	if actual != expected {
		return ErrUnstable
	}

	return nil
}

func hasUnsupportedControl(value string, allowWhitespace bool) bool {
	for _, r := range value {
		if !unicode.IsControl(r) {
			continue
		}

		if allowWhitespace &&
			(r == '\n' || r == '\r' || r == '\t') {
			continue
		}

		return true
	}

	return false
}

// Validate runs deterministic offline regression checks.
// It does not execute, activate, or merge generated tools.
func Validate() error {
	left := map[string]string{
		"b": "2",
		"a": "1",
	}
	right := map[string]string{
		"a": "1",
		"b": "2",
	}

	first, err := FingerprintWithError(left)
	if err != nil {
		return fmt.Errorf("first fingerprint failed: %w", err)
	}

	second, err := FingerprintWithError(right)
	if err != nil {
		return fmt.Errorf("second fingerprint failed: %w", err)
	}

	if first == "" || first != second {
		return ErrUnstable
	}

	if err := VerifyFingerprint(left, first); err != nil {
		return fmt.Errorf("fingerprint verification failed: %w", err)
	}

	// A meaningful specification change must change its fingerprint.
	changed := map[string]string{
		"a": "changed",
		"b": "2",
	}

	changedFingerprint := Fingerprint(changed)
	if changedFingerprint == "" || changedFingerprint == first {
		return errors.New("changed specification produced an invalid or identical fingerprint")
	}

	// Invalid inputs must fail closed.
	invalidCases := []map[string]string{
		nil,
		{"": "value"},
		{"key": strings.Repeat("x", MaxValueBytes+1)},
		{string([]byte{0xff}): "value"},
		{"key": string([]byte{0x00})},
	}

	for _, input := range invalidCases {
		if Fingerprint(input) != "" {
			return errors.New("invalid specification was fingerprinted")
		}

		if _, err := CanonicalJSON(input); err == nil {
			return errors.New("invalid specification was accepted")
		}
	}

	// Reject a map exceeding the entry limit.
	oversized := make(map[string]string, MaxEntries+1)
	for i := 0; i <= MaxEntries; i++ {
		oversized[fmt.Sprintf("key-%03d", i)] = "value"
	}

	if Fingerprint(oversized) != "" {
		return errors.New("oversized specification was fingerprinted")
	}

	return nil
}
