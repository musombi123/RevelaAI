package simulate

import "testing"

func TestKnownScenariosAreExplicitlySynthetic(t *testing.T) {
	for _, name := range []string{"auth-failure-burst", "startup-entry", "vpn-observation"} {
		report, err := Run(name)
		if err != nil { t.Fatal(err) }
		if !report.Simulated || !report.Finding.Simulated { t.Fatalf("%s was not marked synthetic", name) }
		if report.Finding.Scope != "lab" { t.Fatalf("%s escaped lab scope", name) }
		if len(report.Detections) == 0 || !report.Detections[0].Triggered { t.Fatalf("%s did not trigger its expected detector", name) }
	}
}

func TestUnknownScenarioIsRejected(t *testing.T) {
	if _, err := Run("arbitrary-shell-command"); err == nil { t.Fatal("unknown scenario should be rejected") }
}
