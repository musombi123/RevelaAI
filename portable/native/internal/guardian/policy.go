// Package guardian is the local, fail-closed policy gate for Field Engine
// operations. It deliberately has no "bypass Guardian" or override method.
package guardian

import "strings"

type Request struct {
	Action     string
	Scope      string
	Authorized bool
}

type Decision struct {
	Allowed bool   `json:"allowed"`
	Decision string `json:"decision"`
	Reason   string `json:"reason"`
	Action   string `json:"action"`
	Scope    string `json:"scope"`
}

var prohibited = map[string]struct{}{
	"remote_exploitation": {},
	"vpn_bypass":          {},
	"credential_dump":     {},
	"stealth_evasion":     {},
	"disable_defenses":    {},
	"delete_evidence":     {},
	"execute_payload":     {},
	"external_network_scan": {},
}

var allowedScopes = map[string]map[string]struct{}{
	"system_inventory":          {"local": {}},
	"network_metadata":          {"local": {}},
	"file_inventory":            {"local": {}},
	"safe_vulnerability_check":  {"local": {}, "lab": {}},
	"adversary_emulation":       {"lab": {}},
	"remediation_plan":          {"local": {}, "lab": {}},
	"repair_verification":       {"local": {}, "lab": {}},
	"core_health_probe":         {"local": {}},
	"start_local_core_services": {"local": {}},
	"meta_engineer_sync":       {"local": {}, "remote": {}},
}

func Evaluate(req Request) Decision {
	action := strings.ToLower(strings.TrimSpace(req.Action))
	scope := strings.ToLower(strings.TrimSpace(req.Scope))
	decision := Decision{Decision: "deny", Reason: "unknown action; policy is fail-closed", Action: action, Scope: scope}

	if action == "" || scope == "" {
		decision.Reason = "action and scope are required"
		return decision
	}
	if _, blocked := prohibited[action]; blocked {
		decision.Reason = "action is prohibited by Guardian policy"
		return decision
	}
	scopes, known := allowedScopes[action]
	if !known {
		return decision
	}
	if !req.Authorized {
		decision.Reason = "explicit operator authorization is required"
		return decision
	}
	if _, ok := scopes[scope]; !ok {
		decision.Reason = "action is not permitted in the requested scope"
		return decision
	}

	decision.Allowed = true
	decision.Decision = "allow"
	decision.Reason = "known defensive action; scope and explicit authorization checks passed"
	return decision
}
