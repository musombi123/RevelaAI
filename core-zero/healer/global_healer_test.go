package healer

import (
	"os"
	"path/filepath"
	"testing"
)

const healerTestDBSchema = "usect-zero.worldwide-failure-db.v1"

func TestGlobalHealerAcrossCountries(t *testing.T) {
	root := filepath.Join("..", "..")

	cases := []struct {
		country  string
		language string
	}{
		{"US", "en"},
		{"DE", "de"},
		{"CN", "zh"},
		{"KE", "sw"},
	}

	for _, tc := range cases {
		tc := tc

		t.Run(tc.country, func(t *testing.T) {
			got, err := Classify(
				"x509: certificate signed by unknown authority",
				tc.country,
				tc.language,
				root,
			)
			if err != nil {
				t.Fatalf("Classify returned an error: %v", err)
			}

			if !got.Matched {
				t.Fatalf("expected a curated pattern match: %+v", got)
			}
			if got.PatternID != "certificate_validation" {
				t.Fatalf(
					"expected pattern certificate_validation, got %q",
					got.PatternID,
				)
			}
			if got.AutomaticRepair {
				t.Fatal("classification must never authorize automatic repair")
			}
			if !got.GuardianRequired {
				t.Fatal("guardian approval must always be required")
			}
			if got.Recommendation == "" {
				t.Fatal("matched pattern must provide a recommendation")
			}
			if got.DatabaseStatus != "loaded_curated_advisory" {
				t.Fatalf(
					"unexpected database status: %q",
					got.DatabaseStatus,
				)
			}
		})
	}
}

func TestGlobalHealerFailsClosedWithoutDatabase(t *testing.T) {
	root := t.TempDir()

	if _, err := Classify("disk full", "DE", "de", root); err == nil {
		t.Fatal("missing database must fail closed")
	}
}

func TestGlobalHealerFailsClosedWithMalformedDatabase(t *testing.T) {
	root := t.TempDir()
	writeHealerTestDB(t, root, []byte(`{"schema":`))

	if _, err := Classify(
		"disk full",
		"DE",
		"de",
		root,
	); err == nil {
		t.Fatal("malformed database must fail closed")
	}
}

func TestGlobalHealerFailsClosedWithUnsupportedSchema(t *testing.T) {
	root := t.TempDir()

	writeHealerTestDB(t, root, []byte(`{
		"schema": "unknown.failure-db.v99",
		"patterns": [{
			"id": "disk_full",
			"category": "storage",
			"match_any": ["disk full"],
			"recommendation": "Inspect available disk space.",
			"risk": "low"
		}]
	}`))

	if _, err := Classify("disk full", "DE", "de", root); err == nil {
		t.Fatal("unsupported schema must fail closed")
	}
}

func TestGlobalHealerRejectsDuplicatePatternIDs(t *testing.T) {
	root := t.TempDir()

	writeHealerTestDB(t, root, []byte(`{
		"schema": "usect-zero.worldwide-failure-db.v1",
		"patterns": [
			{
				"id": "duplicate_id",
				"category": "storage",
				"match_any": ["disk full"],
				"recommendation": "Inspect storage.",
				"risk": "low"
			},
			{
				"id": "duplicate_id",
				"category": "network",
				"match_any": ["connection refused"],
				"recommendation": "Inspect connectivity.",
				"risk": "low"
			}
		]
	}`))

	if _, err := Classify("disk full", "DE", "de", root); err == nil {
		t.Fatal("duplicate pattern IDs must cause database validation to fail")
	}
}

func TestGlobalHealerPrefersLongestMatchingPhrase(t *testing.T) {
	root := t.TempDir()

	// The generic pattern deliberately appears first. Classification should
	// select the longer phrase, not simply the first matching pattern.
	writeHealerTestDB(t, root, []byte(`{
		"schema": "usect-zero.worldwide-failure-db.v1",
		"status": "curated_advisory_patterns_not_exhaustive",
		"patterns": [
			{
				"id": "generic_certificate",
				"category": "security",
				"match_any": ["certificate"],
				"recommendation": "Inspect certificate validation details.",
				"risk": "medium"
			},
			{
				"id": "certificate_validation",
				"category": "security",
				"match_any": [
					"x509: certificate signed by unknown authority"
				],
				"recommendation": "Verify the certificate chain and trusted issuer.",
				"risk": "medium"
			}
		]
	}`))

	got, err := Classify(
		"x509: certificate signed by unknown authority",
		"US",
		"en",
		root,
	)
	if err != nil {
		t.Fatalf("Classify returned an error: %v", err)
	}

	if !got.Matched {
		t.Fatalf("expected a pattern match: %+v", got)
	}
	if got.PatternID != "certificate_validation" {
		t.Fatalf(
			"expected the most specific pattern, got %q",
			got.PatternID,
		)
	}
	if got.AutomaticRepair {
		t.Fatal("classification must not automatically repair")
	}
	if !got.GuardianRequired {
		t.Fatal("guardian approval must be required")
	}
}

func TestGlobalHealerNoMatchRemainsAdvisoryOnly(t *testing.T) {
	root := t.TempDir()

	writeHealerTestDB(t, root, []byte(`{
		"schema": "usect-zero.worldwide-failure-db.v1",
		"patterns": [{
			"id": "disk_full",
			"category": "storage",
			"match_any": ["disk full"],
			"recommendation": "Inspect available disk space.",
			"risk": "low"
		}]
	}`))

	got, err := Classify(
		"an unrecognized diagnostic",
		"KE",
		"sw",
		root,
	)
	if err != nil {
		t.Fatalf("Classify returned an error: %v", err)
	}

	if got.Matched {
		t.Fatalf("unexpected match for unknown diagnostic: %+v", got)
	}
	if got.AutomaticRepair {
		t.Fatal("automatic repair must remain disabled")
	}
	if !got.GuardianRequired {
		t.Fatal("guardian approval must remain required")
	}
	if got.Recommendation == "" {
		t.Fatal("no-match result must provide a safe fallback recommendation")
	}
	if got.DatabaseStatus != "loaded_curated_advisory" {
		t.Fatalf("unexpected database status: %q", got.DatabaseStatus)
	}
}

func TestGlobalHealerRejectsInvalidCountryBeforeClassification(t *testing.T) {
	_, err := Classify(
		"disk full",
		"INVALID",
		"en",
		t.TempDir(),
	)
	if err == nil {
		t.Fatal("invalid country context must return an error")
	}
}

func TestGlobalHealerRejectsEmptyDiagnostic(t *testing.T) {
	root := t.TempDir()

	writeHealerTestDB(t, root, []byte(`{
		"schema": "usect-zero.worldwide-failure-db.v1",
		"patterns": [{
			"id": "disk_full",
			"category": "storage",
			"match_any": ["disk full"],
			"recommendation": "Inspect available disk space.",
			"risk": "low"
		}]
	}`))

	if _, err := Classify("", "US", "en", root); err == nil {
		t.Fatal("empty diagnostic must be rejected")
	}

	if _, err := Classify("   ", "US", "en", root); err == nil {
		t.Fatal("whitespace-only diagnostic must be rejected")
	}
}

func TestGlobalHealerRejectsOversizedDiagnostic(t *testing.T) {
	root := t.TempDir()

	writeHealerTestDB(t, root, []byte(`{
		"schema": "usect-zero.worldwide-failure-db.v1",
		"patterns": [{
			"id": "disk_full",
			"category": "storage",
			"match_any": ["disk full"],
			"recommendation": "Inspect available disk space.",
			"risk": "low"
		}]
	}`))

	// The implementation's diagnostic limit is 8192 bytes.
	oversized := make([]byte, 8193)
	for i := range oversized {
		oversized[i] = 'x'
	}

	if _, err := Classify(string(oversized), "US", "en", root); err == nil {
		t.Fatal("diagnostic exceeding 8192 bytes must be rejected")
	}
}

func writeHealerTestDB(t *testing.T, root string, contents []byte) {
	t.Helper()

	dbDir := filepath.Join(
		root,
		"core-zero",
		"knowledge",
		"worldwide_failure_db",
	)

	if err := os.MkdirAll(dbDir, 0700); err != nil {
		t.Fatalf("create test database directory: %v", err)
	}

	dbPath := filepath.Join(dbDir, "patterns.json")

	if err := os.WriteFile(dbPath, contents, 0600); err != nil {
		t.Fatalf("write test database: %v", err)
	}
}
