package mind

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	maxRepositoryEntries = 500000
	maxReportedPaths     = 500
)

type repositoryInventory struct {
	RepositoryRoot          string         `json:"repository_root"`
	ObservedAt              time.Time      `json:"observed_at"`
	Complete                bool           `json:"complete"`
	EntriesScanned          int            `json:"entries_scanned"`
	DirectoriesScanned      int            `json:"directories_scanned"`
	FilesScanned            int            `json:"files_scanned"`
	SymlinksObserved        int            `json:"symlinks_observed"`
	GitDirectoriesExcluded int            `json:"git_directories_excluded"`
	TotalRegularFileBytes   int64          `json:"total_regular_file_bytes"`
	LanguageCounts          map[string]int `json:"language_counts"`
	CorePathCounts          map[string]int `json:"core_path_counts"`
	HubPathCounts           map[string]int `json:"hub_path_counts"`
	PriorityPaths           []string       `json:"priority_paths,omitempty"`
	HubPaths                []string       `json:"hub_paths,omitempty"`
	OpenAPIPaths             []string       `json:"openapi_paths,omitempty"`
	ChangelogPaths           []string       `json:"changelog_paths,omitempty"`
	AuditLogPaths            []string       `json:"audit_log_paths,omitempty"`
	PathSizeManifestSHA256   string         `json:"path_size_manifest_sha256"`
	LimitsNote               string         `json:"limits_note"`
}

// scanRepositoryInventory creates a read-only inventory of repository paths.
//
// It does not execute or copy source files and never follows symlinks.
// The manifest is a digest of relative paths, entry types, and regular-file
// sizes; file contents are not included.
//
// The scan fails rather than returning a complete-looking inventory if a
// filesystem error occurs or the configured entry limit is exceeded.
func (s *Service) scanRepositoryInventory() (repositoryInventory, error) {
	if s == nil || strings.TrimSpace(s.RepoRoot) == "" {
		return repositoryInventory{}, fmt.Errorf(
			"repository root is required",
		)
	}

	root, err := filepath.Abs(filepath.Clean(s.RepoRoot))
	if err != nil {
		return repositoryInventory{}, fmt.Errorf(
			"resolve repository root: %w",
			err,
		)
	}

	rootInfo, err := os.Lstat(root)
	if err != nil {
		return repositoryInventory{}, fmt.Errorf(
			"inspect repository root: %w",
			err,
		)
	}

	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return repositoryInventory{}, fmt.Errorf(
			"repository root must be an existing, non-symlink directory",
		)
	}

	inventory := repositoryInventory{
		RepositoryRoot: "configured_repository_root",
		ObservedAt:     time.Now().UTC(),
		Complete:       true,
		EntriesScanned: 1,
		DirectoriesScanned: 1,
		LanguageCounts: make(map[string]int),
		CorePathCounts: map[string]int{
			"core-zero":            0,
			"core-one-inventions":  0,
			"core-one-libraries":   0,
			"core-one-guardian":    0,
			"core-two":             0,
		},
		HubPathCounts: make(map[string]int),
		PriorityPaths: make([]string, 0),
		HubPaths:      make([]string, 0),
		OpenAPIPaths:  make([]string, 0),
		ChangelogPaths: make([]string, 0),
		AuditLogPaths: make([]string, 0),
		LimitsNote: "Read-only path and size inventory. Source contents are not " +
			"read or executed. Symlinks are inventoried by name but never followed. " +
			".git directories and their contents are excluded. Every encountered " +
			"entry counts toward the 500,000-entry limit; incomplete scans return " +
			"an error rather than a successful partial inventory.",
	}

	manifestHasher := sha256.New()

	hubNames := map[string]bool{
		"elimu":        true,
		"shamba":       true,
		"biashara":     true,
		"community":    true,
		"scripture":    true,
		"faith":        true,
		"theology":     true,
		"education":    true,
		"agriculture":  true,
		"marketplace":  true,
		"study":        true,
		"study-hub":    true,
	}

	walkErr := filepath.WalkDir(root, func(
		path string,
		entry fs.DirEntry,
		incomingErr error,
	) error {
		if incomingErr != nil {
			return incomingErr
		}

		if path == root {
			return nil
		}

		// Count every encountered entry, including symlinks and the .git
		// directory itself. The root was counted during initialization.
		inventory.EntriesScanned++
		if inventory.EntriesScanned > maxRepositoryEntries {
			return fmt.Errorf(
				"repository scan exceeded the %d-entry safety cap",
				maxRepositoryEntries,
			)
		}

		relative, err := filepath.Rel(root, path)
		if err != nil {
			return fmt.Errorf("make relative repository path: %w", err)
		}

		relative = filepath.ToSlash(relative)
		lower := strings.ToLower(relative)

		// Never descend into Git internals. WalkDir does not follow symlinks,
		// so a symlink named .git is not treated as a real repository directory.
		if entry.IsDir() && entry.Name() == ".git" {
			inventory.GitDirectoriesExcluded++
			return filepath.SkipDir
		}

		kind := "other"
		var size int64

		switch {
		case entry.Type()&os.ModeSymlink != 0:
			kind = "symlink"
			inventory.SymlinksObserved++

		case entry.IsDir():
			kind = "directory"
			inventory.DirectoriesScanned++

		default:
			inventory.FilesScanned++

			info, infoErr := entry.Info()
			if infoErr != nil {
				return fmt.Errorf(
					"inspect repository entry %q: %w",
					relative,
					infoErr,
				)
			}

			if info.Mode().IsRegular() {
				kind = "regular_file"
				size = info.Size()

				if size < 0 {
					return fmt.Errorf(
						"regular file %q has a negative size",
						relative,
					)
				}

				if inventory.TotalRegularFileBytes >
					math.MaxInt64-size {
					return fmt.Errorf(
						"regular file byte total exceeds int64 capacity",
					)
				}

				inventory.TotalRegularFileBytes += size
				inventory.LanguageCounts[languageForPath(relative)]++
			} else if info.Mode()&os.ModeNamedPipe != 0 {
				kind = "named_pipe"
			} else if info.Mode()&os.ModeSocket != 0 {
				kind = "socket"
			} else if info.Mode()&os.ModeDevice != 0 {
				kind = "device"
			}
		}

		// Include every observed non-Git entry in the path/metadata manifest.
		// Symlinks are recorded by their path and type; their targets are never read.
		if _, err := fmt.Fprintf(
			manifestHasher,
			"%s\x00%s\x00%d\n",
			relative,
			kind,
			size,
		); err != nil {
			return fmt.Errorf(
				"update repository manifest: %w",
				err,
			)
		}

		updateCorePathCounts(&inventory, lower)

		segments := strings.Split(lower, "/")
		inHub := false

		for _, segment := range segments {
			if hubNames[segment] {
				inventory.HubPathCounts[segment]++
				inHub = true
			}
		}

		if inHub {
			inventory.HubPaths = appendBounded(
				inventory.HubPaths,
				relative,
			)
		}

		base := strings.ToLower(filepath.Base(relative))

		if isOpenAPIPath(lower) {
			inventory.OpenAPIPaths = appendBounded(
				inventory.OpenAPIPaths,
				relative,
			)
			inventory.PriorityPaths = appendBounded(
				inventory.PriorityPaths,
				relative,
			)
		}

		if strings.Contains(lower, "changelog") ||
			strings.HasPrefix(base, "changes-") ||
			base == "changes.md" {
			inventory.ChangelogPaths = appendBounded(
				inventory.ChangelogPaths,
				relative,
			)
			inventory.PriorityPaths = appendBounded(
				inventory.PriorityPaths,
				relative,
			)
		}

		if strings.Contains(lower, "audit_log") {
			inventory.AuditLogPaths = appendBounded(
				inventory.AuditLogPaths,
				relative,
			)
			inventory.PriorityPaths = appendBounded(
				inventory.PriorityPaths,
				relative,
			)
		}

		if strings.HasPrefix(lower, "core-zero/") ||
			strings.HasPrefix(lower, "core-one/inventions/") ||
			strings.HasPrefix(lower, "core-one/libraries/") ||
			strings.HasPrefix(lower, "core-one/guardian/") {
			inventory.PriorityPaths = appendBounded(
				inventory.PriorityPaths,
				relative,
			)
		}

		return nil
	})

	if walkErr != nil {
		return repositoryInventory{}, fmt.Errorf(
			"repository inventory incomplete after %d entries: %w",
			inventory.EntriesScanned,
			walkErr,
		)
	}

	inventory.PathSizeManifestSHA256 = hex.EncodeToString(
		manifestHasher.Sum(nil),
	)

	inventory.PriorityPaths = sortedUnique(inventory.PriorityPaths)
	inventory.HubPaths = sortedUnique(inventory.HubPaths)
	inventory.OpenAPIPaths = sortedUnique(inventory.OpenAPIPaths)
	inventory.ChangelogPaths = sortedUnique(inventory.ChangelogPaths)
	inventory.AuditLogPaths = sortedUnique(inventory.AuditLogPaths)

	return inventory, nil
}

func updateCorePathCounts(
	inventory *repositoryInventory,
	lower string,
) {
	switch {
	case lower == "core-zero" || strings.HasPrefix(lower, "core-zero/"):
		inventory.CorePathCounts["core-zero"]++

	case lower == "core-one/inventions" ||
		strings.HasPrefix(lower, "core-one/inventions/"):
		inventory.CorePathCounts["core-one-inventions"]++

	case lower == "core-one/libraries" ||
		strings.HasPrefix(lower, "core-one/libraries/"):
		inventory.CorePathCounts["core-one-libraries"]++

	case lower == "core-one/guardian" ||
		strings.HasPrefix(lower, "core-one/guardian/"):
		inventory.CorePathCounts["core-one-guardian"]++
	}

	if lower == "core-two" || strings.HasPrefix(lower, "core-two/") {
		inventory.CorePathCounts["core-two"]++
	}
}

func isOpenAPIPath(lower string) bool {
	return lower == "openapi.yaml" ||
		lower == "openapi.yml" ||
		strings.HasSuffix(lower, "/openapi.yaml") ||
		strings.HasSuffix(lower, "/openapi.yml")
}

func appendBounded(paths []string, path string) []string {
	if len(paths) >= maxReportedPaths {
		return paths
	}
	return append(paths, path)
}

func languageForPath(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".go":
		return "go"
	case ".py":
		return "python"
	case ".js", ".mjs", ".cjs":
		return "javascript"
	case ".jsx":
		return "jsx"
	case ".ts", ".mts", ".cts":
		return "typescript"
	case ".tsx":
		return "tsx"
	case ".json":
		return "json"
	case ".yaml", ".yml":
		return "yaml"
	case ".md", ".mdx":
		return "markdown"
	case ".html", ".htm":
		return "html"
	case ".css":
		return "css"
	case ".rs":
		return "rust"
	case ".c", ".h":
		return "c"
	case ".cpp", ".cc", ".hpp", ".hh":
		return "cpp"
	case ".java":
		return "java"
	case ".sql":
		return "sql"
	case ".sh", ".ps1", ".bat":
		return "shell"
	case ".toml":
		return "toml"
	case ".xml":
		return "xml"
	default:
		return "other"
	}
}

func sortedUnique(values []string) []string {
	if len(values) < 2 {
		return values
	}

	sort.Strings(values)

	out := values[:1]
	for _, value := range values[1:] {
		if value != out[len(out)-1] {
			out = append(out, value)
		}
	}

	return out
}
