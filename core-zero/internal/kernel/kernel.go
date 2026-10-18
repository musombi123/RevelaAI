package kernel

import (
	"bufio"
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

var excludedDirs = map[string]bool{
	".git": true, "node_modules": true, "vendor": true, "venv": true,
	".venv": true, "__pycache__": true, ".pytest_cache": true,
	".mypy_cache": true, "dist": true, "build": true,
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
	At      time.Time      `json:"at"`
	Action  string         `json:"action"`
	Actor   string         `json:"actor"`
	Subject string         `json:"subject,omitempty"`
	Outcome string         `json:"outcome"`
	Details map[string]any `json:"details,omitempty"`
}
type Kernel struct {
	Root     string
	CoreRoot string
	mu       sync.Mutex
}

func New(root string) (*Kernel, error) {
	abs, err := filepath.Abs(root)
	if err != nil { return nil, err }
	info, err := os.Stat(abs)
	if err != nil { return nil, err }
	if !info.IsDir() { return nil, errors.New("repository root is not a directory") }
	core := filepath.Join(abs, "core-zero")
	if configured := strings.TrimSpace(os.Getenv("USECT_ZERO_DATA_DIR")); configured != "" {
		dataRoot, err := filepath.Abs(configured)
		if err != nil {
			return nil, fmt.Errorf("resolve USECT_ZERO_DATA_DIR: %w", err)
		}
		if err := os.MkdirAll(dataRoot, 0700); err != nil {
			return nil, fmt.Errorf("create USECT_ZERO_DATA_DIR: %w", err)
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
	for _, d := range []string{"state", "evidence", "audit_log"} {
		if err := os.MkdirAll(filepath.Join(core, d), 0700); err != nil { return nil, err }
	}
	return &Kernel{Root: abs, CoreRoot: core}, nil
}
func randomID() (string, error) {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil { return "", err }
	return hex.EncodeToString(b), nil
}
func digest(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func languageFor(path string) string {
	ext := strings.ToLower(filepath.Ext(path))
	m := map[string]string{".py": "Python", ".go": "Go", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".rs": "Rust", ".java": "Java", ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".sh": "Shell", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".toml": "TOML", ".md": "Markdown", ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".proto": "Protocol Buffers", ".v": "Verilog", ".sv": "SystemVerilog"}
	return m[ext]
}
func (k *Kernel) relativeSafe(rel string) (string, error) {
	if strings.TrimSpace(rel) == "" || filepath.IsAbs(rel) { return "", errors.New("path must be a non-empty relative path") }
	rel = filepath.Clean(rel)
	if rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) { return "", errors.New("path escapes repository root") }
	abs := filepath.Join(k.Root, rel)
	final, err := filepath.Rel(k.Root, abs)
	if err != nil || final == ".." || strings.HasPrefix(final, ".."+string(filepath.Separator)) { return "", errors.New("path escapes repository root") }
	return final, nil
}
func (k *Kernel) git(args ...string) ([]byte, error) {
	cmd := exec.Command("git", append([]string{"-C", k.Root}, args...)...)
	return cmd.Output()
}
func (k *Kernel) GitHead() string {
	b, err := k.git("rev-parse", "HEAD")
	if err != nil { return "" }
	return strings.TrimSpace(string(b))
}
func (k *Kernel) Scan() (ScanEvidence, error) {
	result := ScanEvidence{SchemaVersion: "usect-zero.scan.v1", GeneratedAt: time.Now().UTC(), RepositoryRoot: k.Root, GitHead: k.GitHead(), LanguageCounts: map[string]int{}, ChangelogPaths: []string{}, Files: []FileRecord{}, ReadOnly: true, EvidenceNote: "Local filesystem inventory; not a runtime-health or hardware verification."}
	err := filepath.WalkDir(k.Root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil { return nil }
		if path == k.Root { return nil }
		rel, err := filepath.Rel(k.Root, path)
		if err != nil { return nil }
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			base := d.Name()
			if excludedDirs[base] { return filepath.SkipDir }
			if rel == "core-zero/state" || rel == "core-zero/evidence" || rel == "core-zero/audit_log" { return filepath.SkipDir }
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 || !d.Type().IsRegular() { return nil }
		f, err := os.Open(path)
		if err != nil { return nil }
		h := sha256.New()
		n, copyErr := io.Copy(h, f)
		_ = f.Close()
		if copyErr != nil { return nil }
		lang := languageFor(rel)
		result.Files = append(result.Files, FileRecord{Path: rel, SHA256: hex.EncodeToString(h.Sum(nil)), Bytes: n, Language: lang})
		if lang != "" { result.LanguageCounts[lang]++ }
		lower := strings.ToLower(rel)
		if strings.Contains(lower, "changelog") || strings.Contains(lower, "change-log") { result.ChangelogPaths = append(result.ChangelogPaths, rel) }
		return nil
	})
	if err != nil { return result, err }
	sort.Slice(result.Files, func(i, j int) bool { return result.Files[i].Path < result.Files[j].Path })
	sort.Strings(result.ChangelogPaths)
	result.FileCount = len(result.Files)
	manifest, _ := json.Marshal(result.Files)
	result.ManifestSHA256 = digest(manifest)
	return result, nil
}

func (k *Kernel) writeJSON(rel string, v any) error {
	dst := filepath.Join(k.CoreRoot, rel)
	if !strings.HasPrefix(filepath.Clean(dst), filepath.Clean(k.CoreRoot)+string(filepath.Separator)) { return errors.New("state path escapes core root") }
	if err := os.MkdirAll(filepath.Dir(dst), 0700); err != nil { return err }
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil { return err }
	b = append(b, '\n')
	tmp := dst + ".tmp"
	if err = os.WriteFile(tmp, b, 0600); err != nil { return err }
	return os.Rename(tmp, dst)
}
func (k *Kernel) readJSON(rel string, v any) error {
	b, err := os.ReadFile(filepath.Join(k.CoreRoot, rel))
	if err != nil { return err }
	return json.Unmarshal(b, v)
}
func (k *Kernel) Audit(action, actor, subject, outcome string, details map[string]any) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	path := filepath.Join(k.CoreRoot, "audit_log", "events.jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil { return err }
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil { return err }
	defer f.Close()
	enc := json.NewEncoder(f)
	return enc.Encode(AuditEvent{At: time.Now().UTC(), Action: action, Actor: actor, Subject: subject, Outcome: outcome, Details: details})
}

type Baseline struct {
	SchemaVersion  string       `json:"schema_version"`
	CreatedAt      time.Time    `json:"created_at"`
	GitHead        string       `json:"git_head"`
	Files          []FileRecord `json:"files"`
	ManifestSHA256 string       `json:"manifest_sha256"`
}

func (k *Kernel) RecordBaseline() (Baseline, error) {
	scan, err := k.Scan()
	if err != nil { return Baseline{}, err }
	if scan.GitHead == "" { return Baseline{}, errors.New("baseline requires a local Git repository with a HEAD commit") }
	b := Baseline{SchemaVersion: "usect-zero.baseline.v1", CreatedAt: time.Now().UTC(), GitHead: scan.GitHead, Files: scan.Files, ManifestSHA256: scan.ManifestSHA256}
	if err = k.writeJSON("state/baseline.json", b); err != nil { return Baseline{}, err }
	if err = k.Audit("baseline_recorded", "local-operator", b.GitHead, "evidence_saved", map[string]any{"file_count": len(b.Files), "manifest_sha256": b.ManifestSHA256}); err != nil { return Baseline{}, err }
	return b, nil
}
func (k *Kernel) LoadBaseline() (Baseline, error) {
	var b Baseline
	err := k.readJSON("state/baseline.json", &b)
	return b, err
}
func (k *Kernel) SaveEvidence() (ScanEvidence, error) {
	s, err := k.Scan()
	if err != nil { return s, err }
	if err = k.writeJSON("evidence/latest-scan.json", s); err != nil { return s, err }
	if err = k.Audit("repository_scan", "local-operator", s.ManifestSHA256, "evidence_saved", map[string]any{"file_count": s.FileCount, "git_head": s.GitHead}); err != nil { return s, err }
	return s, nil
}
func (k *Kernel) TrackedFiles() ([]string, error) {
	b, err := k.git("ls-files", "--cached")
	if err != nil { return nil, fmt.Errorf("git ls-files failed: %w", err) }
	s := bufio.NewScanner(strings.NewReader(string(b)))
	var out []string
	for s.Scan() {
		p := strings.TrimSpace(s.Text())
		if p != "" {
			if clean, e := k.relativeSafe(p); e == nil { out = append(out, filepath.ToSlash(clean)) }
		}
	}
	return out, s.Err()
}
