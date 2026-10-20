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
