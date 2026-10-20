package genesis

import (
	"strings"
	"testing"
)

func TestRuntimeInvocationUsesPublishedTreeButExcludesTests(t *testing.T) {
	for _, required := range []string{
		"cp -R /candidate/. /tmp/work/toolimpl/",
		"rm -f /tmp/work/toolimpl/test.go /tmp/work/toolimpl/*_test.go",
		"GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off",
		"toolimpl.Tool{}",
		"toolimpl.Request{Action: in.Action, Inputs: in.Inputs, Consent: in.Consent}",
	} {
		if !strings.Contains(goToolInvocationScript, required) {
			t.Errorf("runtime launcher is missing required contract %q", required)
		}
	}
	if strings.Contains(goToolInvocationScript, "cp /candidate/code.go /candidate/library.go") {
		t.Fatal("runtime launcher must preserve the complete tested artifact tree")
	}
}


func TestToolInvocationOutputMustBeBoundedJSONObject(t *testing.T) {
	for _, valid := range [][]byte{
		[]byte(`{"status":"proposal_only","tool":"safe_tool","summary":"done"}`),
		[]byte(`{"status":"proposal_only","tool":"safe_tool","summary":"done","created_at":"2026-10-20T00:00:00Z","evidence":["evidence.json"]}`),
	} {
		if err := validateToolInvocationOutput(valid); err != nil {
			t.Errorf("valid runtime result should pass: %v", err)
		}
	}
	for _, invalid := range [][]byte{
		nil,
		[]byte("null"),
		[]byte("[]"),
		[]byte("{}"),
		[]byte(`{"incomplete":`),
		[]byte(`{"status":"proposal_only","tool":"safe_tool","summary":"done","extra":true}`),
		[]byte(`{"status":1,"tool":"safe_tool","summary":"done"}`),
		[]byte(`{"status":"proposal_only","tool":"safe_tool","summary":"done","evidence":[1]}`),
	} {
		if err := validateToolInvocationOutput(invalid); err == nil {
			t.Errorf("invalid/non-object tool result should be rejected: %q", invalid)
		}
	}
	if err := validateToolInvocationOutput(make([]byte, maxToolInvocationBytes+1)); err == nil {
		t.Fatal("oversized tool result must be rejected")
	}
	if err := validateToolInvocationOutputForName([]byte(`{"status":"proposal_only","tool":"other_tool","summary":"done"}`), "safe_tool"); err == nil {
		t.Fatal("tool result must identify the signed tool being invoked")
	}
	if err := validateToolInvocationOutputForName([]byte(`{"status":"proposal_only","tool":"safe_tool","summary":"done"}`), "safe_tool"); err != nil {
		t.Fatalf("matching signed tool identity should pass: %v", err)
	}
}
