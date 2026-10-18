// Package diagnostics provides read-only operational and baseline-drift reports.
package diagnostics

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"time"

	"usect-zero.local/core-zero/internal/kernel"
)

const sampleLimit = 50

type RuntimeInfo struct {
	GoVersion string `json:"go_version"`
	OS        string `json:"os"`
	Arch      string `json:"arch"`
}

type RepositoryInfo struct {
	GitHead         string `json:"git_head,omitempty"`
	FileCount       int    `json:"file_count"`
	ManifestSHA256  string `json:"manifest_sha256"`
	ReadOnly        bool   `json:"read_only"`
}

type BaselineComparison struct {
	Status            string   `json:"status"`
	GitHead           string   `json:"git_head,omitempty"`
	ExpectedFileCount int      `json:"expected_file_count"`
	AddedCount        int      `json:"added_count"`
	ModifiedCount     int      `json:"modified_count"`
	MissingCount      int      `json:"missing_count"`
	AddedPaths        []string `json:"added_paths"`
	ModifiedPaths     []string `json:"modified_paths"`
	MissingPaths      []string `json:"missing_paths"`
	SamplesTruncated  bool     `json:"samples_truncated"`
}

type StorageCheck struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Detail string `json:"detail"`
}

type Report struct {
	SchemaVersion string             `json:"schema_version"`
	GeneratedAt   time.Time           `json:"generated_at"`
	Status        string              `json:"status"`
	Runtime       RuntimeInfo         `json:"runtime"`
	Repository    RepositoryInfo      `json:"repository"`
	Baseline      BaselineComparison `json:"baseline"`
	Storage       []StorageCheck      `json:"storage"`
	Warnings      []string            `json:"warnings"`
	SafetyNotes   []string            `json:"safety_notes"`
}

// Run returns an operational report without writing to repository files. Storage
// checks use short-lived temporary files inside USECT-ZERO's own data directories.
func Run(k *kernel.Kernel) (Report, error) {
	report := Report{
		SchemaVersion: "usect-zero.diagnostics.v1",
		GeneratedAt: time.Now().UTC(),
		Status: "ready",
		Runtime: RuntimeInfo{GoVersion: runtime.Version(), OS: runtime.GOOS, Arch: runtime.GOARCH},
		Baseline: BaselineComparison{
			Status: "not_recorded",
			AddedPaths: []string{},
			ModifiedPaths: []string{},
			MissingPaths: []string{},
		},
		Storage: []StorageCheck{},
		Warnings: []string{},
		SafetyNotes: []string{
			"Diagnostics do not execute candidate code or change repository files.",
			"Baseline drift can represent legitimate development work; review paths before recovery.",
			"Storage checks create and remove short-lived probe files inside USECT-ZERO data directories.",
		},
	}

	scan, err := k.Scan()
	if err != nil {
		report.Status = "degraded"
		report.Warnings = append(report.Warnings, "Repository scan failed; baseline comparison is incomplete.")
		return report, err
	}
	report.Repository = RepositoryInfo{
		GitHead: scan.GitHead,
		FileCount: scan.FileCount,
		ManifestSHA256: scan.ManifestSHA256,
		ReadOnly: true,
	}

	for _, name := range []string{"state", "evidence", "audit_log"} {
		check := checkStorage(filepath.Join(k.CoreRoot, name), name)
		report.Storage = append(report.Storage, check)
		if check.Status != "ok" {
			report.Status = "degraded"
			report.Warnings = append(report.Warnings, "One or more USECT-ZERO storage directories failed their write/delete check.")
		}
	}

	baseline, err := k.LoadBaseline()
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			report.Warnings = append(report.Warnings, "No recovery baseline is recorded; recovery proposals should remain unavailable until an operator records one.")
		} else {
			report.Baseline.Status = "unavailable"
			report.Warnings = append(report.Warnings, "The saved baseline could not be read or parsed.")
		}
		return report, nil
	}

	report.Baseline.Status = "compared"
	report.Baseline.GitHead = baseline.GitHead
	report.Baseline.ExpectedFileCount = len(baseline.Files)

	current := make(map[string]kernel.FileRecord, len(scan.Files))
	expected := make(map[string]kernel.FileRecord, len(baseline.Files))
	for _, item := range scan.Files {
		current[item.Path] = item
	}
	for _, item := range baseline.Files {
		expected[item.Path] = item
		if now, ok := current[item.Path]; !ok {
			report.Baseline.MissingCount++
			report.Baseline.MissingPaths = append(report.Baseline.MissingPaths, item.Path)
		} else if now.SHA256 != item.SHA256 {
			report.Baseline.ModifiedCount++
			report.Baseline.ModifiedPaths = append(report.Baseline.ModifiedPaths, item.Path)
		}
	}
	for path := range current {
		if _, ok := expected[path]; !ok {
			report.Baseline.AddedCount++
			report.Baseline.AddedPaths = append(report.Baseline.AddedPaths, path)
		}
	}
	sort.Strings(report.Baseline.AddedPaths)
	sort.Strings(report.Baseline.ModifiedPaths)
	sort.Strings(report.Baseline.MissingPaths)
	report.Baseline.SamplesTruncated =
		len(report.Baseline.AddedPaths) > sampleLimit ||
		len(report.Baseline.ModifiedPaths) > sampleLimit ||
		len(report.Baseline.MissingPaths) > sampleLimit
	report.Baseline.AddedPaths = sample(report.Baseline.AddedPaths)
	report.Baseline.ModifiedPaths = sample(report.Baseline.ModifiedPaths)
	report.Baseline.MissingPaths = sample(report.Baseline.MissingPaths)

	if report.Baseline.AddedCount+report.Baseline.ModifiedCount+report.Baseline.MissingCount > 0 {
		report.Warnings = append(report.Warnings, "Repository files differ from the saved baseline; changes are reported for review and are not automatically reverted.")
	}
	return report, nil
}

func checkStorage(dir, name string) StorageCheck {
	info, err := os.Stat(dir)
	if err != nil || !info.IsDir() {
		return StorageCheck{Name: name, Status: "failed", Detail: "directory is missing or inaccessible"}
	}
	f, err := os.CreateTemp(dir, ".usect-zero-diagnostics-*")
	if err != nil {
		return StorageCheck{Name: name, Status: "failed", Detail: "temporary write probe could not be created"}
	}
	tempName := f.Name()
	closeErr := f.Close()
	removeErr := os.Remove(tempName)
	if closeErr != nil || removeErr != nil {
		return StorageCheck{Name: name, Status: "failed", Detail: "temporary probe could not be closed and removed cleanly"}
	}
	return StorageCheck{Name: name, Status: "ok", Detail: "write and cleanup probe passed"}
}

func sample(paths []string) []string {
	if len(paths) > sampleLimit {
		return paths[:sampleLimit]
	}
	if paths == nil {
		return []string{}
	}
	return paths
}
