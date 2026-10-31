// Package inventory collects bounded metadata and hashes from an explicitly
// selected local directory. It never follows symlinks or executes files.
package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	DefaultMaxFiles = 10000
	MaxFileBytes    = int64(256 << 20)
)

type FileRecord struct {
	Path       string    `json:"path"`
	Size       int64     `json:"size"`
	ModifiedAt time.Time `json:"modified_at"`
	Mode       string    `json:"mode"`
	SHA256     string    `json:"sha256,omitempty"`
	Status     string    `json:"status"`
	Note       string    `json:"note,omitempty"`
}

type Result struct {
	Root       string       `json:"root"`
	ScannedAt  time.Time    `json:"scanned_at"`
	Files      []FileRecord `json:"files"`
	TotalFiles int          `json:"total_files"`
	Hashed     int          `json:"hashed"`
	Skipped    int          `json:"skipped"`
	ReadOnly   bool         `json:"read_only"`
}

func Scan(root string, maxFiles int) (Result, error) {
	if strings.TrimSpace(root) == "" {
		return Result{}, errors.New("root path is required")
	}
	if maxFiles <= 0 || maxFiles > DefaultMaxFiles {
		return Result{}, fmt.Errorf("maxFiles must be between 1 and %d", DefaultMaxFiles)
	}
	absolute, err := filepath.Abs(root)
	if err != nil {
		return Result{}, fmt.Errorf("resolve root: %w", err)
	}
	rootInfo, err := os.Lstat(absolute)
	if err != nil {
		return Result{}, fmt.Errorf("inspect root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return Result{}, errors.New("root must be a real directory, not a symlink")
	}

	result := Result{Root: absolute, ScannedAt: time.Now().UTC(), Files: []FileRecord{}, ReadOnly: true}
	err = filepath.WalkDir(absolute, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			result.Skipped++
			return nil
		}
		if path == absolute {
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			result.Skipped++
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.IsDir() {
			name := entry.Name()
			if name == ".git" || name == "node_modules" || name == ".venv" || name == "venv" || name == "__pycache__" {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			result.Skipped++
			return nil
		}
		if result.TotalFiles >= maxFiles {
			return fmt.Errorf("file limit reached (%d); narrow the selected directory", maxFiles)
		}
		rel, err := filepath.Rel(absolute, path)
		if err != nil {
			result.Skipped++
			return nil
		}
		rec := FileRecord{
			Path: filepath.ToSlash(rel), Size: info.Size(), ModifiedAt: info.ModTime().UTC(),
			Mode: info.Mode().String(), Status: "metadata_only",
		}
		result.TotalFiles++
		if info.Size() > MaxFileBytes {
			rec.Note = "larger than hashing limit; content not read"
			result.Skipped++
			result.Files = append(result.Files, rec)
			return nil
		}

		before, err := os.Stat(path)
		if err != nil {
			rec.Status, rec.Note = "unavailable", "file could not be opened"
			result.Skipped++
			result.Files = append(result.Files, rec)
			return nil
		}
		f, err := os.Open(path)
		if err != nil {
			rec.Status, rec.Note = "unavailable", "file could not be opened"
			result.Skipped++
			result.Files = append(result.Files, rec)
			return nil
		}
		h := sha256.New()
		n, copyErr := io.Copy(h, io.LimitReader(f, MaxFileBytes+1))
		_ = f.Close()
		after, statErr := os.Stat(path)
		if copyErr != nil || statErr != nil || n != before.Size() || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
			rec.Status, rec.Note = "changed_or_unreadable", "file changed during read or could not be hashed reliably"
			result.Skipped++
			result.Files = append(result.Files, rec)
			return nil
		}
		rec.SHA256 = hex.EncodeToString(h.Sum(nil))
		rec.Status = "hashed"
		result.Hashed++
		result.Files = append(result.Files, rec)
		return nil
	})
	if err != nil {
		return result, err
	}
	return result, nil
}
