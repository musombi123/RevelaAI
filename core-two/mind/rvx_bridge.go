// Package mind exposes the shared Core-Two RVX protection API.
//
// Cryptographic operations are delegated to the canonical Core-Two RVX
// package to prevent duplicate implementations and keep envelope handling
// consistent across callers.
package mind

import "revela-mind.local/core-two/rvx"

// RVXEnvelope is an alias of the canonical RVX envelope type.
// The alias preserves type compatibility with package rvx.
type RVXEnvelope = rvx.Envelope

// SealRVX seals plaintext using the canonical RVX implementation.
//
// Key validation, key derivation, encryption, nonce generation, and envelope
// versioning are controlled by rvx.Seal.
func SealRVX(masterKey string, plaintext []byte) (RVXEnvelope, error) {
	return rvx.Seal(masterKey, plaintext)
}

// OpenRVX authenticates and decrypts an RVX envelope using the canonical
// implementation. Authentication failures are returned by rvx.Open.
func OpenRVX(masterKey string, envelope RVXEnvelope) ([]byte, error) {
	return rvx.Open(masterKey, envelope)
}
