package kernel

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	gitCommandTimeout = 5 * time.Second

	maxScanFiles = 100000
	maxScanBytes int64 = 2 << 30 // 2 GiB per completed repository scan

	maxStateFileBytes int64 = 256 << 20 // 256 MiB
	maxAuditRecordBytes = 1 << 20       // 1 MiB
)

var excludedDirs = map[string]bool{
	".git":           true,
	"node_modules":   true,
	"vendor":         true,
	"venv":           true,
	".venv":          true,
	"__pycache__":    true,
	".pytest_cache":  true,
	".mypy_cache":    true,
	"dist":           true,
	"build":          true,
}

type FileRecord struct {
	Path     string `json:"path"`
	SHA256   string `json:"sha256"`
	Bytes    int64  `json:"bytes"`
	Language string `json:"language,omitempty"`
}

type ScanEvidence struct {
	SchemaVersion  string         `json:"schema_version"`
	GeneratedAt    time.Time      `json:"generated_at"`
	RepositoryRoot string         `json:"repository_root"`
	GitHead        string         `json:"git_head,omitempty"`
	FileCount      int            `json:"file_count"`
	LanguageCounts map[string]int `json:"language_counts"`
	ChangelogPaths []string       `json:"changelog_paths"`
	Files          []FileRecord   `json:"files"`
	ManifestSHA256 string         `json:"manifest_sha256"`
	ReadOnly       bool           `json:"read_only"`
	EvidenceNote   string         `json:"evidence_note"`
}

type AuditEvent struct {
	At           time.Time      `json:"at"`
	Action       string         `json:"action"`
	Actor        string         `json:"actor"`
	Subject      string         `json:"subject,omitempty"`
	Outcome      string         `json:"outcome"`
	Details      map[string]any `json:"details,omitempty"`
	PreviousHash string         `json:"previous_hash,omitempty"`
	Hash         string         `json:"hash,omitempty"`
}

type Kernel struct {
	Root     string
	CoreRoot string

	mu sync.Mutex
}

type Baseline struct {
	SchemaVersion  string       `json:"schema_version"`
	CreatedAt      time.Time    `json:"created_at"`
	GitHead        string       `json:"git_head"`
	Files          []FileRecord `json:"files"`
	ManifestSHA256 string       `json:"manifest_sha256"`
}

// New initializes the repository scanner and the local USECT-ZERO data
// directories. It resolves the repository path to avoid treating a symlink
// alias as the canonical repository location.
//
// USECT_ZERO_DATA_DIR may point outside the repository. The kernel creates
// its own private state, evidence, and audit_log directories beneath it.
func New(root string) (*Kernel, error) {
	if strings.TrimSpace(root) == "" {
		return nil, errors.New("repository root is required")
	}

	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root: %w", err)
	}

	abs, err = filepath.EvalSymlinks(abs)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root symlinks: %w", err)
	}

	info, err := os.Stat(abs)
	if err != nil {
		return nil, fmt.Errorf("inspect repository root: %w", err)
	}
	if !info.IsDir() {
		return nil, errors.New("repository root is not a directory")
	}

	core := filepath.Join(abs, "core-zero")

	if configured := strings.TrimSpace(os.Getenv("USECT_ZERO_DATA_DIR")); configured != "" {
		dataRoot, err := filepath.Abs(configured)
		if err != nil {
			return nil, fmt.Errorf("resolve USECT_ZERO_DATA_DIR: %w", err)
		}

		if err := os.MkdirAll(dataRoot, 0700); err != nil {
			return nil, fmt.Errorf("create USECT_ZERO_DATA_DIR: %w", err)
		}

		dataRoot, err = filepath.EvalSymlinks(dataRoot)
		if err != nil {
			return nil, fmt.Errorf("resolve data directory symlinks: %w", err)
		}

		info, err := os.Stat(dataRoot)
		if err != nil {
			return nil, fmt.Errorf("inspect USECT_ZERO_DATA_DIR: %w", err)
		}
		if !info.IsDir() {
			return nil, errors.New("USECT_ZERO_DATA_DIR must point to a directory")
		}

		core = dataRoot
	}

	k := &Kernel{
		Root:     abs,
		CoreRoot: core,
	}

	// Refuse to follow a symlink as the managed core root. A configured
	// data-root path is resolved before reaching this check.
	if err := ensurePhysicalDirectory(core, true); err != nil {
		return nil, fmt.Errorf("initialize core data root: %w", err)
	}

	for _, name := range []string{"state", "evidence", "audit_log"} {
		if err := k.ensureCoreDirectory(name); err != nil {
			return nil, fmt.Errorf("initialize %s directory: %w", name, err)
		}
	}

	return k, nil
}

// ensurePhysicalDirectory ensures that a specific directory exists and that
// the final path component is not a symlink. Its parent must already exist.
func ensurePhysicalDirectory(path string, create bool) error {
	info, err := os.Lstat(path)

	if errors.Is(err, os.ErrNotExist) && create {
		if err := os.Mkdir(path, 0700); err != nil && !errors.Is(err, os.ErrExist) {
			return err
		}
		info, err = os.Lstat(path)
	}

	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("refusing symlinked managed directory: %s", path)
	}
	if !info.IsDir() {
		return fmt.Errorf("managed path is not a directory: %s", path)
	}

	return nil
}

func randomID() (string, error) {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func digest(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func languageFor(path string) string {
	ext := strings.ToLower(filepath.Ext(path))

	extensions := map[string]string{
		".py":   "Python",
		".go":   "Go",
		".js":   "JavaScript",
		".jsx":  "JavaScript",
		".ts":   "TypeScript",
		".tsx":  "TypeScript",
		".rs":   "Rust",
		".java": "Java",
		".c":    "C",
		".h":    "C/C++",
		".cc":   "C++",
		".cpp":  "C++",
		".hpp":  "C++",
		".cs":   "C#",
		".rb":   "Ruby",
		".php":  "PHP",
		".swift": "Swift",
		".kt":   "Kotlin",
		".sh":   "Shell",
		".yaml": "YAML",
		".yml":  "YAML",
		".json": "JSON",
		".toml": "TOML",
		".md":   "Markdown",
		".html": "HTML",
		".css":  "CSS",
		".sql":  "SQL",
		".proto": "Protocol Buffers",
		".v":     "Verilog",
		".sv":    "SystemVerilog",
	}

	return extensions[ext]
}

// relativeSafe validates that rel names a location inside the repository.
// It also rejects paths that normalize through traversal components rather
// than silently rewriting the caller's input.
func (k *Kernel) relativeSafe(rel string) (string, error) {
	if k == nil || strings.TrimSpace(k.Root) == "" {
		return "", errors.New("repository root is not configured")
	}
	if strings.TrimSpace(rel) == "" || strings.ContainsRune(rel, '\x00') || filepath.IsAbs(rel) {
		return "", errors.New("path must be a non-empty relative path")
	}

	rel = filepath.FromSlash(rel)

	if filepath.VolumeName(rel) != "" {
		return "", errors.New("path must not contain a volume name")
	}

	clean := filepath.Clean(rel)
	if clean == "." ||
		clean == ".." ||
		filepath.IsAbs(clean) ||
		strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", errors.New("path escapes repository root")
	}

	root := filepath.Clean(k.Root)
	abs := filepath.Join(root, clean)

	final, err := filepath.Rel(root, abs)
	if err != nil {
		return "", errors.New("could not validate repository-relative path")
	}
	if final == ".." ||
		filepath.IsAbs(final) ||
		strings.HasPrefix(final, ".."+string(filepath.Separator)) {
		return "", errors.New("path escapes repository root")
	}

	return final, nil
}

func (k *Kernel) validateRepositoryRoot() error {
	if k == nil || strings.TrimSpace(k.Root) == "" {
		return errors.New("repository root is not configured")
	}

	info, err := os.Lstat(k.Root)
	if err != nil {
		return fmt.Errorf("inspect repository root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("repository root is no longer a physical directory")
	}

	return nil
}

func (k *Kernel) validateCoreRoot() error {
	if k == nil || strings.TrimSpace(k.CoreRoot) == "" {
		return errors.New("core data root is not configured")
	}

	info, err := os.Lstat(k.CoreRoot)
	if err != nil {
		return fmt.Errorf("inspect core data root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("core data root is not a physical directory")
	}

	return nil
}

// cleanCoreRelative validates paths within the managed USECT-ZERO data root.
func cleanCoreRelative(rel string) (string, error) {
	if rel == "" || strings.ContainsRune(rel, '\x00') || filepath.IsAbs(rel) {
		return "", errors.New("state path must be a non-empty relative path")
	}

	rel = filepath.FromSlash(rel)
	if filepath.VolumeName(rel) != "" {
		return "", errors.New("state path must not contain a volume name")
	}

	clean := filepath.Clean(rel)
	if clean == "." ||
		clean == ".." ||
		filepath.IsAbs(clean) ||
		strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", errors.New("state path escapes core root")
	}

	return clean, nil
}

// coreFilePath validates each existing parent component and rejects symlinks.
// When createParents is true, missing intermediate directories are created
// with owner-only permissions. The final component may not exist yet.
func (k *Kernel) coreFilePath(rel string, createParents bool) (string, error) {
	if err := k.validateCoreRoot(); err != nil {
		return "", err
	}

	clean, err := cleanCoreRelative(rel)
	if err != nil {
		return "", err
	}

	parts := strings.Split(clean, string(filepath.Separator))
	if len(parts) == 0 {
		return "", errors.New("invalid core data path")
	}

	current := filepath.Clean(k.CoreRoot)

	for _, part := range parts[:len(parts)-1] {
		if part == "" || part == "." || part == ".." {
			return "", errors.New("invalid core data path component")
		}

		current = filepath.Join(current, part)

		err := ensurePhysicalDirectory(current, createParents)
		if err != nil {
			return "", fmt.Errorf("validate core data directory: %w", err)
		}
	}

	dst := filepath.Join(k.CoreRoot, clean)

	// Lstat rather than Stat so a symlink cannot disguise a file outside the
	// configured data root.
	info, err := os.Lstat(dst)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("refusing symlinked state file")
		}
		if !info.Mode().IsRegular() {
			return "", errors.New("state path is not a regular file")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("inspect state file: %w", err)
	}

	return dst, nil
}

func (k *Kernel) git(args ...string) ([]byte, error) {
	if err := k.validateRepositoryRoot(); err != nil {
		return nil, err
	}

	ctx, cancel := context.WithTimeout(context.Background(), gitCommandTimeout)
	defer cancel()

	gitArgs := append([]string{"-C", k.Root}, args...)
	cmd := exec.CommandContext(ctx, "git", gitArgs...)
	cmd.Env = append(os.Environ(),
		"GIT_OPTIONAL_LOCKS=0",
		"GIT_TERMINAL_PROMPT=0",
	)

	output, err := cmd.Output()
	if ctx.Err() == context.DeadlineExceeded {
		return nil, errors.New("Git command timed out")
	}
	if err != nil {
		return nil, fmt.Errorf("Git command failed")
	}

	return output, nil
}

func (k *Kernel) GitHead() string {
	if k == nil {
		return ""
	}

	b, err := k.git("rev-parse", "--verify", "HEAD")
	if err != nil {
		return ""
	}

	return strings.TrimSpace(string(b))
}

// directoriesExcludedFromScan returns repository-relative managed storage
// directories. This matters when USECT_ZERO_DATA_DIR points inside the
// repository: evidence files must not recursively inventory themselves.
func (k *Kernel) directoriesExcludedFromScan() map[string]bool {
	excluded := make(map[string]bool, 3)

	if k == nil || k.Root == "" || k.CoreRoot == "" {
		return excluded
	}

	rel, err := filepath.Rel(k.Root, k.CoreRoot)
	if err != nil ||
		rel == "." ||
		rel == ".." ||
		filepath.IsAbs(rel) ||
		strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return excluded
	}

	for _, name := range []string{"state", "evidence", "audit_log"} {
		excluded[filepath.Clean(filepath.Join(rel, name))] = true
	}

	return excluded
}

func (k *Kernel) Scan() (ScanEvidence, error) {
	if err := k.validateRepositoryRoot(); err != nil {
		return ScanEvidence{}, err
	}
	if err := k.validateCoreRoot(); err != nil {
		return ScanEvidence{}, err
	}

	result := ScanEvidence{
		SchemaVersion:  "usect-zero.scan.v1",
		GeneratedAt:    time.Now().UTC(),
		RepositoryRoot: ".",
		GitHead:        k.GitHead(),
		LanguageCounts: map[string]int{},
		ChangelogPaths: []string{},
		Files:          []FileRecord{},
		ReadOnly:       true,
		EvidenceNote: "Repository-relative inventory of regular files. " +
			"Symbolic links and managed state directories are excluded. " +
			"This is not runtime-health or hardware verification.",
	}

	excludedStorage := k.directoriesExcludedFromScan()
	var totalBytes int64

	err := filepath.WalkDir(k.Root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			// A partial scan must never be silently reported as complete.
			return fmt.Errorf("scan could not inspect %q: %w", path, walkErr)
		}

		if path == k.Root {
			return nil
		}

		rel, err := filepath.Rel(k.Root, path)
		if err != nil {
			return fmt.Errorf("compute repository-relative path: %w", err)
		}
		rel = filepath.Clean(rel)

		if entry.IsDir() {
			if excludedDirs[entry.Name()] || excludedStorage[rel] {
				return filepath.SkipDir
			}
			return nil
		}

		// WalkDir does not follow symlink directories. Do not include symlink
		// files or special files such as sockets, FIFOs, and device nodes.
		info, err := entry.Info()
		if err != nil {
			return fmt.Errorf("inspect repository file %q: %w", rel, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return nil
		}

		if len(result.Files) >= maxScanFiles {
			return fmt.Errorf("scan exceeded the maximum of %d files", maxScanFiles)
		}

		remaining := maxScanBytes - totalBytes
		if remaining < 0 || info.Size() > remaining {
			return fmt.Errorf("scan exceeded the maximum byte budget of %d", maxScanBytes)
		}

		f, err := os.Open(path)
		if err != nil {
			return fmt.Errorf("open repository file %q: %w", rel, err)
		}

		openedInfo, statErr := f.Stat()
		if statErr != nil {
			_ = f.Close()
			return fmt.Errorf("inspect open repository file %q: %w", rel, statErr)
		}
		if !openedInfo.Mode().IsRegular() || !os.SameFile(info, openedInfo) {
			_ = f.Close()
			return fmt.Errorf("repository file changed during scan: %q", rel)
		}

		h := sha256.New()

		// Read at most one byte beyond the remaining budget so a file that
		// grows during scanning cannot bypass the resource limit.
		n, copyErr := io.Copy(h, io.LimitReader(f, remaining+1))
		afterInfo, afterErr := f.Stat()
		closeErr := f.Close()

		if copyErr != nil {
			return fmt.Errorf("hash repository file %q: %w", rel, copyErr)
		}
		if n > remaining {
			return fmt.Errorf("scan exceeded the maximum byte budget of %d", maxScanBytes)
		}
		if afterErr != nil {
			return fmt.Errorf("reinspect repository file %q: %w", rel, afterErr)
		}
		if closeErr != nil {
			return fmt.Errorf("close repository file %q: %w", rel, closeErr)
		}
		if !os.SameFile(openedInfo, afterInfo) ||
			openedInfo.Size() != afterInfo.Size() ||
			!openedInfo.ModTime().Equal(afterInfo.ModTime()) ||
			n != afterInfo.Size() {
			return fmt.Errorf("repository file changed during scan: %q", rel)
		}

		totalBytes += n

		safePath := filepath.ToSlash(rel)
		lang := languageFor(safePath)

		result.Files = append(result.Files, FileRecord{
			Path:     safePath,
			SHA256:   hex.EncodeToString(h.Sum(nil)),
			Bytes:    n,
			Language: lang,
		})

		if lang != "" {
			result.LanguageCounts[lang]++
		}

		lower := strings.ToLower(safePath)
		if strings.Contains(lower, "changelog") ||
			strings.Contains(lower, "change-log") {
			result.ChangelogPaths = append(result.ChangelogPaths, safePath)
		}

		return nil
	})
	if err != nil {
		return ScanEvidence{}, err
	}

	sort.Slice(result.Files, func(i, j int) bool {
		return result.Files[i].Path < result.Files[j].Path
	})
	sort.Strings(result.ChangelogPaths)

	result.FileCount = len(result.Files)

	manifest, err := json.Marshal(result.Files)
	if err != nil {
		return ScanEvidence{}, fmt.Errorf("serialize scan manifest: %w", err)
	}

	result.ManifestSHA256 = digest(manifest)

	return result, nil
}

// ensureCoreDirectory creates a child directory beneath CoreRoot while
// refusing to follow symlinks in the managed directory path.
func (k *Kernel) ensureCoreDirectory(rel string) error {
	clean, err := cleanCoreRelative(rel)
	if err != nil {
		return err
	}
	if err := k.validateCoreRoot(); err != nil {
		return err
	}

	current := filepath.Clean(k.CoreRoot)
	for _, part := range strings.Split(clean, string(filepath.Separator)) {
		if part == "" || part == "." || part == ".." {
			return errors.New("invalid managed directory component")
		}

		current = filepath.Join(current, part)

		if err := ensurePhysicalDirectory(current, true); err != nil {
			return err
		}
	}

	return nil
}

// writeJSON atomically writes a JSON document to a managed relative path.
// A unique temporary file avoids collisions between concurrent writers.
func (k *Kernel) writeJSON(rel string, v any) error {
	if k == nil {
		return errors.New("kernel is not initialized")
	}

	encoded, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Errorf("serialize state JSON: %w", err)
	}
	encoded = append(encoded, '\n')

	if int64(len(encoded)) > maxStateFileBytes {
		return errors.New("state JSON exceeds the maximum allowed file size")
	}

	k.mu.Lock()
	defer k.mu.Unlock()

	dst, err := k.coreFilePath(rel, true)
	if err != nil {
		return err
	}

	dir := filepath.Dir(dst)
	tmp, err := os.CreateTemp(dir, ".usect-zero-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary state file: %w", err)
	}

	tmpName := tmp.Name()
	defer os.Remove(tmpName)

	if err := tmp.Chmod(0600); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("secure temporary state file: %w", err)
	}

	n, writeErr := tmp.Write(encoded)
	if writeErr != nil {
		_ = tmp.Close()
		return fmt.Errorf("write temporary state file: %w", writeErr)
	}
	if n != len(encoded) {
		_ = tmp.Close()
		return io.ErrShortWrite
	}

	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("sync temporary state file: %w", err)
	}

	if err := tmp.Close(); err != nil {
		return fmt.Errorf("close temporary state file: %w", err)
	}

	// Recheck the destination immediately before replacement. Rename replaces
	// a destination symlink itself rather than following it on typical
	// supported filesystems; it does not authorize an outside path.
	if _, err := k.coreFilePath(rel, false); err != nil {
		return err
	}

	if err := os.Rename(tmpName, dst); err != nil {
		return fmt.Errorf("replace state file: %w", err)
	}

	return nil
}

func (k *Kernel) readJSON(rel string, v any) error {
	if k == nil {
		return errors.New("kernel is not initialized")
	}

	src, err := k.coreFilePath(rel, false)
	if err != nil {
		return err
	}

	f, err := os.Open(src)
	if err != nil {
		return err
	}

	openedInfo, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return fmt.Errorf("inspect state file: %w", err)
	}

	pathInfo, err := os.Lstat(src)
	if err != nil {
		_ = f.Close()
		return fmt.Errorf("reinspect state file: %w", err)
	}

	if pathInfo.Mode()&os.ModeSymlink != 0 ||
		!openedInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, pathInfo) {
		_ = f.Close()
		return errors.New("refusing to read an unsafe state file")
	}

	if openedInfo.Size() > maxStateFileBytes {
		_ = f.Close()
		return errors.New("state file exceeds the maximum allowed size")
	}

	data, readErr := io.ReadAll(io.LimitReader(f, maxStateFileBytes+1))
	closeErr := f.Close()

	if readErr != nil {
		return fmt.Errorf("read state file: %w", readErr)
	}
	if closeErr != nil {
		return fmt.Errorf("close state file: %w", closeErr)
	}
	if int64(len(data)) > maxStateFileBytes {
		return errors.New("state file exceeds the maximum allowed size")
	}

	if err := json.Unmarshal(data, v); err != nil {
		return fmt.Errorf("decode state JSON: %w", err)
	}

	return nil
}

func (k *Kernel) Audit(
	action,
	actor,
	subject,
	outcome string,
	details map[string]any,
) error {
	if k == nil {
		return errors.New("kernel is not initialized")
	}

	k.mu.Lock()
	defer k.mu.Unlock()

	event := AuditEvent{
		At:      time.Now().UTC(),
		Action:  action,
		Actor:   actor,
		Subject: subject,
		Outcome: outcome,
		Details: details,
	}
	previousHash, err := k.auditChainHeadLocked()
	if err != nil {
		return fmt.Errorf("refuse to append to an unverifiable audit log: %w", err)
	}
	event.PreviousHash = previousHash
	event.Hash = auditEventHash(event)

	line, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("serialize audit event: %w", err)
	}
	if len(line)+1 > maxAuditRecordBytes {
		return errors.New("audit event exceeds the maximum record size")
	}
	line = append(line, '\n')

	path, err := k.coreFilePath("audit_log/events.jsonl", true)
	if err != nil {
		return err
	}

	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("open audit log: %w", err)
	}

	openedInfo, statErr := f.Stat()
	pathInfo, pathErr := os.Lstat(path)
	if statErr != nil || pathErr != nil ||
		!openedInfo.Mode().IsRegular() ||
		pathInfo.Mode()&os.ModeSymlink != 0 ||
		!os.SameFile(openedInfo, pathInfo) {
		_ = f.Close()
		return errors.New("audit log changed or is not a safe regular file")
	}
	if err := f.Chmod(0600); err != nil {
		_ = f.Close()
		return fmt.Errorf("secure audit log permissions: %w", err)
	}

	n, err := f.Write(line)
	if err != nil {
		_ = f.Close()
		return fmt.Errorf("append audit event: %w", err)
	}
	if n != len(line) {
		_ = f.Close()
		return io.ErrShortWrite
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return fmt.Errorf("sync audit log: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("close audit log: %w", err)
	}
	return nil
}

func (k *Kernel) RecordBaseline() (Baseline, error) {
	if k == nil {
		return Baseline{}, errors.New("kernel is not initialized")
	}

	scan, err := k.Scan()
	if err != nil {
		return Baseline{}, fmt.Errorf("scan before baseline: %w", err)
	}
	if scan.GitHead == "" {
		return Baseline{}, errors.New(
			"baseline requires a local Git repository with a HEAD commit",
		)
	}

	baseline := Baseline{
		SchemaVersion:  "usect-zero.baseline.v1",
		CreatedAt:      time.Now().UTC(),
		GitHead:        scan.GitHead,
		Files:          scan.Files,
		ManifestSHA256: scan.ManifestSHA256,
	}

	if err := k.writeJSON("state/baseline.json", baseline); err != nil {
		return Baseline{}, fmt.Errorf("persist baseline: %w", err)
	}

	if err := k.Audit(
		"baseline_recorded",
		"local-operator",
		baseline.GitHead,
		"evidence_saved",
		map[string]any{
			"file_count":      len(baseline.Files),
			"manifest_sha256": baseline.ManifestSHA256,
		},
	); err != nil {
		return Baseline{}, fmt.Errorf("audit baseline recording: %w", err)
	}

	return baseline, nil
}

func (k *Kernel) LoadBaseline() (Baseline, error) {
	if k == nil {
		return Baseline{}, errors.New("kernel is not initialized")
	}

	var baseline Baseline
	if err := k.readJSON("state/baseline.json", &baseline); err != nil {
		return Baseline{}, err
	}

	return baseline, nil
}

func (k *Kernel) SaveEvidence() (ScanEvidence, error) {
	if k == nil {
		return ScanEvidence{}, errors.New("kernel is not initialized")
	}

	scan, err := k.Scan()
	if err != nil {
		return ScanEvidence{}, fmt.Errorf("scan repository: %w", err)
	}

	if err := k.writeJSON("evidence/latest-scan.json", scan); err != nil {
		return ScanEvidence{}, fmt.Errorf("persist scan evidence: %w", err)
	}

	if err := k.Audit(
		"repository_scan",
		"local-operator",
		scan.ManifestSHA256,
		"evidence_saved",
		map[string]any{
			"file_count": len(scan.Files),
			"git_head":   scan.GitHead,
		},
	); err != nil {
		return ScanEvidence{}, fmt.Errorf("audit repository scan: %w", err)
	}

	return scan, nil
}

// TrackedFiles returns Git-index paths using NUL delimiters so filenames
// containing spaces or line breaks are not silently corrupted by line parsing.
func (k *Kernel) TrackedFiles() ([]string, error) {
	if k == nil {
		return nil, errors.New("kernel is not initialized")
	}

	output, err := k.git("ls-files", "--cached", "-z")
	if err != nil {
		return nil, fmt.Errorf("git ls-files failed: %w", err)
	}

	var result []string
	for _, raw := range bytes.Split(output, []byte{0}) {
		if len(raw) == 0 {
			continue
		}

		name := string(raw)
		safe, err := k.relativeSafe(name)
		if err != nil {
			// An unsafe Git index path should not be silently trusted.
			return nil, fmt.Errorf("unsafe Git index path: %w", err)
		}

		result = append(result, filepath.ToSlash(safe))
	}

	sort.Strings(result)
	return result, nil
}
