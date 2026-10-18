package diagnostics

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"usect-zero.local/core-zero/internal/kernel"
)

func writeFile(t *testing.T, path, body string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestRunReportsBaselineDriftWithoutRewritingFiles(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "changed.txt"), "before")
	writeFile(t, filepath.Join(root, "missing.txt"), "remove me")

	k, err := kernel.New(root)
	if err != nil {
		t.Fatal(err)
	}
	scan, err := k.Scan()
	if err != nil {
		t.Fatal(err)
	}

	baseline := kernel.Baseline{
		SchemaVersion: "usect-zero.baseline.v1",
		CreatedAt: time.Now().UTC(),
		GitHead: "test-baseline-head",
		Files: scan.Files,
		ManifestSHA256: scan.ManifestSHA256,
	}
	raw, err := json.Marshal(baseline)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(k.CoreRoot, "state", "baseline.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}

	writeFile(t, filepath.Join(root, "changed.txt"), "after")
	writeFile(t, filepath.Join(root, "added.txt"), "new file")
	if err := os.Remove(filepath.Join(root, "missing.txt")); err != nil {
		t.Fatal(err)
	}

	report, err := Run(k)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "ready" {
		t.Fatalf("unexpected operational status: %q warnings=%v", report.Status, report.Warnings)
	}
	if report.Baseline.Status != "compared" {
		t.Fatalf("baseline was not compared: %+v", report.Baseline)
	}
	if report.Baseline.AddedCount != 1 || report.Baseline.ModifiedCount != 1 || report.Baseline.MissingCount != 1 {
		t.Fatalf("incorrect drift counts: %+v", report.Baseline)
	}
	if len(report.Baseline.AddedPaths) != 1 || report.Baseline.AddedPaths[0] != "added.txt" {
		t.Fatalf("incorrect added-path sample: %v", report.Baseline.AddedPaths)
	}
	if got, err := os.ReadFile(filepath.Join(root, "changed.txt")); err != nil || string(got) != "after" {
		t.Fatalf("diagnostics modified the working file: %q, %v", got, err)
	}
	encoded, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), root) {
		t.Fatal("diagnostics report must not expose the absolute repository root")
	}
	for _, check := range report.Storage {
		if check.Status != "ok" {
			t.Fatalf("storage probe failed for %s: %+v", check.Name, check)
		}
	}
}

func TestRunWithoutBaselineWarnsButDoesNotFailOperationalCheck(t *testing.T) {
	k, err := kernel.New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	report, err := Run(k)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "ready" || report.Baseline.Status != "not_recorded" {
		t.Fatalf("expected ready core with baseline warning: %+v", report)
	}
	if len(report.Warnings) == 0 {
		t.Fatal("expected a warning explaining that no baseline is recorded")
	}
}
