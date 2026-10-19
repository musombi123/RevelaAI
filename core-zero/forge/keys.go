// Package forge implements the local API-key request workflow.
//
// Keys remain pending until a human operator approves the request. Only
// a cryptographic hash of an issued secret is persisted. Plaintext secrets
// are returned once to the approving caller and cannot be recovered later.
//
// This package does not itself authenticate human administrators. The API
// layer must authenticate and authorize every approval and revocation request.
package forge

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/mail"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	defaultKeyTTL = 90 * 24 * time.Hour
	maxKeyTTL     = 365 * 24 * time.Hour

	maxNameBytes       = 120
	maxEmailBytes      = 254
	maxReasonBytes     = 1200
	maxActorBytes      = 120
	maxRepositoryBytes = 2048

	maxStoredJSONBytes = 1 << 20
	maxStoredRecords   = 10000
)

type KeyRequest struct {
	ID            string     `json:"id"`
	Name          string     `json:"name"`
	Email         string     `json:"email"`
	RepositoryURL string     `json:"repository_url,omitempty"`
	Reason        string     `json:"reason"`
	Scopes        []string   `json:"scopes"`
	Status        string     `json:"status"`
	CreatedAt     time.Time  `json:"created_at"`
	DecisionAt    *time.Time `json:"decision_at,omitempty"`
	DecisionBy    string     `json:"decision_by,omitempty"`
	IssuedKeyID   string     `json:"issued_key_id,omitempty"`
}

// IssuedKey is the in-memory representation of an API key.
//
// KeyHash is deliberately excluded from ordinary JSON serialization to
// prevent accidental disclosure if a caller serializes IssuedKey directly.
// The dedicated issuedKeyRecord type below persists the hash to disk.
type IssuedKey struct {
	ID        string `json:"id"`
	RequestID string `json:"request_id"`

	KeyHash string `json:"-"`

	Scopes    []string   `json:"scopes"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	ExpiresAt time.Time  `json:"expires_at"`
	RevokedAt *time.Time `json:"revoked_at,omitempty"`
	RevokedBy string     `json:"revoked_by,omitempty"`
}

// issuedKeyRecord is the private persistence representation. It deliberately
// separates persisted secret hashes from the public JSON representation.
type issuedKeyRecord struct {
	ID        string `json:"id"`
	RequestID string `json:"request_id"`
	KeyHash   string `json:"key_hash"`

	Scopes    []string   `json:"scopes"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	ExpiresAt time.Time  `json:"expires_at"`
	RevokedAt *time.Time `json:"revoked_at,omitempty"`
	RevokedBy string     `json:"revoked_by,omitempty"`
}

type KeyManager struct {
	// Root is the managed USECT-ZERO data directory, normally Kernel.CoreRoot.
	// Operations canonicalize and validate this path before accessing records.
	Root string

	// mu protects operations performed through this manager instance.
	// It does not coordinate independent processes or separate KeyManager
	// instances that point at the same directory.
	mu sync.Mutex
}

var allowedScopes = map[string]bool{
	"scan:read":       true,
	"heal:propose":    true,
	"assemble:propose": true,
	"radar:compare":   true,
	"mind:compile":   true,
	"bridge:propose": true,
}

// New creates a key manager. Filesystem errors are reported by the operations
// that use the manager, preserving the existing constructor signature.
func New(root string) *KeyManager {
	root = strings.TrimSpace(root)
	if root == "" {
		return &KeyManager{}
	}

	abs, err := filepath.Abs(root)
	if err == nil {
		root = filepath.Clean(abs)

		// Canonicalize an existing root so ordinary symlink aliases are not
		// retained as the manager's working path.
		if resolved, resolveErr := filepath.EvalSymlinks(root); resolveErr == nil {
			root = filepath.Clean(resolved)
		}
	}

	return &KeyManager{Root: root}
}

// newID creates a 96-bit cryptographically random lowercase hexadecimal ID.
func newID() (string, error) {
	raw := make([]byte, 12)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("generate resource ID: %w", err)
	}

	return hex.EncodeToString(raw), nil
}

func validID(id string) bool {
	if len(id) != 24 || id != strings.ToLower(id) {
		return false
	}

	raw, err := hex.DecodeString(id)
	return err == nil && len(raw) == 12
}

func keyHash(secret string) string {
	sum := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(sum[:])
}

func cloneScopes(scopes []string) []string {
	return append([]string(nil), scopes...)
}

func cloneTime(value *time.Time) *time.Time {
	if value == nil {
		return nil
	}

	copied := *value
	return &copied
}

func cloneRequest(request KeyRequest) KeyRequest {
	request.Scopes = cloneScopes(request.Scopes)
	request.DecisionAt = cloneTime(request.DecisionAt)
	return request
}

func cloneIssuedKey(key IssuedKey) IssuedKey {
	key.Scopes = cloneScopes(key.Scopes)
	key.RevokedAt = cloneTime(key.RevokedAt)
	return key
}

func toIssuedKeyRecord(key IssuedKey) issuedKeyRecord {
	return issuedKeyRecord{
		ID:        key.ID,
		RequestID: key.RequestID,
		KeyHash:   key.KeyHash,
		Scopes:    cloneScopes(key.Scopes),
		Status:    key.Status,
		CreatedAt: key.CreatedAt,
		ExpiresAt: key.ExpiresAt,
		RevokedAt: cloneTime(key.RevokedAt),
		RevokedBy: key.RevokedBy,
	}
}

func fromIssuedKeyRecord(record issuedKeyRecord) IssuedKey {
	return IssuedKey{
		ID:        record.ID,
		RequestID: record.RequestID,
		KeyHash:   record.KeyHash,
		Scopes:    cloneScopes(record.Scopes),
		Status:    record.Status,
		CreatedAt: record.CreatedAt,
		ExpiresAt: record.ExpiresAt,
		RevokedAt: cloneTime(record.RevokedAt),
		RevokedBy: record.RevokedBy,
	}
}

// ensureRoot validates or initializes the configured data root.
//
// KeyManager methods call this while holding mu.
func (m *KeyManager) ensureRoot() (string, error) {
	if m == nil {
		return "", errors.New("key manager is not initialized")
	}

	configured := strings.TrimSpace(m.Root)
	if configured == "" {
		return "", errors.New("key store root is not configured")
	}

	abs, err := filepath.Abs(configured)
	if err != nil {
		return "", fmt.Errorf("resolve key store root: %w", err)
	}
	abs = filepath.Clean(abs)

	info, err := os.Lstat(abs)
	if errors.Is(err, os.ErrNotExist) {
		if err := os.MkdirAll(abs, 0700); err != nil {
			return "", fmt.Errorf("create key store root: %w", err)
		}
		info, err = os.Lstat(abs)
	}
	if err != nil {
		return "", fmt.Errorf("inspect key store root: %w", err)
	}

	if info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("key store root must not be a symbolic link")
	}
	if !info.IsDir() {
		return "", errors.New("key store root is not a directory")
	}

	resolved, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return "", fmt.Errorf("resolve key store root: %w", err)
	}

	resolved = filepath.Clean(resolved)
	m.Root = resolved

	return resolved, nil
}

// secureDirectory walks a directory path component by component, refusing
// symlinked or non-directory components. When create is true, missing
// components are created with owner-only permissions.
func secureDirectory(root, relative string, create bool) (string, error) {
	clean, err := cleanRelativePath(relative)
	if err != nil {
		return "", err
	}

	current := filepath.Clean(root)
	parts := strings.Split(clean, string(filepath.Separator))

	for _, part := range parts {
		if part == "" || part == "." || part == ".." {
			return "", errors.New("invalid managed directory component")
		}

		current = filepath.Join(current, part)

		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) && create {
			if err := os.Mkdir(current, 0700); err != nil && !errors.Is(err, os.ErrExist) {
				return "", fmt.Errorf("create managed directory: %w", err)
			}
			info, err = os.Lstat(current)
		}

		if err != nil {
			return "", fmt.Errorf("inspect managed directory: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("refusing a symlinked key store directory")
		}
		if !info.IsDir() {
			return "", errors.New("managed key store path is not a directory")
		}

		if create {
			if err := os.Chmod(current, 0700); err != nil {
				return "", fmt.Errorf("secure managed directory permissions: %w", err)
			}
		}
	}

	return current, nil
}

func cleanRelativePath(relative string) (string, error) {
	if relative == "" || strings.ContainsRune(relative, '\x00') || filepath.IsAbs(relative) {
		return "", errors.New("managed path must be a non-empty relative path")
	}

	relative = filepath.FromSlash(relative)
	if filepath.VolumeName(relative) != "" {
		return "", errors.New("managed path must not contain a volume name")
	}

	clean := filepath.Clean(relative)
	if clean == "." ||
		clean == ".." ||
		filepath.IsAbs(clean) ||
		strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", errors.New("managed path escapes the key store root")
	}

	return clean, nil
}

// dirs initializes the key store layout. Callers must hold m.mu.
func (m *KeyManager) dirs() error {
	root, err := m.ensureRoot()
	if err != nil {
		return err
	}

	for _, directory := range []string{
		"state",
		"state/keys",
		"state/keys/requests",
		"state/keys/issued",
	} {
		if _, err := secureDirectory(root, directory, true); err != nil {
			return fmt.Errorf("initialize key store directory: %w", err)
		}
	}

	return nil
}

// filePath returns a validated managed path and refuses symlinked final
// components. It does not open or modify the returned file.
func (m *KeyManager) filePath(relative string) (string, error) {
	root, err := m.ensureRoot()
	if err != nil {
		return "", err
	}

	clean, err := cleanRelativePath(relative)
	if err != nil {
		return "", err
	}

	parent := filepath.Dir(clean)
	if parent != "." {
		if _, err := secureDirectory(root, parent, false); err != nil {
			return "", err
		}
	}

	dst := filepath.Join(root, clean)
	info, err := os.Lstat(dst)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("refusing a symlinked key record")
		}
		if !info.Mode().IsRegular() {
			return "", errors.New("key record path is not a regular file")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("inspect key record path: %w", err)
	}

	return dst, nil
}

// write persists a JSON document through a same-directory temporary file.
// The temporary file has restrictive permissions and is synced before rename.
func write(path string, value any) error {
	parent := filepath.Dir(path)

	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return fmt.Errorf("inspect key record directory: %w", err)
	}
	if parentInfo.Mode()&os.ModeSymlink != 0 || !parentInfo.IsDir() {
		return errors.New("key record parent is not a safe directory")
	}

	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return fmt.Errorf("encode key record: %w", err)
	}
	encoded = append(encoded, '\n')

	if len(encoded) > maxStoredJSONBytes {
		return errors.New("key record exceeds the maximum permitted size")
	}

	// Validate an existing destination before preparing the replacement.
	info, statErr := os.Lstat(path)
	if statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return errors.New("refusing to replace an unsafe key record")
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return fmt.Errorf("inspect destination key record: %w", statErr)
	}

	tmp, err := os.CreateTemp(parent, ".usect-zero-key-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary key record: %w", err)
	}

	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)

	if err := tmp.Chmod(0600); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("secure temporary key record: %w", err)
	}

	n, err := tmp.Write(encoded)
	if err != nil {
		_ = tmp.Close()
		return fmt.Errorf("write temporary key record: %w", err)
	}
	if n != len(encoded) {
		_ = tmp.Close()
		return io.ErrShortWrite
	}

	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("sync temporary key record: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("close temporary key record: %w", err)
	}

	// Recheck the target. Rename replaces the directory entry instead of
	// opening and writing through a destination symlink.
	info, statErr = os.Lstat(path)
	if statErr == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return errors.New("key record destination changed to an unsafe file")
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return fmt.Errorf("recheck destination key record: %w", statErr)
	}

	if err := os.Rename(tmpPath, path); err != nil {
		return fmt.Errorf("commit key record: %w", err)
	}

	// The record contents have been synced before rename. Directory syncing
	// is best-effort because support varies by operating system/filesystem.
	syncDirectoryBestEffort(parent)

	return nil
}

// syncDirectoryBestEffort requests persistence of directory metadata where
// supported. A failure is not interpreted as proof that the rename failed.
func syncDirectoryBestEffort(path string) {
	directory, err := os.Open(path)
	if err != nil {
		return
	}
	defer directory.Close()

	_ = directory.Sync()
}

// read decodes one bounded JSON value, rejecting unknown fields, trailing
// data, symlinks and non-regular files.
func read(path string, value any) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("refusing an unsafe key record")
	}
	if info.Size() > maxStoredJSONBytes {
		return errors.New("key record exceeds the maximum permitted size")
	}

	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open key record: %w", err)
	}

	openedInfo, statErr := file.Stat()
	pathInfo, pathErr := os.Lstat(path)

	if statErr != nil || pathErr != nil ||
		pathInfo.Mode()&os.ModeSymlink != 0 ||
		!openedInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, pathInfo) {
		_ = file.Close()
		return errors.New("key record changed or is not a safe regular file")
	}

	raw, readErr := io.ReadAll(io.LimitReader(file, maxStoredJSONBytes+1))
	closeErr := file.Close()

	if readErr != nil {
		return fmt.Errorf("read key record: %w", readErr)
	}
	if closeErr != nil {
		return fmt.Errorf("close key record: %w", closeErr)
	}
	if len(raw) > maxStoredJSONBytes {
		return errors.New("key record exceeds the maximum permitted size")
	}

	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(value); err != nil {
		return fmt.Errorf("decode key record: %w", err)
	}

	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return errors.New("key record must contain exactly one JSON value")
		}
		return fmt.Errorf("invalid trailing key record data: %w", err)
	}

	return nil
}

func (m *KeyManager) writeRequest(path string, request KeyRequest) error {
	return write(path, cloneRequest(request))
}

func (m *KeyManager) readRequest(path string) (KeyRequest, error) {
	var request KeyRequest
	if err := read(path, &request); err != nil {
		return KeyRequest{}, err
	}
	return request, nil
}

func (m *KeyManager) writeIssued(path string, key IssuedKey) error {
	// Always use the private persistence DTO so the key hash is stored on
	// disk even though normal JSON serialization of IssuedKey hides it.
	return write(path, toIssuedKeyRecord(key))
}

func (m *KeyManager) readIssued(path string) (IssuedKey, error) {
	var record issuedKeyRecord
	if err := read(path, &record); err != nil {
		return IssuedKey{}, err
	}
	return fromIssuedKeyRecord(record), nil
}

func validateText(
	name string,
	value string,
	minBytes int,
	maxBytes int,
	allowLineBreaks bool,
) error {
	if !utf8.ValidString(value) {
		return fmt.Errorf("%s must contain valid UTF-8", name)
	}
	if len(value) < minBytes || len(value) > maxBytes {
		return fmt.Errorf("%s must be between %d and %d bytes", name, minBytes, maxBytes)
	}
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s must not be empty", name)
	}

	for _, ch := range value {
		if !unicode.IsControl(ch) {
			continue
		}

		if allowLineBreaks && (ch == '\n' || ch == '\r' || ch == '\t') {
			continue
		}

		return fmt.Errorf("%s contains an unsupported control character", name)
	}

	return nil
}

func validateEmail(value string) error {
	if err := validateText("email", value, 3, maxEmailBytes, false); err != nil {
		return err
	}

	if strings.ContainsAny(value, " \t\r\n") {
		return errors.New("email must be a single mailbox address")
	}

	parsed, err := mail.ParseAddress(value)
	if err != nil || parsed.Address != value {
		return errors.New("email must be a valid mailbox address")
	}

	return nil
}

func validateRepositoryURL(value string) error {
	if value == "" {
		return nil
	}

	if err := validateText(
		"repository_url",
		value,
		1,
		maxRepositoryBytes,
		false,
	); err != nil {
		return err
	}

	parsed, err := url.Parse(value)
	if err != nil {
		return errors.New("repository_url must be a valid HTTPS URL")
	}

	if !strings.EqualFold(parsed.Scheme, "https") ||
		parsed.Host == "" ||
		parsed.Hostname() == "" ||
		parsed.User != nil ||
		parsed.Opaque != "" ||
		parsed.Fragment != "" {
		return errors.New(
			"repository_url must use HTTPS and must not contain credentials or a fragment",
		)
	}

	return nil
}

func cleanScopes(scopes []string) ([]string, error) {
	if len(scopes) == 0 {
		// Preserve the original safe default: read-only scan access.
		scopes = []string{"scan:read"}
	}

	if len(scopes) > len(allowedScopes) {
		return nil, errors.New("too many requested scopes")
	}

	set := make(map[string]bool, len(scopes))

	for _, scope := range scopes {
		scope = strings.TrimSpace(scope)
		if !allowedScopes[scope] {
			return nil, fmt.Errorf("scope %q is not requestable", scope)
		}
		set[scope] = true
	}

	result := make([]string, 0, len(set))
	for scope := range set {
		result = append(result, scope)
	}
	sort.Strings(result)

	return result, nil
}

// validateStoredScopes validates scopes without silently defaulting, trimming,
// or correcting persisted security metadata.
func validateStoredScopes(scopes []string) error {
	if len(scopes) == 0 || len(scopes) > len(allowedScopes) {
		return errors.New("stored scopes have an invalid count")
	}

	seen := make(map[string]bool, len(scopes))
	for _, scope := range scopes {
		if scope == "" || strings.TrimSpace(scope) != scope || !allowedScopes[scope] {
			return fmt.Errorf("stored scope %q is invalid", scope)
		}
		if seen[scope] {
			return fmt.Errorf("stored scope %q is duplicated", scope)
		}
		seen[scope] = true
	}

	return nil
}

func validateActor(actor string) (string, error) {
	actor = strings.TrimSpace(actor)
	if err := validateText("actor", actor, 1, maxActorBytes, false); err != nil {
		return "", err
	}

	return actor, nil
}

func validateRequestFields(name, email, repo, reason string) error {
	if err := validateText("name", name, 2, maxNameBytes, false); err != nil {
		return err
	}
	if err := validateEmail(email); err != nil {
		return err
	}
	if err := validateRepositoryURL(repo); err != nil {
		return err
	}
	if err := validateText("reason", reason, 8, maxReasonBytes, true); err != nil {
		return errors.New(
			"name, valid email, and an 8–1200 byte reason are required; reason contains unsupported content",
		)
	}

	return nil
}

func validateRequestRecord(request KeyRequest, expectedID string) error {
	if !validID(expectedID) || !validID(request.ID) || request.ID != expectedID {
		return errors.New("key request identifier does not match its filename")
	}

	if err := validateRequestFields(
		request.Name,
		request.Email,
		request.RepositoryURL,
		request.Reason,
	); err != nil {
		return fmt.Errorf("invalid stored key request fields: %w", err)
	}

	if err := validateStoredScopes(request.Scopes); err != nil {
		return fmt.Errorf("invalid stored key request scopes: %w", err)
	}

	if request.CreatedAt.IsZero() {
		return errors.New("stored key request has no creation timestamp")
	}

	switch request.Status {
	case "pending_approval":
		if request.DecisionAt != nil ||
			request.DecisionBy != "" ||
			request.IssuedKeyID != "" {
			return errors.New("pending key request contains decision metadata")
		}

	case "approved":
		if request.DecisionAt == nil ||
			request.DecisionAt.IsZero() ||
			!validID(request.IssuedKeyID) {
			return errors.New("approved key request has incomplete decision metadata")
		}
		if _, err := validateActor(request.DecisionBy); err != nil {
			return errors.New("approved key request has an invalid decision actor")
		}

	case "rejected":
		if request.DecisionAt == nil ||
			request.DecisionAt.IsZero() ||
			request.IssuedKeyID != "" {
			return errors.New("rejected key request has invalid decision metadata")
		}
		if _, err := validateActor(request.DecisionBy); err != nil {
			return errors.New("rejected key request has an invalid decision actor")
		}

	default:
		return fmt.Errorf("unsupported stored key request status %q", request.Status)
	}

	return nil
}

func validateIssuedRecord(key IssuedKey, expectedID string) error {
	if !validID(expectedID) || !validID(key.ID) || key.ID != expectedID {
		return errors.New("issued key identifier does not match its filename")
	}
	if !validID(key.RequestID) {
		return errors.New("issued key has an invalid request identifier")
	}

	hashBytes, err := hex.DecodeString(key.KeyHash)
	if err != nil || len(hashBytes) != sha256.Size ||
		key.KeyHash != strings.ToLower(key.KeyHash) {
		return errors.New("issued key has an invalid key hash")
	}

	if err := validateStoredScopes(key.Scopes); err != nil {
		return fmt.Errorf("issued key scopes are invalid: %w", err)
	}

	if key.CreatedAt.IsZero() || key.ExpiresAt.IsZero() ||
		!key.ExpiresAt.After(key.CreatedAt) {
		return errors.New("issued key has invalid lifetime metadata")
	}

	switch key.Status {
	case "active":
		if key.RevokedAt != nil || key.RevokedBy != "" {
			return errors.New("active key contains revocation metadata")
		}

	case "revoked":
		if key.RevokedAt == nil ||
			key.RevokedAt.IsZero() ||
			key.RevokedAt.Before(key.CreatedAt) {
			return errors.New("revoked key has invalid revocation timestamp")
		}
		if _, err := validateActor(key.RevokedBy); err != nil {
			return errors.New("revoked key has invalid revocation actor")
		}

	default:
		return fmt.Errorf("unsupported stored issued-key status %q", key.Status)
	}

	return nil
}

// Request stores a key request in pending_approval state. It does not issue
// a secret or grant any API privileges.
func (m *KeyManager) Request(
	name,
	email,
	repo,
	reason string,
	scopes []string,
) (KeyRequest, error) {
	name = strings.TrimSpace(name)
	email = strings.TrimSpace(email)
	repo = strings.TrimSpace(repo)
	reason = strings.TrimSpace(reason)

	if err := validateRequestFields(name, email, repo, reason); err != nil {
		return KeyRequest{}, err
	}

	clean, err := cleanScopes(scopes)
	if err != nil {
		return KeyRequest{}, err
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return KeyRequest{}, fmt.Errorf("key store unavailable: %w", err)
	}

	for attempt := 0; attempt < 3; attempt++ {
		id, err := newID()
		if err != nil {
			return KeyRequest{}, err
		}

		path, err := m.filePath(filepath.Join("state", "keys", "requests", id+".json"))
		if err != nil {
			return KeyRequest{}, err
		}

		if _, err := os.Lstat(path); err == nil {
			// Cryptographically improbable ID collision; generate another ID
			// rather than overwriting an existing request.
			continue
		} else if !errors.Is(err, os.ErrNotExist) {
			return KeyRequest{}, fmt.Errorf("inspect new request destination: %w", err)
		}

		request := KeyRequest{
			ID:            id,
			Name:          name,
			Email:         email,
			RepositoryURL: repo,
			Reason:        reason,
			Scopes:        cloneScopes(clean),
			Status:        "pending_approval",
			CreatedAt:     time.Now().UTC(),
		}

		if err := m.writeRequest(path, request); err != nil {
			return KeyRequest{}, fmt.Errorf("persist key request: %w", err)
		}

		return cloneRequest(request), nil
	}

	return KeyRequest{}, errors.New("could not allocate a unique key request ID")
}

// Approve issues a random API key after an authorized caller explicitly
// approves the request. The caller must return the plaintext secret only once.
//
// The API layer must authenticate and authorize the human operator before
// invoking this method.
func (m *KeyManager) Approve(
	id,
	actor string,
	ttl time.Duration,
) (KeyRequest, string, error) {
	if !validID(id) {
		return KeyRequest{}, "", os.ErrNotExist
	}

	actor, err := validateActor(actor)
	if err != nil {
		return KeyRequest{}, "", err
	}

	if ttl <= 0 {
		ttl = defaultKeyTTL
	}
	if ttl > maxKeyTTL {
		return KeyRequest{}, "", fmt.Errorf(
			"key lifetime exceeds maximum of %s",
			maxKeyTTL,
		)
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return KeyRequest{}, "", fmt.Errorf("key store unavailable: %w", err)
	}

	requestPath, err := m.filePath(filepath.Join("state", "keys", "requests", id+".json"))
	if err != nil {
		return KeyRequest{}, "", err
	}

	request, err := m.readRequest(requestPath)
	if err != nil {
		return KeyRequest{}, "", fmt.Errorf("read key request: %w", err)
	}
	if err := validateRequestRecord(request, id); err != nil {
		return KeyRequest{}, "", fmt.Errorf("key request integrity check failed: %w", err)
	}
	if request.Status != "pending_approval" {
		return cloneRequest(request), "", errors.New("request is not pending approval")
	}

	secretBytes := make([]byte, 32)
	if _, err := rand.Read(secretBytes); err != nil {
		return KeyRequest{}, "", fmt.Errorf("generate API key secret: %w", err)
	}
	secret := "uz0_" + base64.RawURLEncoding.EncodeToString(secretBytes)

	keyID, err := newID()
	if err != nil {
		return KeyRequest{}, "", err
	}

	now := time.Now().UTC()
	issued := IssuedKey{
		ID:        keyID,
		RequestID: id,
		KeyHash:   keyHash(secret),
		Scopes:    cloneScopes(request.Scopes),
		Status:    "active",
		CreatedAt: now,
		ExpiresAt: now.Add(ttl),
	}

	if err := validateIssuedRecord(issued, keyID); err != nil {
		return KeyRequest{}, "", fmt.Errorf("internal issued-key validation failed: %w", err)
	}

	issuedPath, err := m.filePath(filepath.Join("state", "keys", "issued", keyID+".json"))
	if err != nil {
		return KeyRequest{}, "", err
	}

	if _, err := os.Lstat(issuedPath); err == nil {
		return KeyRequest{}, "", errors.New("issued key identifier collision")
	} else if !errors.Is(err, os.ErrNotExist) {
		return KeyRequest{}, "", fmt.Errorf("inspect issued key destination: %w", err)
	}

	if err := m.writeIssued(issuedPath, issued); err != nil {
		return KeyRequest{}, "", fmt.Errorf("persist issued key: %w", err)
	}

	request.Status = "approved"
	request.IssuedKeyID = keyID
	request.DecisionAt = &now
	request.DecisionBy = actor

	if err := validateRequestRecord(request, id); err != nil {
		rollbackErr := removeManagedFile(issuedPath)
		if rollbackErr != nil {
			return KeyRequest{}, "", fmt.Errorf(
				"request integrity check failed: %v; issued-key rollback also failed: %w",
				err,
				rollbackErr,
			)
		}
		return KeyRequest{}, "", fmt.Errorf("request integrity check failed: %w", err)
	}

	if err := m.writeRequest(requestPath, request); err != nil {
		rollbackErr := removeManagedFile(issuedPath)
		if rollbackErr != nil {
			return KeyRequest{}, "", fmt.Errorf(
				"persist approved request: %v; issued-key rollback also failed: %w",
				err,
				rollbackErr,
			)
		}
		return KeyRequest{}, "", fmt.Errorf("persist approved request: %w", err)
	}

	return cloneRequest(request), secret, nil
}

// ListRequests returns validated request records newest first.
//
// A corrupt record fails the listing rather than being silently omitted from
// the operator's view of pending or completed key requests.
func (m *KeyManager) ListRequests(status string) ([]KeyRequest, error) {
	status = strings.TrimSpace(status)
	switch status {
	case "", "pending_approval", "approved", "rejected":
	default:
		return nil, errors.New("unsupported key request status filter")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return nil, fmt.Errorf("key store unavailable: %w", err)
	}

	files, err := m.recordFiles(filepath.Join("state", "keys", "requests"))
	if err != nil {
		return nil, err
	}

	items := make([]KeyRequest, 0, len(files))
	for _, record := range files {
		request, err := m.readRequest(record.path)
		if err != nil {
			return nil, fmt.Errorf("read request record %q: %w", record.id, err)
		}

		if err := validateRequestRecord(request, record.id); err != nil {
			return nil, fmt.Errorf("request record %q failed validation: %w", record.id, err)
		}

		if status == "" || request.Status == status {
			items = append(items, cloneRequest(request))
		}
	}

	sort.Slice(items, func(i, j int) bool {
		if items[i].CreatedAt.Equal(items[j].CreatedAt) {
			return items[i].ID < items[j].ID
		}
		return items[i].CreatedAt.After(items[j].CreatedAt)
	})

	return items, nil
}

// ListIssued returns validated key metadata newest first.
//
// Expiration is computed dynamically. A key whose persisted status is active
// is reported as expired when its expiration time has arrived. Callers must
// project safe public fields rather than exposing key-management internals.
func (m *KeyManager) ListIssued(status string) ([]IssuedKey, error) {
	status = strings.TrimSpace(status)
	switch status {
	case "", "active", "revoked", "expired":
	default:
		return nil, errors.New("unsupported issued-key status filter")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return nil, fmt.Errorf("key store unavailable: %w", err)
	}

	files, err := m.recordFiles(filepath.Join("state", "keys", "issued"))
	if err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	items := make([]IssuedKey, 0, len(files))

	for _, record := range files {
		key, err := m.readIssued(record.path)
		if err != nil {
			return nil, fmt.Errorf("read issued-key record %q: %w", record.id, err)
		}

		if err := validateIssuedRecord(key, record.id); err != nil {
			return nil, fmt.Errorf("issued-key record %q failed validation: %w", record.id, err)
		}

		effectiveStatus := key.Status
		if effectiveStatus == "active" && !now.Before(key.ExpiresAt) {
			effectiveStatus = "expired"
		}
		if status != "" && effectiveStatus != status {
			continue
		}

		key.Status = effectiveStatus
		items = append(items, cloneIssuedKey(key))
	}

	sort.Slice(items, func(i, j int) bool {
		if items[i].CreatedAt.Equal(items[j].CreatedAt) {
			return items[i].ID < items[j].ID
		}
		return items[i].CreatedAt.After(items[j].CreatedAt)
	})

	return items, nil
}

type recordFile struct {
	id   string
	path string
}

// recordFiles discovers JSON record files in a known managed directory.
// Malformed filenames, symlinked records and special files cause an error
// rather than being silently skipped.
func (m *KeyManager) recordFiles(relativeDirectory string) ([]recordFile, error) {
	root, err := m.ensureRoot()
	if err != nil {
		return nil, err
	}

	directory, err := secureDirectory(root, relativeDirectory, false)
	if err != nil {
		return nil, err
	}

	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, fmt.Errorf("list key store records: %w", err)
	}

	result := make([]recordFile, 0, len(entries))

	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}

		if len(result) >= maxStoredRecords {
			return nil, fmt.Errorf("record count exceeds maximum of %d", maxStoredRecords)
		}

		id := strings.TrimSuffix(entry.Name(), ".json")
		if !validID(id) {
			return nil, fmt.Errorf("invalid key record filename %q", entry.Name())
		}

		path, err := m.filePath(filepath.Join(relativeDirectory, entry.Name()))
		if err != nil {
			return nil, fmt.Errorf("validate key record %q: %w", entry.Name(), err)
		}

		info, err := os.Lstat(path)
		if err != nil {
			return nil, fmt.Errorf("inspect key record %q: %w", entry.Name(), err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return nil, fmt.Errorf("key record %q is not a regular file", entry.Name())
		}

		result = append(result, recordFile{
			id:   id,
			path: path,
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].id < result[j].id
	})

	return result, nil
}

// Revoke revokes an issued key. The API layer must authorize the actor before
// calling this method. Revoked keys cannot subsequently pass Validate.
func (m *KeyManager) Revoke(id, actor string) (IssuedKey, error) {
	if !validID(id) {
		return IssuedKey{}, os.ErrNotExist
	}

	actor, err := validateActor(actor)
	if err != nil {
		return IssuedKey{}, err
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return IssuedKey{}, fmt.Errorf("key store unavailable: %w", err)
	}

	path, err := m.filePath(filepath.Join("state", "keys", "issued", id+".json"))
	if err != nil {
		return IssuedKey{}, err
	}

	key, err := m.readIssued(path)
	if err != nil {
		return IssuedKey{}, fmt.Errorf("read issued key: %w", err)
	}
	if err := validateIssuedRecord(key, id); err != nil {
		return IssuedKey{}, fmt.Errorf("issued-key integrity check failed: %w", err)
	}
	if key.Status != "active" {
		return cloneIssuedKey(key), errors.New("key is not active")
	}

	now := time.Now().UTC()
	key.Status = "revoked"
	key.RevokedAt = &now
	key.RevokedBy = actor

	if err := validateIssuedRecord(key, id); err != nil {
		return IssuedKey{}, fmt.Errorf("revocation metadata validation failed: %w", err)
	}
	if err := m.writeIssued(path, key); err != nil {
		return IssuedKey{}, fmt.Errorf("persist key revocation: %w", err)
	}

	return cloneIssuedKey(key), nil
}

// Validate checks a presented secret and requested scope.
//
// It fails closed on inaccessible, malformed or corrupt persisted key records.
// On failure it returns no key ID. Only an active, unexpired key with the
// requested explicit scope is accepted.
func (m *KeyManager) Validate(secret, scope string) (bool, string) {
	if m == nil || secret == "" || !allowedScopes[scope] {
		return false, ""
	}

	// Issued secrets have a fixed format: prefix plus 32 bytes encoded as
	// unpadded base64url. Reject malformed input before filesystem access.
	const prefix = "uz0_"
	if !strings.HasPrefix(secret, prefix) {
		return false, ""
	}

	encoded := strings.TrimPrefix(secret, prefix)
	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil || len(raw) != 32 ||
		base64.RawURLEncoding.EncodeToString(raw) != encoded {
		return false, ""
	}

	presentedHash := sha256.Sum256([]byte(secret))

	m.mu.Lock()
	defer m.mu.Unlock()

	if err := m.dirs(); err != nil {
		return false, ""
	}

	files, err := m.recordFiles(filepath.Join("state", "keys", "issued"))
	if err != nil {
		return false, ""
	}

	now := time.Now().UTC()
	matchCount := 0
	var matchedID string
	var authorized bool

	for _, record := range files {
		key, err := m.readIssued(record.path)
		if err != nil {
			return false, ""
		}
		if err := validateIssuedRecord(key, record.id); err != nil {
			return false, ""
		}

		storedHash, err := hex.DecodeString(key.KeyHash)
		if err != nil || len(storedHash) != sha256.Size {
			return false, ""
		}

		matches := subtle.ConstantTimeCompare(storedHash, presentedHash[:])
		if matches != 1 {
			continue
		}

		matchCount++
		matchedID = key.ID
		authorized = key.Status == "active" && now.Before(key.ExpiresAt)

		hasScope := false
		for _, grantedScope := range key.Scopes {
			if grantedScope == scope {
				hasScope = true
			}
		}
		authorized = authorized && hasScope
	}

	// Duplicate secret hashes indicate corrupted or inconsistent state.
	if matchCount != 1 || !authorized {
		return false, ""
	}

	return true, matchedID
}

// removeManagedFile safely removes a regular record file during rollback.
// It does not follow symbolic links.
func removeManagedFile(path string) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect rollback target: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("refusing to remove an unsafe rollback target")
	}

	if err := os.Remove(path); err != nil {
		return fmt.Errorf("remove rollback record: %w", err)
	}

	syncDirectoryBestEffort(filepath.Dir(path))
	return nil
}
