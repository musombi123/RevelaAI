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

func writeDiagnosticTestFile(t *testing.T, path, body string) {
	t.Helper()

	if err := os.WriteFile(path, []byte(body), 0600); err != nil {
		t.Fatalf("write test file %q: %v", path, err)
	}
}

func newDiagnosticsTestKernel(t *testing.T) (*kernel.Kernel, string) {
	t.Helper()

	t.Setenv("USECT_ZERO_DATA_DIR", "")

	root := t.TempDir()
	k, err := kernel.New(root)
	if err != nil {
		t.Fatalf("initialize kernel: %v", err)
	}

	return k, root
}

func createDiagnosticsTestBaseline(t *testing.T, k *kernel.Kernel) kernel.Baseline {
	t.Helper()

	scan, err := k.Scan()
	if err != nil {
		t.Fatalf("scan repository for baseline fixture: %v", err)
	}

	baseline := kernel.Baseline{
		SchemaVersion:  "usect-zero.baseline.v1",
		CreatedAt:      time.Now().UTC(),
		GitHead:        "test-baseline-head",
		Files:          scan.Files,
		ManifestSHA256: scan.ManifestSHA256,
	}

	return baseline
}

func saveDiagnosticsTestBaseline(t *testing.T, k *kernel.Kernel, baseline kernel.Baseline) {
	t.Helper()

	raw, err := json.Marshal(baseline)
	if err != nil {
		t.Fatalf("serialize baseline fixture: %v", err)
	}

	path := filepath.Join(k.CoreRoot, "state", "baseline.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatalf("persist baseline fixture: %v", err)
	}
}

func TestRunReportsBaselineDriftWithoutRewritingFiles(t *testing.T) {
	k, root := newDiagnosticsTestKernel(t)

	changedPath := filepath.Join(root, "changed.txt")
	missingPath := filepath.Join(root, "missing.txt")

	writeDiagnosticTestFile(t, changedPath, "before")
	writeDiagnosticTestFile(t, missingPath, "remove me")

	baseline := createDiagnosticsTestBaseline(t, k)
	saveDiagnosticsTestBaseline(t, k, baseline)

	writeDiagnosticTestFile(t, changedPath, "after")
	writeDiagnosticTestFile(t, filepath.Join(root, "added.txt"), "new file")

	if err := os.Remove(missingPath); err != nil {
		t.Fatal(err)
	}

	report, err := Run(k)
	if err != nil {
		t.Fatalf("diagnostics failed: %v", err)
	}

	if report.SchemaVersion != "usect-zero.diagnostics.v1" {
		t.Fatalf("unexpected schema version: %q", report.SchemaVersion)
	}

	if report.Status != "ready" {
		t.Fatalf("unexpected operational status: %q warnings=%v", report.Status, report.Warnings)
	}

	if report.Baseline.Status != "compared" {
		t.Fatalf("baseline was not compared: %+v", report.Baseline)
	}

	if report.Baseline.AddedCount != 1 ||
		report.Baseline.ModifiedCount != 1 ||
		report.Baseline.MissingCount != 1 {
		t.Fatalf("incorrect drift counts: %+v", report.Baseline)
	}

	if report.Baseline.ExpectedFileCount != len(baseline.Files) {
		t.Fatalf(
			"unexpected expected-file count: got %d want %d",
			report.Baseline.ExpectedFileCount,
			len(baseline.Files),
		)
	}

	if len(report.Baseline.AddedPaths) != 1 ||
		report.Baseline.AddedPaths[0] != "added.txt" {
		t.Fatalf("incorrect added-path sample: %v", report.Baseline.AddedPaths)
	}

	if len(report.Baseline.ModifiedPaths) != 1 ||
		report.Baseline.ModifiedPaths[0] != "changed.txt" {
		t.Fatalf("incorrect modified-path sample: %v", report.Baseline.ModifiedPaths)
	}

	if len(report.Baseline.MissingPaths) != 1 ||
		report.Baseline.MissingPaths[0] != "missing.txt" {
		t.Fatalf("incorrect missing-path sample: %v", report.Baseline.MissingPaths)
	}

	if report.Baseline.SamplesTruncated {
		t.Fatal("small drift result must not be marked as truncated")
	}

	content, err := os.ReadFile(changedPath)
	if err != nil || string(content) != "after" {
		t.Fatalf("diagnostics modified the working file: %q, %v", content, err)
	}

	if _, err := os.Stat(missingPath); !os.IsNotExist(err) {
		t.Fatalf("diagnostics unexpectedly restored the removed file: %v", err)
	}

	encoded, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}

	if strings.Contains(string(encoded), root) {
		t.Fatal("diagnostics report exposed the absolute repository root")
	}

	for _, check := range report.Storage {
		if check.Status != "ok" {
			t.Fatalf("storage probe failed for %s: %+v", check.Name, check)
		}
	}
}

func TestRunWithoutBaselineWarnsButDoesNotFailOperationalCheck(t *testing.T) {
	k, _ := newDiagnosticsTestKernel(t)

	report, err := Run(k)
	if err != nil {
		t.Fatalf("diagnostics should succeed without a baseline: %v", err)
	}

	if report.Status != "ready" ||
		report.Baseline.Status != "not_recorded" {
		t.Fatalf("expected ready system with baseline warning: %+v", report)
	}

	if len(report.Warnings) == 0 {
		t.Fatal("expected a warning explaining that no baseline is recorded")
	}

	if len(report.Baseline.AddedPaths) != 0 ||
		len(report.Baseline.ModifiedPaths) != 0 ||
		len(report.Baseline.MissingPaths) != 0 {
		t.Fatalf("missing baseline must not produce fabricated drift: %+v", report.Baseline)
	}
}

func TestRunRejectsCorruptedBaselineManifest(t *testing.T) {
	k, root := newDiagnosticsTestKernel(t)

	writeDiagnosticTestFile(t, filepath.Join(root, "source.go"), "package example\n")

	baseline := createDiagnosticsTestBaseline(t, k)
	if len(baseline.Files) == 0 {
		t.Fatal("test fixture should contain at least one file")
	}

	// Change an individual record without updating the manifest checksum.
	baseline.Files[0].SHA256 = strings.Repeat("0", 64)
	saveDiagnosticsTestBaseline(t, k, baseline)

	report, err := Run(k)
	if err != nil {
		t.Fatalf("corrupt baseline should produce a report: %v", err)
	}

	if report.Status != "degraded" {
		t.Fatalf("corrupt baseline must degrade diagnostics: %+v", report)
	}

	if report.Baseline.Status != "unavailable" {
		t.Fatalf("corrupt baseline was not marked unavailable: %+v", report.Baseline)
	}

	if report.Baseline.AddedCount != 0 ||
		report.Baseline.ModifiedCount != 0 ||
		report.Baseline.MissingCount != 0 {
		t.Fatalf("corrupt baseline must not produce a trusted drift result: %+v", report.Baseline)
	}

	if len(report.Baseline.AddedPaths) != 0 ||
		len(report.Baseline.ModifiedPaths) != 0 ||
		len(report.Baseline.MissingPaths) != 0 {
		t.Fatalf("corrupt baseline returned path samples: %+v", report.Baseline)
	}
}

func TestRunRejectsUnsafeBaselinePath(t *testing.T) {
	k, root := newDiagnosticsTestKernel(t)

	writeDiagnosticTestFile(t, filepath.Join(root, "source.go"), "package example\n")

	baseline := createDiagnosticsTestBaseline(t, k)
	if len(baseline.Files) == 0 {
		t.Fatal("test fixture should contain at least one file")
	}

	// Path validation should reject this even before trusting the manifest
	// checksum. The resulting report must not disclose the injected path.
	baseline.Files[0].Path = filepath.Join(root, "outside.txt")
	saveDiagnosticsTestBaseline(t, k, baseline)

	report, err := Run(k)
	if err != nil {
		t.Fatalf("unsafe baseline should produce a diagnostic report: %v", err)
	}

	if report.Status != "degraded" ||
		report.Baseline.Status != "unavailable" {
		t.Fatalf("unsafe baseline was not rejected: %+v", report.Baseline)
	}

	encoded, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}

	if strings.Contains(string(encoded), root) {
		t.Fatal("diagnostics leaked an absolute path from an invalid baseline")
	}
}

func TestRunMalformedBaselineDegradesStatus(t *testing.T) {
	k, _ := newDiagnosticsTestKernel(t)

	path := filepath.Join(k.CoreRoot, "state", "baseline.json")
	writeDiagnosticTestFile(t, path, `{"schema_version":`)

	report, err := Run(k)
	if err != nil {
		t.Fatalf("malformed baseline should be reported without panic: %v", err)
	}

	if report.Status != "degraded" {
		t.Fatalf("malformed baseline should degrade diagnostics: %+v", report)
	}

	if report.Baseline.Status != "unavailable" {
		t.Fatalf("malformed baseline should be unavailable: %+v", report.Baseline)
	}
}

func TestRunBoundsDriftSamplesButPreservesFullCounts(t *testing.T) {
	k, root := newDiagnosticsTestKernel(t)

	const extraFiles = 7
	total := sampleLimit + extraFiles

	var paths []string
	for i := 0; i < total; i++ {
		name := filepath.Join(root, strings.Repeat("a", 0)+fileName(i))
		writeDiagnosticTestFile(t, name, "baseline content")
		paths = append(paths, name)
	}

	baseline := createDiagnosticsTestBaseline(t, k)
	saveDiagnosticsTestBaseline(t, k, baseline)

	for _, name := range paths {
		if err := os.Remove(name); err != nil {
			t.Fatalf("remove baseline file %q: %v", name, err)
		}
	}

	report, err := Run(k)
	if err != nil {
		t.Fatal(err)
	}

	if report.Baseline.Status != "compared" {
		t.Fatalf("baseline comparison did not finish: %+v", report.Baseline)
	}

	if report.Baseline.MissingCount != total {
		t.Fatalf("full missing count lost: got %d want %d", report.Baseline.MissingCount, total)
	}

	if len(report.Baseline.MissingPaths) != sampleLimit {
		t.Fatalf(
			"missing-path sample not bounded: got %d want %d",
			len(report.Baseline.MissingPaths),
			sampleLimit,
		)
	}

	if !report.Baseline.SamplesTruncated {
		t.Fatal("expected SamplesTruncated when path samples exceed the limit")
	}

	for i := 1; i < len(report.Baseline.MissingPaths); i++ {
		if report.Baseline.MissingPaths[i-1] > report.Baseline.MissingPaths[i] {
			t.Fatal("returned missing-path sample is not sorted")
		}
	}
}

func TestRunReportsUnsafeStorageAsDegraded(t *testing.T) {
	k, root := newDiagnosticsTestKernel(t)

	auditDir := filepath.Join(k.CoreRoot, "audit_log")
	if err := os.Remove(auditDir); err != nil {
		t.Fatalf("remove original audit directory: %v", err)
	}

	outside := filepath.Join(t.TempDir(), "external-audit")
	if err := os.MkdirAll(outside, 0700); err != nil {
		t.Fatal(err)
	}

	if err := os.Symlink(outside, auditDir); err != nil {
		t.Skipf("symlink creation unavailable: %v", err)
	}

	report, err := Run(k)
	if err != nil {
		t.Fatalf("storage failure should be reported: %v", err)
	}

	if report.Status != "degraded" {
		t.Fatalf("unsafe storage should degrade diagnostics: %+v", report)
	}

	foundFailure := false
	for _, check := range report.Storage {
		if check.Name == "audit_log" && check.Status == "failed" {
			foundFailure = true
		}
	}
	if !foundFailure {
		t.Fatalf("expected failed audit_log storage check: %+v", report.Storage)
	}

	if strings.Contains(strings.Join(report.Warnings, " "), outside) {
		t.Fatal("storage warning exposed the absolute external storage path")
	}

	// The test verifies the repository root is not exposed even when storage
	// diagnostics fail.
	encoded, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), root) {
		t.Fatal("degraded diagnostic report exposed repository filesystem paths")
	}
}

func TestRunNilKernelFailsExplicitly(t *testing.T) {
	report, err := Run(nil)
	if err == nil {
		t.Fatal("nil kernel must be reported as an error")
	}

	if report.Status != "degraded" {
		t.Fatalf("nil kernel should produce a degraded report: %+v", report)
	}

	if report.Baseline.Status != "not_recorded" {
		t.Fatalf("unexpected nil-kernel baseline status: %q", report.Baseline.Status)
	}

	if len(report.Warnings) == 0 {
		t.Fatal("nil-kernel report should explain why diagnostics could not run")
	}
}

func TestSampleReturnsNonNilEmptySlice(t *testing.T) {
	result := sample(nil)
	if result == nil {
		t.Fatal("sample(nil) must return an empty slice for stable JSON output")
	}
	if len(result) != 0 {
		t.Fatalf("expected empty sample, got %#v", result)
	}
}

func TestSampleTruncatesPathList(t *testing.T) {
	paths := make([]string, sampleLimit+5)
	for i := range paths {
		paths[i] = fileName(i)
	}

	result := sample(paths)
	if len(result) != sampleLimit {
		t.Fatalf("sample returned %d paths, expected %d", len(result), sampleLimit)
	}
}

func fileName(index int) string {
	return strings.Repeat("0", 4-len(strings.TrimLeft(strings.Repeat("0", 4)+strings.TrimSpace(string(rune('0'+index%10)), " "), "0"))) +
		strings.TrimSpace(string(rune('0'+index%10)), " ") +
		".txt"
}
