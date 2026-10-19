// Package candidate provides a proposed authenticated-encryption envelope
// for RVX source or intermediate-representation data.
//
// This is a candidate proposal for human review. It does not modify the
// Core-One compiler, execute RVX instructions, generate WASM, or activate
// encrypted content automatically.
package candidate

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
)

const (
	RVXEnvelopeVersionV1 = "rvx-aead-v1"
	RVXEnvelopeVersionV2 = "rvx-aead-v2"

	rvxMinMasterKeyBytes = 32
	rvxMaxPlaintextBytes = 16 << 20 // 16 MiB
	rvxGCMNonceBytes     = 12
	rvxGCMTagBytes       = 16

	// Bound encoded input before allocating the decoded ciphertext.
	rvxMaxCiphertextBytes        = rvxMaxPlaintextBytes + rvxGCMTagBytes
	rvxMaxCiphertextEncodedBytes = 24 << 20
	rvxMaxNonceEncodedBytes     = 64
)

// RVXEnvelope stores a versioned, authenticated-encryption envelope.
//
// Nonce and Ciphertext use unpadded standard Base64 encoding.
// The nonce is public metadata, not a secret. Ciphertext must not be
// modified without causing authentication failure.
type RVXEnvelope struct {
	Version    string `json:"version"`
	Nonce      string `json:"nonce"`
	Ciphertext string `json:"ciphertext"`
}

// SealRVX encrypts plaintext using AES-256-GCM and a caller-supplied master
// secret. New envelopes use v2, which derives an encryption key with
// HMAC-SHA-256 domain separation.
//
// The masterKey should be a cryptographically random secret containing at
// least 32 bytes. A long, human-chosen password is not a substitute for a
// high-entropy key.
//
// The resulting envelope protects confidentiality and integrity. It does
// not validate RVX syntax, authorize execution, or prove that plaintext is
// safe.
func SealRVX(masterKey string, plain []byte) (RVXEnvelope, error) {
	if err := validateMasterKey(masterKey); err != nil {
		return RVXEnvelope{}, err
	}

	if len(plain) > rvxMaxPlaintextBytes {
		return RVXEnvelope{}, fmt.Errorf(
			"RVX plaintext exceeds the %d-byte limit",
			rvxMaxPlaintextBytes,
		)
	}

	key := deriveRVXKeyV2(masterKey)

	block, err := aes.NewCipher(key)
	if err != nil {
		return RVXEnvelope{}, fmt.Errorf("initialize AES cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return RVXEnvelope{}, fmt.Errorf("initialize AES-GCM: %w", err)
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return RVXEnvelope{}, fmt.Errorf("generate RVX encryption nonce: %w", err)
	}

	ciphertext := gcm.Seal(
		nil,
		nonce,
		plain,
		[]byte(RVXEnvelopeVersionV2),
	)

	if len(ciphertext) > rvxMaxCiphertextBytes {
		return RVXEnvelope{}, errors.New("encrypted RVX payload exceeds the size limit")
	}

	return RVXEnvelope{
		Version:    RVXEnvelopeVersionV2,
		Nonce:      base64.RawStdEncoding.EncodeToString(nonce),
		Ciphertext: base64.RawStdEncoding.EncodeToString(ciphertext),
	}, nil
}

// OpenRVX authenticates and decrypts a supported RVX envelope.
//
// Version v1 uses the original SHA-256-derived key, preserving compatibility
// with envelopes created by the previous candidate implementation.
// Version v2 uses HMAC-SHA-256 domain-separated key derivation.
//
// Authentication must succeed before plaintext is returned. The plaintext
// remains untrusted and must be parsed and validated independently.
func OpenRVX(masterKey string, box RVXEnvelope) ([]byte, error) {
	if err := validateMasterKey(masterKey); err != nil {
		return nil, errors.New("invalid RVX envelope or master key")
	}

	if len(box.Nonce) == 0 ||
		len(box.Nonce) > rvxMaxNonceEncodedBytes ||
		len(box.Ciphertext) == 0 ||
		len(box.Ciphertext) > rvxMaxCiphertextEncodedBytes {
		return nil, errors.New("invalid RVX envelope or master key")
	}

	var key []byte

	switch box.Version {
	case RVXEnvelopeVersionV1:
		key = deriveRVXKeyV1(masterKey)

	case RVXEnvelopeVersionV2:
		key = deriveRVXKeyV2(masterKey)

	default:
		return nil, errors.New("unsupported RVX envelope version")
	}

	nonce, err := decodeCanonicalBase64(box.Nonce)
	if err != nil {
		return nil, errors.New("invalid RVX nonce encoding")
	}

	ciphertext, err := decodeCanonicalBase64(box.Ciphertext)
	if err != nil {
		return nil, errors.New("invalid RVX ciphertext encoding")
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, errors.New("could not initialize RVX decryption")
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, errors.New("could not initialize RVX authentication")
	}

	if len(nonce) != gcm.NonceSize() {
		return nil, errors.New("invalid RVX nonce length")
	}

	if len(ciphertext) < gcm.Overhead() ||
		len(ciphertext) > rvxMaxCiphertextBytes {
		return nil, errors.New("invalid RVX ciphertext length")
	}

	plaintext, err := gcm.Open(
		nil,
		nonce,
		ciphertext,
		[]byte(box.Version),
	)
	if err != nil {
		// Use one authentication error rather than exposing cryptographic
		// details about why an unauthenticated envelope was rejected.
		return nil, errors.New("RVX envelope authentication failed")
	}

	if len(plaintext) > rvxMaxPlaintextBytes {
		return nil, errors.New("decrypted RVX payload exceeds the size limit")
	}

	return plaintext, nil
}

func validateMasterKey(masterKey string) error {
	if len([]byte(masterKey)) < rvxMinMasterKeyBytes {
		return errors.New("master key must contain at least 32 bytes")
	}
	return nil
}

// deriveRVXKeyV1 preserves the previous candidate implementation's key
// derivation for opening previously generated v1 envelopes.
//
// V1 is retained for migration compatibility; new envelopes use v2.
func deriveRVXKeyV1(masterKey string) []byte {
	sum := sha256.Sum256([]byte(masterKey))
	return sum[:]
}

// deriveRVXKeyV2 uses HMAC-SHA-256 with a fixed domain-separation label.
//
// This is a key derivation step for an already high-entropy master secret,
// not a password-hardening function or a replacement for a KDF designed for
// human passwords.
func deriveRVXKeyV2(masterKey string) []byte {
	mac := hmac.New(sha256.New, []byte(masterKey))
	_, _ = mac.Write([]byte("revela-rvx-envelope-v2/aes-256-gcm"))
	return mac.Sum(nil)
}

// decodeCanonicalBase64 accepts only the unpadded standard Base64 format
// emitted by SealRVX. Canonical encoding avoids ambiguous textual forms.
func decodeCanonicalBase64(value string) ([]byte, error) {
	decoded, err := base64.RawStdEncoding.DecodeString(value)
	if err != nil {
		return nil, err
	}

	if base64.RawStdEncoding.EncodeToString(decoded) != value {
		return nil, errors.New("non-canonical Base64 encoding")
	}

	return decoded, nil
}
