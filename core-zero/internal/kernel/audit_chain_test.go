package kernel

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAuditHashChainDetectsTampering(t *testing.T) {
	root := t.TempDir()
	k, err := New(root)
	if err != nil {
		t.Fatal(err)
	}
	if err := k.Audit("test_one", "test", "subject", "ok", map[string]any{"n": 1}); err != nil {
		t.Fatal(err)
	}
	if err := k.Audit("test_two", "test", "subject", "ok", nil); err != nil {
		t.Fatal(err)
	}
	report, err := k.VerifyAudit()
	if err != nil {
		t.Fatal(err)
	}
	if !report.Verified || !report.ChainValid || report.Entries != 2 {
		t.Fatalf("unexpected verification report: %+v", report)
	}

	path := filepath.Join(k.CoreRoot, "audit_log", "events.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for i := range data {
		if data[i] == 'o' {
			data[i] = 'x'
			break
		}
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	report, err = k.VerifyAudit()
	if err != nil {
		t.Fatal(err)
	}
	if report.ChainValid || report.Verified {
		t.Fatalf("tampered log was accepted: %+v", report)
	}
	if err := k.Audit("after_tamper", "test", "subject", "ok", nil); err == nil {
		t.Fatal("expected append to fail closed after tampering")
	}
}

func TestAuditLegacyPrefixIsNotClaimedVerified(t *testing.T) {
	root := t.TempDir()
	k, err := New(root)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(k.CoreRoot, "audit_log", "events.jsonl")
	if err := os.WriteFile(path, []byte("{\"at\":\"2026-01-01T00:00:00Z\",\"action\":\"legacy\",\"actor\":\"test\",\"outcome\":\"ok\"}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := k.Audit("new_event", "test", "subject", "ok", nil); err != nil {
		t.Fatal(err)
	}
	report, err := k.VerifyAudit()
	if err != nil {
		t.Fatal(err)
	}
	if !report.ChainValid || report.Verified || report.LegacyEntries != 1 {
		t.Fatalf("legacy prefix was misreported: %+v", report)
	}
}


func TestAuditVerifierRejectsIncompleteTrailingRecord(t *testing.T) {
	report := verifyAuditBytes([]byte(`{"action":"incomplete"}`))
	if report.ChainValid || report.Verified || report.Status != "invalid" {
		t.Fatalf("incomplete audit record was accepted: %+v", report)
	}
}
