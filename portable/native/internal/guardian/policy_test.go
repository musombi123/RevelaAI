package guardian

import "testing"

func TestAllowsReadOnlyLocalInventoryWithExplicitAuthorization(t *testing.T) {
	got := Evaluate(Request{Action: "file_inventory", Scope: "local", Authorized: true})
	if !got.Allowed || got.Decision != "allow" {
		t.Fatalf("expected allow, got %+v", got)
	}
}

func TestDeniesMissingAuthorization(t *testing.T) {
	got := Evaluate(Request{Action: "file_inventory", Scope: "local"})
	if got.Allowed || got.Decision != "deny" {
		t.Fatalf("expected deny, got %+v", got)
	}
}

func TestAdversaryEmulationIsLabOnly(t *testing.T) {
	if got := Evaluate(Request{Action: "adversary_emulation", Scope: "local", Authorized: true}); got.Allowed {
		t.Fatalf("local adversary emulation must be denied: %+v", got)
	}
	if got := Evaluate(Request{Action: "adversary_emulation", Scope: "lab", Authorized: true}); !got.Allowed {
		t.Fatalf("lab simulation should be allowed: %+v", got)
	}
}

func TestGuardianDoesNotPermitControlBypass(t *testing.T) {
	for _, action := range []string{"vpn_bypass", "remote_exploitation", "credential_dump", "disable_defenses", "delete_evidence", "execute_payload"} {
		got := Evaluate(Request{Action: action, Scope: "lab", Authorized: true})
		if got.Allowed {
			t.Errorf("prohibited action %q was allowed", action)
		}
	}
}

func TestUnknownActionFailsClosed(t *testing.T) {
	got := Evaluate(Request{Action: "run-anything", Scope: "lab", Authorized: true})
	if got.Allowed {
		t.Fatalf("unknown action must fail closed: %+v", got)
	}
}
