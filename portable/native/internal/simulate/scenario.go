// Package simulate runs inert, synthetic detection exercises. It does not
// create OS persistence, execute payloads, authenticate to services, or scan
// networks. Every emitted event is marked as simulated.
package simulate

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/musombi123/revela-field-engine/internal/contract"
)

type Event struct {
	Type      string    `json:"type"`
	Count     int       `json:"count,omitempty"`
	WindowSec int       `json:"window_seconds,omitempty"`
	Location  string    `json:"fixture_location,omitempty"`
	At        time.Time `json:"at"`
}

type Detection struct {
	RuleID    string `json:"rule_id"`
	Triggered bool   `json:"triggered"`
	Reason    string `json:"reason"`
}

type Report struct {
	SchemaVersion string             `json:"schema_version"`
	Scenario      string             `json:"scenario"`
	Mode          string             `json:"mode"`
	Simulated     bool               `json:"simulated"`
	Events        []Event            `json:"events"`
	Detections    []Detection        `json:"detections"`
	Finding       contract.Finding   `json:"finding"`
	Safety        string             `json:"safety"`
}

func Run(name string) (Report, error) {
	now := time.Now().UTC()
	report := Report{
		SchemaVersion: contract.SchemaVersion,
		Scenario: name,
		Mode: "synthetic_detection_validation",
		Simulated: true,
		Events: []Event{},
		Detections: []Detection{},
		Safety: "Synthetic telemetry only. No host settings, accounts, processes, files, credentials, or network targets were modified or contacted.",
	}
	var category, title, summary, recommendation, tactic, technique string
	var raw string

	switch name {
	case "auth-failure-burst":
		category, title = "identity_monitoring", "Synthetic authentication-failure burst"
		summary = "A synthetic fixture represents repeated failed authentication events inside a short time window."
		recommendation = "Validate rate limiting, alert thresholds, multifactor authentication and account lockout policy using approved identity-provider telemetry."
		tactic, technique = "Credential Access", "Brute Force"
		raw = "failed-auth:12:60"
		report.Events = append(report.Events, Event{Type:"authentication_failed", Count:12, WindowSec:60, At:now})
		report.Detections = append(report.Detections, Detection{RuleID:"identity.failed_auth_burst", Triggered:true, Reason:"12 synthetic failures in a 60-second fixture window"})
	case "startup-entry":
		category, title = "persistence_monitoring", "Synthetic startup-entry change"
		summary = "A synthetic manifest represents an unexpected startup entry; no registry, launch agent, service or startup folder was changed."
		recommendation = "Review authorised software inventory, startup-item provenance and endpoint detection coverage. Investigate the real host only with explicit scope."
		tactic, technique = "Persistence", "Boot or Logon Autostart Execution"
		raw = "startup-entry:fixture:untrusted"
		report.Events = append(report.Events, Event{Type:"startup_entry_added", Count:1, Location:"isolated-fixture/autorun.json", At:now})
		report.Detections = append(report.Detections, Detection{RuleID:"host.unapproved_startup_entry", Triggered:true, Reason:"synthetic startup manifest is not in the fixture allowlist"})
	case "vpn-observation":
		category, title = "network_visibility", "Synthetic VPN tunnel visibility check"
		summary = "A synthetic tunnel-interface observation is used to test whether reporting distinguishes a VPN from malicious activity."
		recommendation = "Document permitted VPN routes and DNS behaviour. Do not bypass the tunnel or infer a person's identity from VPN use."
		tactic, technique = "Network Visibility", "Tunnel interface observation"
		raw = "vpn-interface:fixture:tun0"
		report.Events = append(report.Events, Event{Type:"tunnel_interface_observed", Count:1, Location:"synthetic/tun0", At:now})
		report.Detections = append(report.Detections, Detection{RuleID:"network.tunnel_visibility", Triggered:true, Reason:"synthetic tunnel indicator observed; this is not a maliciousness verdict"})
	default:
		return Report{}, fmt.Errorf("unknown scenario %q (choose auth-failure-burst, startup-entry, or vpn-observation)", name)
	}

	sum := sha256.Sum256([]byte(name + "|" + raw + "|" + now.Format(time.RFC3339Nano)))
	report.Finding = contract.Finding{
		SchemaVersion: contract.SchemaVersion,
		ID: "field-" + hex.EncodeToString(sum[:8]),
		Source: "revela-field-engine",
		ObservedAt: now,
		Target: "isolated synthetic fixture",
		Category: category,
		Severity: "informational",
		Title: title,
		Summary: summary,
		Evidence: []contract.Evidence{{Kind:"synthetic_event", Ref:"scenario://" + name, Note:"Synthetic evidence only; not observed on a real host."}},
		Recommendation: recommendation,
		Scope: "lab",
		Simulated: true,
		Techniques: []contract.Technique{{Framework:"MITRE ATT&CK Enterprise v20.0", Name:technique, Tactic:tactic}},
	}
	return report, nil
}
