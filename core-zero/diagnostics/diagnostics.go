// Package diagnostics provides read-only operational and baseline-drift reports.
//
// Diagnostics does not repair files, execute candidate code, or modify
// repository source files. Storage probes are confined to USECT-ZERO's
// managed data directories and are always cleaned up.
package diagnostics

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"usect-zero.local/core-zero/internal/kernel"
)

const (
	sampleLimit      = 50
	maxBaselineFiles = 100000
)

type RuntimeInfo struct {
	GoVersion string `json:"go_version"`
	OS        string `json:"os"`
	Arch      string `json:"arch"`
}

type RepositoryInfo struct {
	GitHead        string `json:"git_head,omitempty"`
	FileCount      int    `json:"file_count"`
	ManifestSHA256 string `json:"manifest_sha256"`
	ReadOnly       bool   `json:"read_only"`
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
	SchemaVersion string              `json:"schema_version"`
	GeneratedAt   time.Time            `json:"generated_at"`
	Status        string               `json:"status"`
	Runtime       RuntimeInfo          `json:"runtime"`
	Repository    RepositoryInfo       `json:"repository"`
	Baseline      BaselineComparison   `json:"baseline"`
	Storage       []StorageCheck       `json:"storage"`
	Warnings      []string             `json:"warnings"`
	SafetyNotes   []string             `json:"safety_notes"`
}

// Run returns a bounded operational report.
//
// It reads the repository, loads the saved baseline, compares manifests and
// checks whether managed storage directories support temporary-file creation,
// writing, syncing and cleanup. It does not change repository source files.
//
// A missing baseline is represented as not_recorded. A malformed or
// inconsistent baseline is reported as unavailable and degrades the report.
func Run(k *kernel.Kernel) (Report, error) {
	report := newReport()

	if k == nil {
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"Kernel is unavailable; repository and storage diagnostics could not run.",
		)
		return report, errors.New("diagnostics kernel is not initialized")
	}

	scan, err := k.Scan()
	if err != nil {
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"Repository scan failed; baseline comparison is incomplete.",
		)
		return report, fmt.Errorf("diagnostics repository scan failed: %w", err)
	}

	if err := validateFileRecords(
		scan.Files,
		scan.FileCount,
		scan.ManifestSHA256,
	); err != nil {
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"Repository scan evidence failed integrity checks; baseline comparison was not performed.",
		)
		return report, fmt.Errorf("repository scan evidence is invalid: %w", err)
	}

	report.Repository = RepositoryInfo{
		GitHead:        scan.GitHead,
		FileCount:      scan.FileCount,
		ManifestSHA256: scan.ManifestSHA256,
		ReadOnly:       true,
	}

	storageFailed := false

	for _, name := range []string{"state", "evidence", "audit_log"} {
		check := checkStorage(filepath.Join(k.CoreRoot, name), name)
		report.Storage = append(report.Storage, check)

		if check.Status != "ok" {
			storageFailed = true
		}
	}

	if storageFailed {
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"One or more USECT-ZERO storage directories failed their write, sync, or cleanup check.",
		)
	}

	baseline, err := k.LoadBaseline()
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			report.Baseline.Status = "not_recorded"
			report.Warnings = append(
				report.Warnings,
				"No recovery baseline is recorded; recovery proposals should remain unavailable until an operator records one.",
			)
			return report, nil
		}

		report.Baseline.Status = "unavailable"
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"The saved baseline could not be read or parsed; no drift comparison was performed.",
		)
		return report, nil
	}

	if err := validateBaseline(baseline); err != nil {
		report.Baseline.Status = "unavailable"
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"The saved baseline failed integrity validation; no drift comparison was performed.",
		)
		return report, nil
	}

	report.Baseline.Status = "compared"
	report.Baseline.GitHead = baseline.GitHead
	report.Baseline.ExpectedFileCount = len(baseline.Files)

	if err := compareFiles(&report.Baseline, baseline.Files, scan.Files); err != nil {
		report.Baseline.Status = "unavailable"
		report.Status = "degraded"
		report.Warnings = append(
			report.Warnings,
			"The baseline comparison could not be completed reliably.",
		)
		return report, fmt.Errorf("compare baseline manifests: %w", err)
	}

	if report.Baseline.AddedCount+
		report.Baseline.ModifiedCount+
		report.Baseline.MissingCount > 0 {
		report.Warnings = append(
			report.Warnings,
			"Repository files differ from the saved baseline; changes are reported for review and are not automatically reverted.",
		)
	}

	return report, nil
}

func newReport() Report {
	return Report{
		SchemaVersion: "usect-zero.diagnostics.v1",
		GeneratedAt:   time.Now().UTC(),
		Status:        "ready",
		Runtime: RuntimeInfo{
			GoVersion: runtime.Version(),
			OS:        runtime.GOOS,
			Arch:      runtime.GOARCH,
		},
		Baseline: BaselineComparison{
			Status:        "not_recorded",
			AddedPaths:    []string{},
			ModifiedPaths: []string{},
			MissingPaths:  []string{},
		},
		Storage:  []StorageCheck{},
		Warnings: []string{},
		SafetyNotes: []string{
			"Diagnostics do not execute candidate code or change repository source files.",
			"Baseline drift can represent legitimate development work; review paths before proposing recovery.",
			"Storage checks create and remove short-lived probe files inside USECT-ZERO managed data directories.",
			"Baseline integrity verification confirms internal consistency, not the authenticity of the operator who recorded it.",
			"A successful storage probe does not prove that all data is durable or that the storage device is healthy.",
			"Diagnostics reports are evidence for review and do not authorize repair or hardware action.",
		},
	}
}

// validateBaseline checks the baseline's schema, metadata, file records and
// manifest hash before its data is trusted for drift comparison.
func validateBaseline(baseline kernel.Baseline) error {
	if baseline.SchemaVersion != "usect-zero.baseline.v1" {
		return fmt.Errorf(
			"unsupported baseline schema version %q",
			baseline.SchemaVersion,
		)
	}

	if baseline.CreatedAt.IsZero() {
		return errors.New("baseline creation timestamp is missing")
	}

	if strings.TrimSpace(baseline.GitHead) == "" {
		return errors.New("baseline Git HEAD is missing")
	}

	if baseline.Files == nil {
		return errors.New("baseline file manifest is missing")
	}

	if len(baseline.Files) > maxBaselineFiles {
		return fmt.Errorf(
			"baseline contains too many files: %d",
			len(baseline.Files),
		)
	}

	if err := validateFileRecords(
		baseline.Files,
		len(baseline.Files),
		baseline.ManifestSHA256,
	); err != nil {
		return fmt.Errorf("baseline manifest validation failed: %w", err)
	}

	return nil
}

// validateFileRecords verifies paths, hashes, file sizes, duplicate entries,
// file counts and the manifest checksum.
//
// The manifest checksum is calculated with the same JSON serialization
// approach as Kernel.Scan.
func validateFileRecords(
	files []kernel.FileRecord,
	expectedCount int,
	manifestHash string,
) error {
	if expectedCount < 0 || len(files) != expectedCount {
		return errors.New("file count does not match manifest")
	}

	if !validSHA256(manifestHash) {
		return errors.New("manifest SHA-256 digest is invalid")
	}

	seen := make(map[string]struct{}, len(files))

	for index, file := range files {
		if err := validateRelativePath(file.Path); err != nil {
			return fmt.Errorf("file record %d has invalid path: %w", index, err)
		}

		if !validSHA256(file.SHA256) {
			return fmt.Errorf(
				"file record %d has an invalid SHA-256 digest",
				index,
			)
		}

		if file.Bytes < 0 {
			return fmt.Errorf("file record %d has a negative byte count", index)
		}

		if _, exists := seen[file.Path]; exists {
			return fmt.Errorf("duplicate manifest path %q", file.Path)
		}
		seen[file.Path] = struct{}{}
	}

	serialized, err := json.Marshal(files)
	if err != nil {
		return fmt.Errorf("serialize manifest: %w", err)
	}

	sum := sha256.Sum256(serialized)
	calculated := hex.EncodeToString(sum[:])

	if calculated != manifestHash {
		return errors.New("manifest SHA-256 does not match file records")
	}

	return nil
}

func validSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}

	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size
}

// validateRelativePath only accepts clean, slash-separated repository-relative
// paths. It rejects absolute paths, traversal, backslashes and empty paths.
func validateRelativePath(value string) error {
	if value == "" ||
		strings.ContainsRune(value, '\x00') ||
		strings.Contains(value, "\\") ||
		path.IsAbs(value) {
		return errors.New("path must be a non-empty relative path")
	}

	clean := path.Clean(value)

	if clean != value ||
		clean == "." ||
		clean == ".." ||
		strings.HasPrefix(clean, "../") {
		return errors.New("path is not normalized or escapes its root")
	}

	return nil
}

func compareFiles(
	result *BaselineComparison,
	baselineFiles []kernel.FileRecord,
	currentFiles []kernel.FileRecord,
) error {
	current := make(map[string]kernel.FileRecord, len(currentFiles))
	expected := make(map[string]kernel.FileRecord, len(baselineFiles))

	for _, file := range currentFiles {
		if _, exists := current[file.Path]; exists {
			return fmt.Errorf("duplicate current path %q", file.Path)
		}
		current[file.Path] = file
	}

	for _, file := range baselineFiles {
		if _, exists := expected[file.Path]; exists {
			return fmt.Errorf("duplicate baseline path %q", file.Path)
		}
		expected[file.Path] = file
	}

	for _, file := range baselineFiles {
		now, exists := current[file.Path]
		if !exists {
			result.MissingCount++
			result.MissingPaths = append(result.MissingPaths, file.Path)
			continue
		}

		if now.SHA256 != file.SHA256 || now.Bytes != file.Bytes {
			result.ModifiedCount++
			result.ModifiedPaths = append(result.ModifiedPaths, file.Path)
		}
	}

	for _, file := range currentFiles {
		if _, exists := expected[file.Path]; !exists {
			result.AddedCount++
			result.AddedPaths = append(result.AddedPaths, file.Path)
		}
	}

	sort.Strings(result.AddedPaths)
	sort.Strings(result.ModifiedPaths)
	sort.Strings(result.MissingPaths)

	result.SamplesTruncated =
		len(result.AddedPaths) > sampleLimit ||
		len(result.ModifiedPaths) > sampleLimit ||
		len(result.MissingPaths) > sampleLimit

	result.AddedPaths = sample(result.AddedPaths)
	result.ModifiedPaths = sample(result.ModifiedPaths)
	result.MissingPaths = sample(result.MissingPaths)

	return nil
}

// checkStorage verifies that a managed directory can create a temporary file,
// write to it, sync it, close it and remove it. It refuses a symlinked
// directory and does not report raw filesystem paths in the response.
func checkStorage(dir, name string) StorageCheck {
	info, err := os.Lstat(dir)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "directory is missing, inaccessible, or is not a physical directory",
		}
	}

	file, err := os.CreateTemp(dir, ".usect-zero-diagnostics-*")
	if err != nil {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "temporary write probe could not be created",
		}
	}

	tempName := file.Name()
	writeErr := error(nil)
	syncErr := error(nil)

	// The probe contains no credentials or application data.
	if _, err := file.Write([]byte("usect-zero-diagnostics-probe\n")); err != nil {
		writeErr = err
	} else if err := file.Sync(); err != nil {
		syncErr = err
	}

	closeErr := file.Close()
	removeErr := os.Remove(tempName)

	if writeErr != nil {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "temporary probe could not be written successfully",
		}
	}

	if syncErr != nil {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "temporary probe could not be synced successfully",
		}
	}

	if closeErr != nil {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "temporary probe could not be closed cleanly",
		}
	}

	if removeErr != nil {
		return StorageCheck{
			Name:   name,
			Status: "failed",
			Detail: "temporary probe could not be removed cleanly",
		}
	}

	return StorageCheck{
		Name:   name,
		Status: "ok",
		Detail: "temporary write, sync, close and cleanup probe passed",
	}
}

// sample returns a bounded, non-nil slice for stable JSON responses.
func sample(paths []string) []string {
	if len(paths) > sampleLimit {
		paths = paths[:sampleLimit]
	}

	if paths == nil {
		return []string{}
	}

	return paths
}
