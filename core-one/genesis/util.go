package genesis

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	maxUtilityJSONBytes = 64 << 20
	maxUtilityIDPrefix  = 40
	maxUtilitySlugBytes = 48
)

var (
	nonName             = regexp.MustCompile(`[^a-z0-9]+`)
	utilityIDFallbackID uint64
)

// jsonUnmarshal is the shared JSON decoding helper.
// The size cap protects callers from accidentally parsing unexpectedly large
// serialized objects. Callers handling untrusted files should also impose
// their own, usually smaller, limits before calling this function.
func jsonUnmarshal(b []byte, out any) error {
	if len(b) > maxUtilityJSONBytes {
		return fmt.Errorf(
			"JSON payload exceeds the %d-byte limit",
			maxUtilityJSONBytes,
		)
	}

	if out == nil {
		return errors.New("JSON destination cannot be nil")
	}

	if !utf8.Valid(b) {
		return errors.New("JSON payload is not valid UTF-8")
	}

	if err := json.Unmarshal(b, out); err != nil {
		return fmt.Errorf("decode JSON: %w", err)
	}

	return nil
}

// newID creates an opaque identifier using cryptographically secure random
// bytes. If the system random source is unavailable, a timestamp and an
// atomic process-local counter provide a collision-resistant fallback.
func newID(prefix string) string {
	prefix = normalizeUtilityIDPrefix(prefix)

	random := make([]byte, 16)
	if _, err := rand.Read(random); err == nil {
		return prefix + "-" + hex.EncodeToString(random)
	}

	counter := atomic.AddUint64(&utilityIDFallbackID, 1)
	return fmt.Sprintf(
		"%s-fallback-%d-%d",
		prefix,
		time.Now().UTC().UnixNano(),
		counter,
	)
}

func normalizeUtilityIDPrefix(prefix string) string {
	prefix = strings.ToLower(strings.TrimSpace(prefix))

	var b strings.Builder
	b.Grow(minUtilityInt(len(prefix), maxUtilityIDPrefix))

	separator := false

	for _, r := range prefix {
		switch {
		case r >= 'a' && r <= 'z',
			r >= '0' && r <= '9':
			b.WriteRune(r)
			separator = false

		case r == '_' || r == '-':
			if b.Len() > 0 && !separator {
				b.WriteRune(r)
				separator = true
			}

		default:
			if b.Len() > 0 && !separator {
				b.WriteByte('-')
				separator = true
			}
		}

		if b.Len() >= maxUtilityIDPrefix {
			break
		}
	}

	result := strings.Trim(b.String(), "-_")
	if result == "" {
		return "id"
	}

	return result
}

// sha256String returns the hexadecimal SHA-256 digest of a string.
// This is an integrity identifier, not encryption.
func sha256String(s string) string {
	hash := sha256.Sum256([]byte(s))
	return hex.EncodeToString(hash[:])
}

// limitText normalizes whitespace, removes unsafe control characters, and
// truncates to a maximum number of bytes without splitting UTF-8 characters.
//
// A non-positive limit returns an empty string.
func limitText(s string, max int) string {
	if max <= 0 || s == "" {
		return ""
	}

	s = strings.ToValidUTF8(s, "\uFFFD")

	var normalized strings.Builder
	normalized.Grow(minUtilityInt(len(s), max))

	for _, r := range s {
		if unicode.IsControl(r) {
			if unicode.IsSpace(r) {
				normalized.WriteByte(' ')
			}
			continue
		}

		normalized.WriteRune(r)
	}

	cleaned := strings.Join(strings.Fields(normalized.String()), " ")
	if len(cleaned) <= max {
		return cleaned
	}

	return truncateUtilityUTF8(cleaned, max)
}

func truncateUtilityUTF8(s string, maxBytes int) string {
	if maxBytes <= 0 {
		return ""
	}
	if len(s) <= maxBytes {
		return s
	}

	s = s[:maxBytes]
	for len(s) > 0 && !utf8.ValidString(s) {
		s = s[:len(s)-1]
	}

	return s
}

// slugName converts an arbitrary label into a bounded, path-friendly
// resource name consisting only of lowercase ASCII letters, digits,
// and underscores. Its output is safe for Genesis resource-name conventions.
func slugName(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	s = nonName.ReplaceAllString(s, "_")
	s = strings.Trim(s, "_")

	if s == "" {
		return "new_tool"
	}

	if s[0] < 'a' || s[0] > 'z' {
		s = "tool_" + s
	}

	if len(s) > maxUtilitySlugBytes {
		s = strings.TrimRight(s[:maxUtilitySlugBytes], "_")
	}

	if s == "" {
		return "new_tool"
	}

	return s
}

// atomicWrite writes data into a temporary file in the destination directory,
// flushes the file, then renames it into place.
//
// The temporary file is created on the same filesystem as the destination,
// preserving atomic replacement semantics on filesystems that support them.
func atomicWrite(path string, data []byte, mode os.FileMode) error {
	path = strings.TrimSpace(path)
	if path == "" {
		return errors.New("atomic write destination cannot be empty")
	}

	if len(data) > maxUtilityJSONBytes {
		return fmt.Errorf(
			"write payload exceeds the %d-byte limit",
			maxUtilityJSONBytes,
		)
	}

	path = filepath.Clean(path)
	base := filepath.Base(path)

	if base == "." || base == string(filepath.Separator) || base == "" {
		return errors.New("atomic write destination must be a file path")
	}

	dir := filepath.Dir(path)

	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create destination directory: %w", err)
	}

	dirInfo, err := os.Lstat(dir)
	if err != nil {
		return fmt.Errorf("inspect destination directory: %w", err)
	}
	if dirInfo.Mode()&os.ModeSymlink != 0 || !dirInfo.IsDir() {
		return errors.New("atomic write parent must be a directory, not a symlink")
	}

	// Do not silently follow or replace a destination symlink.
	if err := validateUtilityWriteTarget(path); err != nil {
		return err
	}

	file, err := os.CreateTemp(dir, ".genesis-*")
	if err != nil {
		return fmt.Errorf("create temporary file: %w", err)
	}

	tempPath := file.Name()
	closed := false

	defer func() {
		if !closed {
			_ = file.Close()
		}
		_ = os.Remove(tempPath)
	}()

	if err := file.Chmod(mode.Perm()); err != nil {
		return fmt.Errorf("set temporary file permissions: %w", err)
	}

	written, err := file.Write(data)
	if err != nil {
		return fmt.Errorf("write temporary file: %w", err)
	}
	if written != len(data) {
		return io.ErrShortWrite
	}

	if err := file.Sync(); err != nil {
		return fmt.Errorf("sync temporary file: %w", err)
	}

	if err := file.Close(); err != nil {
		closed = true
		return fmt.Errorf("close temporary file: %w", err)
	}
	closed = true

	// Recheck immediately before rename to catch a destination replaced with
	// a symlink while the temporary file was being written.
	if err := validateUtilityWriteTarget(path); err != nil {
		return err
	}

	if err := os.Rename(tempPath, path); err != nil {
		return fmt.Errorf("replace destination file: %w", err)
	}

	// Best-effort directory synchronization improves rename durability on
	// filesystems that support syncing directories. Some platforms do not.
	syncUtilityDirectory(dir)

	return nil
}

func validateUtilityWriteTarget(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("inspect write destination: %w", err)
	}

	if info.Mode()&os.ModeSymlink != 0 {
		return errors.New("write destination must not be a symlink")
	}

	if !info.Mode().IsRegular() {
		return errors.New("write destination must be a regular file")
	}

	return nil
}

func syncUtilityDirectory(path string) {
	dir, err := os.Open(path)
	if err != nil {
		return
	}
	defer dir.Close()

	_ = dir.Sync()
}

// writeJSON writes indented JSON followed by a newline using the atomic
// file-writing helper.
func writeJSON(path string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return fmt.Errorf("encode JSON for %s: %w", filepath.Base(path), err)
	}

	if len(raw)+1 > maxUtilityJSONBytes {
		return fmt.Errorf(
			"serialized JSON exceeds the %d-byte limit",
			maxUtilityJSONBytes,
		)
	}

	raw = append(raw, '\n')

	if err := atomicWrite(path, raw, 0o600); err != nil {
		return fmt.Errorf("write JSON file %s: %w", filepath.Base(path), err)
	}

	return nil
}

func minUtilityInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
