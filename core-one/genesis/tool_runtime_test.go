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
		[]byte(`{"status":"proposal_only","summary":"done"}`),
		[]byte("{}"),
	} {
		if err := validateToolInvocationOutput(valid); err != nil {
			t.Errorf("valid JSON object should pass: %v", err)
		}
	}
	for _, invalid := range [][]byte{
		nil,
		[]byte("null"),
		[]byte("[]"),
		[]byte(`{"incomplete":`),
	} {
		if err := validateToolInvocationOutput(invalid); err == nil {
			t.Errorf("invalid/non-object tool result should be rejected: %q", invalid)
		}
	}
	if err := validateToolInvocationOutput(make([]byte, maxToolInvocationBytes+1)); err == nil {
		t.Fatal("oversized tool result must be rejected")
	}
}
