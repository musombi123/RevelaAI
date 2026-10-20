package forge

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const (
	testName   = "Example Developer"
	testEmail  = "dev@example.invalid"
	testReason = "Need to run deterministic repository scans"
	testActor  = "test-human"
)

func newTestKeyManager(t *testing.T) (*KeyManager, string) {
	t.Helper()

	root := t.TempDir()
	manager := New(root)

	return manager, root
}

func requestTestKey(t *testing.T, manager *KeyManager, scopes []string) KeyRequest {
	t.Helper()

	request, err := manager.Request(
		testName,
		testEmail,
		"https://github.com/example/project",
		testReason,
		scopes,
	)
	if err != nil {
		t.Fatalf("request API key: %v", err)
	}

	if request.Status != "pending_approval" {
		t.Fatalf("new request should be pending approval, got %q", request.Status)
	}

	return request
}

func approveTestKey(
	t *testing.T,
	manager *KeyManager,
	requestID string,
	ttl time.Duration,
) (KeyRequest, string) {
	t.Helper()

	request, secret, err := manager.Approve(requestID, testActor, ttl)
	if err != nil {
		t.Fatalf("approve API key request: %v", err)
	}

	if request.Status != "approved" {
		t.Fatalf("approved request has status %q", request.Status)
	}
	if secret == "" {
		t.Fatal("approval did not return a plaintext API key")
	}

	return request, secret
}

func issuedDirectory(root string) string {
	return filepath.Join(root, "state", "keys", "issued")
}

func TestRequestWaitsForHumanApprovalAndPersistsOnlyHash(t *testing.T) {
	manager, root := newTestKeyManager(t)

	request := requestTestKey(t, manager, []string{"scan:read"})

	if request.DecisionAt != nil ||
		request.DecisionBy != "" ||
		request.IssuedKeyID != "" {
		t.Fatalf("pending request must not contain approval metadata: %#v", request)
	}

	requestPath := filepath.Join(
		root,
		"state",
		"keys",
		"requests",
		request.ID+".json",
	)
	raw, err := os.ReadFile(requestPath)
	if err != nil {
		t.Fatal(err)
	}

	if strings.Contains(string(raw), "api_key") {
		t.Fatal("pending request unexpectedly contains an API key")
	}

	if entries, err := os.ReadDir(issuedDirectory(root)); err != nil {
		t.Fatal(err)
	} else if len(entries) != 0 {
		t.Fatalf("key must not be issued before approval: %v", entries)
	}

	approved, secret := approveTestKey(
		t,
		manager,
		request.ID,
		24*time.Hour,
	)

	if approved.IssuedKeyID == "" {
		t.Fatal("approved request is missing its issued-key ID")
	}
	if approved.DecisionAt == nil || approved.DecisionBy != testActor {
		t.Fatalf("approval metadata missing: %#v", approved)
	}

	if ok, _ := manager.Validate(secret, "scan:read"); !ok {
		t.Fatal("issued key should validate for its granted scope")
	}

	if ok, _ := manager.Validate(secret, "heal:propose"); ok {
		t.Fatal("key must not gain an ungranted scope")
	}

	entries, err := os.ReadDir(issuedDirectory(root))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected one issued-key file; got %d", len(entries))
	}

	savedPath := filepath.Join(issuedDirectory(root), entries[0].Name())
	saved, err := os.ReadFile(savedPath)
	if err != nil {
		t.Fatal(err)
	}

	if strings.Contains(string(saved), secret) {
		t.Fatal("raw API key was persisted")
	}

	var persisted issuedKeyRecord
	if err := json.Unmarshal(saved, &persisted); err != nil {
		t.Fatalf("issued-key record is invalid JSON: %v", err)
	}

	if persisted.KeyHash == "" {
		t.Fatal("issued-key hash was not persisted")
	}
	if persisted.KeyHash != keyHash(secret) {
		t.Fatal("persisted hash does not match the issued secret")
	}
	if persisted.RequestID != request.ID {
		t.Fatalf("issued request ID mismatch: got %q", persisted.RequestID)
	}

	hashBytes, err := hex.DecodeString(persisted.KeyHash)
	if err != nil || len(hashBytes) != 32 {
		t.Fatalf("persisted key hash is not a SHA-256 digest: %q", persisted.KeyHash)
	}

	keyID := strings.TrimSuffix(entries[0].Name(), ".json")
	if keyID != approved.IssuedKeyID {
		t.Fatalf("issued-key ID mismatch: file=%q request=%q", keyID, approved.IssuedKeyID)
	}

	if _, err := manager.Revoke(keyID, testActor); err != nil {
		t.Fatalf("revoke issued key: %v", err)
	}
	if ok, _ := manager.Validate(secret, "scan:read"); ok {
		t.Fatal("revoked key must no longer validate")
	}
}

func TestPrivilegedScopeCannotBeRequested(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	_, err := manager.Request(
		testName,
		testEmail,
		"",
		"Need administrative access to approve production changes",
		[]string{"admin:*"},
	)
	if err == nil {
		t.Fatal("privileged wildcard scope must be rejected")
	}
}

func TestEmptyScopeListDefaultsToReadOnlyAccess(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	request := requestTestKey(t, manager, nil)

	if len(request.Scopes) != 1 || request.Scopes[0] != "scan:read" {
		t.Fatalf("unexpected default scopes: %#v", request.Scopes)
	}

	_, secret := approveTestKey(t, manager, request.ID, time.Hour)

	if ok, _ := manager.Validate(secret, "scan:read"); !ok {
		t.Fatal("default read-only scope should validate")
	}
	if ok, _ := manager.Validate(secret, "heal:propose"); ok {
		t.Fatal("default key must not gain mutation-proposal scopes")
	}
}

func TestRequestedScopesAreDeduplicatedAndSorted(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	request := requestTestKey(
		t,
		manager,
		[]string{"scan:read", "mind:compile", "scan:read"},
	)

	expected := []string{"mind:compile", "scan:read"}
	if len(request.Scopes) != len(expected) {
		t.Fatalf("unexpected scope list: %#v", request.Scopes)
	}

	for i := range expected {
		if request.Scopes[i] != expected[i] {
			t.Fatalf("scopes not normalized: got %#v want %#v", request.Scopes, expected)
		}
	}
}

func TestApprovalCannotIssueSameRequestTwice(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	_, firstSecret := approveTestKey(t, manager, request.ID, time.Hour)

	_, secondSecret, err := manager.Approve(request.ID, testActor, time.Hour)
	if err == nil {
		t.Fatal("already-approved request must not issue a second key")
	}
	if secondSecret != "" {
		t.Fatal("failed approval unexpectedly returned a secret")
	}
	if firstSecret == "" {
		t.Fatal("first approval did not issue a secret")
	}
}

func TestInvalidRequestInputsAreRejected(t *testing.T) {
	tests := []struct {
		name  string
		email string
		repo  string
		reason string
		scopes []string
	}{
		{
			name: "A", email: testEmail, reason: testReason,
			scopes: []string{"scan:read"},
		},
		{
			name: testName, email: "not-an-email", reason: testReason,
			scopes: []string{"scan:read"},
		},
		{
			name: testName, email: "dev example.invalid", reason: testReason,
			scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, repo: "http://github.com/example/project",
			reason: testReason, scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, repo: "https://user:password@example.com/repo",
			reason: testReason, scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, repo: "https://example.com/repo#fragment",
			reason: testReason, scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, reason: "short",
			scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, reason: testReason,
			scopes: []string{"unknown:scope"},
		},
		{
			name: testName, email: testEmail, reason: testReason,
			scopes: []string{"scan:read", "admin:*"},
		},
		{
			name: "Developer\nInjected", email: testEmail, reason: testReason,
			scopes: []string{"scan:read"},
		},
		{
			name: testName, email: testEmail, reason: "Need access\x00to scan",
			scopes: []string{"scan:read"},
		},
	}

	for _, test := range tests {
		t.Run(test.name+"_"+test.email, func(t *testing.T) {
			manager, _ := newTestKeyManager(t)

			_, err := manager.Request(
				test.name,
				test.email,
				test.repo,
				test.reason,
				test.scopes,
			)
			if err == nil {
				t.Fatal("invalid request should have been rejected")
			}
		})
	}
}

func TestRequestScopesCannotExceedAllowedScopeCount(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	_, err := manager.Request(
		testName,
		testEmail,
		"",
		testReason,
		[]string{
			"scan:read",
			"heal:propose",
			"assemble:propose",
			"radar:compare",
			"mind:compile",
			"bridge:propose",
			"admin:*",
		},
	)
	if err == nil {
		t.Fatal("too many or unsupported scopes must be rejected")
	}
}

func TestInvalidResourceIDsAreRejected(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	invalidIDs := []string{
		"",
		".",
		"..",
		"../../other",
		"aaaaaaaaaaaaaaaaaaaaaaa/",
		"AAAAAAAAAAAAAAAAAAAAAAAA",
		"not-a-key-id",
	}

	for _, id := range invalidIDs {
		t.Run("approve_"+strings.ReplaceAll(id, "/", "_"), func(t *testing.T) {
			_, secret, err := manager.Approve(id, testActor, time.Hour)
			if err == nil {
				t.Fatalf("invalid request ID accepted: %q", id)
			}
			if secret != "" {
				t.Fatal("failed approval returned a secret")
			}
		})

		t.Run("revoke_"+strings.ReplaceAll(id, "/", "_"), func(t *testing.T) {
			if _, err := manager.Revoke(id, testActor); err == nil {
				t.Fatalf("invalid issued-key ID accepted: %q", id)
			}
		})
	}
}

func TestApprovalRejectsInvalidActor(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	for _, actor := range []string{"", "  ", "bad\nactor"} {
		_, secret, err := manager.Approve(request.ID, actor, time.Hour)
		if err == nil {
			t.Fatalf("invalid actor %q should be rejected", actor)
		}
		if secret != "" {
			t.Fatal("failed approval unexpectedly returned a secret")
		}
	}

	requests, err := manager.ListRequests("pending_approval")
	if err != nil {
		t.Fatal(err)
	}
	if len(requests) != 1 || requests[0].ID != request.ID {
		t.Fatalf("failed approvals must not approve the request: %#v", requests)
	}
}

func TestKeyLifetimeIsBounded(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	_, secret, err := manager.Approve(request.ID, testActor, maxKeyTTL+time.Second)
	if err == nil {
		t.Fatal("approval exceeding the maximum TTL must fail")
	}
	if secret != "" {
		t.Fatal("failed approval returned a key secret")
	}

	requests, err := manager.ListRequests("pending_approval")
	if err != nil {
		t.Fatal(err)
	}
	if len(requests) != 1 {
		t.Fatalf("failed approval should leave request pending: %#v", requests)
	}
}

func TestNonPositiveTTLUsesDefaultLifetime(t *testing.T) {
	manager, root := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	approved, secret := approveTestKey(t, manager, request.ID, 0)
	if secret == "" {
		t.Fatal("expected issued key")
	}

	record, err := manager.readIssued(
		filepath.Join(issuedDirectory(root), approved.IssuedKeyID+".json"),
	)
	if err != nil {
		t.Fatal(err)
	}

	actualTTL := record.ExpiresAt.Sub(record.CreatedAt)
	if actualTTL != defaultKeyTTL {
		t.Fatalf("default TTL mismatch: got %s want %s", actualTTL, defaultKeyTTL)
	}
}

func TestExpiredKeyCannotValidate(t *testing.T) {
	manager, root := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})
	approved, secret := approveTestKey(t, manager, request.ID, time.Hour)

	path := filepath.Join(issuedDirectory(root), approved.IssuedKeyID+".json")
	key, err := manager.readIssued(path)
	if err != nil {
		t.Fatal(err)
	}

	now := time.Now().UTC()
	key.CreatedAt = now.Add(-2 * time.Hour)
	key.ExpiresAt = now.Add(-time.Hour)

	if err := manager.writeIssued(path, key); err != nil {
		t.Fatal(err)
	}

	if ok, _ := manager.Validate(secret, "scan:read"); ok {
		t.Fatal("expired key must not validate")
	}

	expired, err := manager.ListIssued("expired")
	if err != nil {
		t.Fatal(err)
	}
	if len(expired) != 1 || expired[0].ID != approved.IssuedKeyID {
		t.Fatalf("expired key missing from expiration listing: %#v", expired)
	}
}

func TestIssuedKeyHashIsOmittedFromOrdinaryJSONSerialization(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})
	approved, secret := approveTestKey(t, manager, request.ID, time.Hour)

	keys, err := manager.ListIssued("")
	if err != nil {
		t.Fatal(err)
	}
	if len(keys) != 1 {
		t.Fatalf("expected one issued key, got %d", len(keys))
	}
	if keys[0].ID != approved.IssuedKeyID {
		t.Fatalf("unexpected issued key: %#v", keys[0])
	}

	serialized, err := json.Marshal(keys[0])
	if err != nil {
		t.Fatal(err)
	}

	if strings.Contains(string(serialized), "key_hash") {
		t.Fatal("KeyHash must not be exposed in ordinary IssuedKey serialization")
	}
	if strings.Contains(string(serialized), keyHash(secret)) {
		t.Fatal("serialized IssuedKey must not expose the stored hash value")
	}
	if strings.Contains(string(serialized), secret) {
		t.Fatal("serialized IssuedKey must not expose the plaintext secret")
	}
}

func TestRevokedKeyCannotBeRevokedAgain(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})
	approved, secret := approveTestKey(t, manager, request.ID, time.Hour)

	revoked, err := manager.Revoke(approved.IssuedKeyID, testActor)
	if err != nil {
		t.Fatal(err)
	}
	if revoked.Status != "revoked" || revoked.RevokedAt == nil {
		t.Fatalf("unexpected revocation result: %#v", revoked)
	}

	if _, err := manager.Revoke(approved.IssuedKeyID, testActor); err == nil {
		t.Fatal("second revocation should fail")
	}

	if ok, _ := manager.Validate(secret, "scan:read"); ok {
		t.Fatal("revoked key should not validate")
	}
}

func TestListRequestsReturnsExpectedStatuses(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	first := requestTestKey(t, manager, []string{"scan:read"})
	second := requestTestKey(t, manager, []string{"mind:compile"})
	approveTestKey(t, manager, first.ID, time.Hour)

	pending, err := manager.ListRequests("pending_approval")
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].ID != second.ID {
		t.Fatalf("unexpected pending request list: %#v", pending)
	}

	approved, err := manager.ListRequests("approved")
	if err != nil {
		t.Fatal(err)
	}
	if len(approved) != 1 || approved[0].ID != first.ID {
		t.Fatalf("unexpected approved request list: %#v", approved)
	}

	all, err := manager.ListRequests("")
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 2 {
		t.Fatalf("expected two requests, got %d", len(all))
	}
}

func TestCorruptIssuedRecordCausesValidationToFailClosed(t *testing.T) {
	manager, root := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})
	_, secret := approveTestKey(t, manager, request.ID, time.Hour)

	corruptID := strings.Repeat("a", 24)
	corruptPath := filepath.Join(issuedDirectory(root), corruptID+".json")
	if err := os.WriteFile(corruptPath, []byte("{invalid json"), 0600); err != nil {
		t.Fatal(err)
	}

	if ok, _ := manager.Validate(secret, "scan:read"); ok {
		t.Fatal("key validation must fail closed when the issued-key store is corrupt")
	}
}

func TestListIssuedDoesNotSilentlyIgnoreCorruptRecords(t *testing.T) {
	manager, root := newTestKeyManager(t)
	requestTestKey(t, manager, []string{"scan:read"})

	corruptPath := filepath.Join(
		issuedDirectory(root),
		strings.Repeat("b", 24)+".json",
	)
	if err := os.WriteFile(corruptPath, []byte("{invalid json"), 0600); err != nil {
		t.Fatal(err)
	}

	if _, err := manager.ListIssued(""); err == nil {
		t.Fatal("issued-key listing should report corrupt key metadata")
	}
}

func TestRequestListingDoesNotSilentlyIgnoreCorruptRecords(t *testing.T) {
	manager, root := newTestKeyManager(t)

	corruptPath := filepath.Join(
		root,
		"state",
		"keys",
		"requests",
		strings.Repeat("c", 24)+".json",
	)
	if err := os.MkdirAll(filepath.Dir(corruptPath), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(corruptPath, []byte("{invalid json"), 0600); err != nil {
		t.Fatal(err)
	}

	if _, err := manager.ListRequests(""); err == nil {
		t.Fatal("request listing should report corrupt request metadata")
	}
}

func TestSymlinkedIssuedRecordIsRejected(t *testing.T) {
	manager, root := newTestKeyManager(t)

	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}

	link := filepath.Join(issuedDirectory(root), strings.Repeat("d", 24)+".json")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink creation unavailable: %v", err)
	}

	if _, err := manager.ListIssued(""); err == nil {
		t.Fatal("symlinked key record should be rejected")
	}
}

func TestCorruptRequestCannotBeApproved(t *testing.T) {
	manager, root := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	requestPath := filepath.Join(
		root,
		"state",
		"keys",
		"requests",
		request.ID+".json",
	)
	if err := os.WriteFile(requestPath, []byte("{not valid"), 0600); err != nil {
		t.Fatal(err)
	}

	_, secret, err := manager.Approve(request.ID, testActor, time.Hour)
	if err == nil {
		t.Fatal("corrupt request must not be approved")
	}
	if secret != "" {
		t.Fatal("failed approval unexpectedly returned a secret")
	}

	entries, err := os.ReadDir(issuedDirectory(root))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("failed approval unexpectedly created issued keys: %v", entries)
	}
}

func TestMalformedSecretFailsClosed(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	secrets := []string{
		"",
		"not-a-key",
		"uz0_short",
		"uz0_" + strings.Repeat("!", 43),
		"uz0_" + strings.Repeat("A", 43),
	}

	for _, secret := range secrets {
		t.Run(secret, func(t *testing.T) {
			if ok, _ := manager.Validate(secret, "scan:read"); ok {
				t.Fatal("malformed secret must not validate")
			}
		})
	}

	if ok, _ := manager.Validate("uz0_"+strings.Repeat("A", 43), "admin:*"); ok {
		t.Fatal("unrecognized scope must not validate")
	}
}

func TestUnsupportedStatusFiltersAreRejected(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	if _, err := manager.ListRequests("active"); err == nil {
		t.Fatal("invalid request status filter should fail")
	}
	if _, err := manager.ListIssued("pending_approval"); err == nil {
		t.Fatal("invalid issued-key status filter should fail")
	}
}

func TestNilOrUnconfiguredManagerFailsClosed(t *testing.T) {
	var manager *KeyManager

	if _, err := manager.Request(
		testName,
		testEmail,
		"",
		testReason,
		[]string{"scan:read"},
	); err == nil {
		t.Fatal("nil manager should reject requests")
	}

	if ok, id := manager.Validate("uz0_"+strings.Repeat("A", 43), "scan:read"); ok || id != "" {
		t.Fatal("nil manager must not validate keys")
	}

	unconfigured := New("")
	if _, err := unconfigured.ListIssued(""); err == nil {
		t.Fatal("unconfigured manager should fail listing")
	}
}

func TestIssuedKeyMetadataAndScopesAreCopied(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})
	_, secret := approveTestKey(t, manager, request.ID, time.Hour)

	request.Scopes[0] = "admin:*"
	if ok, _ := manager.Validate(secret, "scan:read"); !ok {
		t.Fatal("modifying returned request scopes must not mutate persisted authorization")
	}

	keys, err := manager.ListIssued("")
	if err != nil {
		t.Fatal(err)
	}
	if len(keys) != 1 {
		t.Fatalf("expected one issued key, got %d", len(keys))
	}

	keys[0].Scopes[0] = "admin:*"
	keys[0].Status = "revoked"

	if ok, _ := manager.Validate(secret, "scan:read"); !ok {
		t.Fatal("modifying returned key metadata must not mutate persisted state")
	}
	if ok, _ := manager.Validate(secret, "admin:*"); ok {
		t.Fatal("caller-side mutation must not grant an unissued scope")
	}
}

func TestApprovalWithExcessiveTTLDoesNotChangeRequestStatus(t *testing.T) {
	manager, _ := newTestKeyManager(t)
	request := requestTestKey(t, manager, []string{"scan:read"})

	_, _, err := manager.Approve(
		request.ID,
		testActor,
		maxKeyTTL+time.Hour,
	)
	if err == nil {
		t.Fatal("excessive TTL should be rejected")
	}

	pending, err := manager.ListRequests("pending_approval")
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].ID != request.ID {
		t.Fatalf("failed approval changed request status: %#v", pending)
	}
}

func TestApproveMissingRequestReturnsError(t *testing.T) {
	manager, _ := newTestKeyManager(t)

	_, secret, err := manager.Approve(
		strings.Repeat("e", 24),
		testActor,
		time.Hour,
	)
	if err == nil {
		t.Fatal("approval of a missing request should fail")
	}
	if secret != "" {
		t.Fatal("missing request unexpectedly returned a secret")
	}

	var pathError *os.PathError
	if errors.As(err, &pathError) {
		// The underlying filesystem error is allowed to be wrapped.
		return
	}
}
