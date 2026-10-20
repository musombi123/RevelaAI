package genesis

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"time"
)

const (
	toolActionConfirmationTTL = 2 * time.Minute
	maxPendingToolConfirmations = 4096
)

type pendingToolActionConfirmation struct {
	Name        string
	Version     string
	ArtifactHash string
	ArgumentsHash string
	ExpiresAt   time.Time
}

var (
	toolActionConfirmationMu sync.Mutex
	toolActionConfirmations = make(map[string]pendingToolActionConfirmation)
)

// IssueToolActionConfirmation creates a one-use confirmation bound to one
// signed Tier 2 version and the exact JSON arguments. It is issued only after
// the human-facing API has authenticated its action-approval credential.
func IssueToolActionConfirmation(coreRoot, name, version, artifactHash string, input []byte) (string, time.Time, error) {
	if len(input) == 0 || len(input) > 64*1024 || !json.Valid(input) {
		return "", time.Time{}, errors.New("action arguments must be valid bounded JSON")
	}
	record, err := loadSignedToolArtifact(coreRoot, name, version, artifactHash)
	if err != nil {
		return "", time.Time{}, err
	}
	if record.Manifest.RiskTier != 2 {
		return "", time.Time{}, errors.New("per-action confirmation tokens are reserved for Tier 2 tools")
	}
	root, err := registryRoot(coreRoot)
	if err != nil {
		return "", time.Time{}, err
	}
	pointer, err := readActivePointer(root, name)
	if err != nil || !pointer.Active || pointer.Version != version || pointer.ArtifactHash != artifactHash {
		return "", time.Time{}, errors.New("Tier 2 confirmation requires the exact active signed version")
	}
	if !constantTimeStringEqual(pointer.OwnerApprovalHash, artifactHash) {
		return "", time.Time{}, errors.New("Tier 2 version requires owner approval bound to its artifact hash")
	}
	nonce := make([]byte, 32)
	if _, err := rand.Read(nonce); err != nil {
		return "", time.Time{}, errors.New("could not create a one-time action confirmation")
	}
	token := hex.EncodeToString(nonce)
	digest := sha256.Sum256(input)
	expires := time.Now().UTC().Add(toolActionConfirmationTTL)
	toolActionConfirmationMu.Lock()
	defer toolActionConfirmationMu.Unlock()
	now := time.Now().UTC()
	for existing, pending := range toolActionConfirmations {
		if !pending.ExpiresAt.After(now) {
			delete(toolActionConfirmations, existing)
		}
	}
	if len(toolActionConfirmations) >= maxPendingToolConfirmations {
		return "", time.Time{}, errors.New("too many pending Tier 2 confirmations; retry after existing tokens expire")
	}
	toolActionConfirmations[token] = pendingToolActionConfirmation{
		Name: name, Version: version, ArtifactHash: artifactHash,
		ArgumentsHash: hex.EncodeToString(digest[:]), ExpiresAt: expires,
	}
	return token, expires, nil
}

// consumeToolActionConfirmation atomically consumes a one-use confirmation.
func consumeToolActionConfirmation(token, name, version, artifactHash string, input []byte) error {
	if len(token) != 64 || strings.Trim(token, "0123456789abcdef") != "" {
		return errors.New("Tier 2 action requires a valid one-time human confirmation")
	}
	digest := sha256.Sum256(input)
	inputHash := hex.EncodeToString(digest[:])
	toolActionConfirmationMu.Lock()
	defer toolActionConfirmationMu.Unlock()
	pending, ok := toolActionConfirmations[token]
	if !ok {
		return errors.New("Tier 2 action confirmation is missing, expired, or already used")
	}
	// Consume even a mismatched attempt so a token cannot be tried against
	// multiple argument values or artifacts.
	delete(toolActionConfirmations, token)
	if !pending.ExpiresAt.After(time.Now().UTC()) ||
		pending.Name != name || pending.Version != version ||
		!constantTimeStringEqual(pending.ArtifactHash, artifactHash) ||
		!constantTimeStringEqual(pending.ArgumentsHash, inputHash) {
		return errors.New("Tier 2 action confirmation does not match the exact action")
	}
	return nil
}
