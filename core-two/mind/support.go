package mind

import (
	"bufio"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

const (
	maxMindJSONBodyBytes      int64 = 1 << 20
	maxMindWriteBytes         int   = 64 << 20
	maxMindLogBytes           int64 = 64 << 20
	maxMindLogLineBytes             = 1 << 20
	maxLibraryInventoryFiles        = 10000
	maxLibrarySourceBytes           = 8 << 20
	maxLibraryInventoryBytes  int64 = 128 << 20
)

// countEndpointUsage counts recognized HTTP endpoint events.
//
// The boolean reports whether the file was read successfully, including when
// zero matching events were found.
func countEndpointUsage(path string) (int, bool) {
	count := 0

	_, err := scanMindJSONLines(path, func(line []byte) {
		var event map[string]any
		if json.Unmarshal(line, &event) != nil {
			return
		}

		eventType, _ := event["type"].(string)
		switch eventType {
		case "http_request", "endpoint_access", "endpoint_used":
			count++
		}
	})

	return count, err == nil
}

func (s *Service) productionToolCount() int {
	if s == nil || s.One == nil {
		return 0
	}

	items, err := s.One.ListInventions()
	if err != nil {
		return 0
	}

	return len(items)
}

func (s *Service) coreOneLibraryInventory() map[string]any {
	type libraryFile struct {
		Path   string `json:"path"`
		SHA256 string `json:"sha256"`
		Bytes  int    `json:"bytes"`
	}

	files := make([]libraryFile, 0)
	rootLabel := "core-one/libraries/created"

	result := map[string]any{
		"root":                   rootLabel,
		"source_files_observed": 0,
		"files":                  files,
		"source_copied":          false,
		"scan_complete":          false,
		"scan_error_count":       0,
		"inventory_file_limit":   maxLibraryInventoryFiles,
		"inventory_byte_limit":   maxLibraryInventoryBytes,
		"source_file_size_limit": maxLibrarySourceBytes,
	}

	if s == nil || strings.TrimSpace(s.OneRoot) == "" {
		result["note"] = "Core-One root is unavailable; no files were inventoried."
		return result
	}

	root := filepath.Join(s.OneRoot, "libraries", "created")

	// Reject an absent, non-directory, or symbolic-link root before walking.
	if !directoryExists(root) {
		result["scan_complete"] = true
		result["note"] = "No existing Core-One library directory was observed. Candidate artifacts remain separate proposals."
		return result
	}

	var totalBytes int64
	var errorCount int
	limitReached := false

	err := filepath.WalkDir(root, func(
		path string,
		entry os.DirEntry,
		walkErr error,
	) error {
		if walkErr != nil {
			errorCount++
			return nil
		}

		if path == root {
			return nil
		}

		if entry.Type()&os.ModeSymlink != 0 {
			errorCount++
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}

		if entry.IsDir() {
			return nil
		}

		ext := filepath.Ext(entry.Name())
		if ext != ".go" && ext != ".rvx" {
			return nil
		}

		if len(files) >= maxLibraryInventoryFiles {
			limitReached = true
			return filepath.SkipAll
		}

		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			errorCount++
			return nil
		}

		if info.Size() < 0 || info.Size() > maxLibrarySourceBytes {
			errorCount++
			return nil
		}

		if totalBytes+info.Size() > maxLibraryInventoryBytes {
			limitReached = true
			return filepath.SkipAll
		}

		relative, err := filepath.Rel(s.OneRoot, path)
		if err != nil {
			errorCount++
			return nil
		}

		raw, err := readMindFileWithinRoot(
			s.OneRoot,
			relative,
			maxLibrarySourceBytes,
		)
		if err != nil {
			errorCount++
			return nil
		}

		repositoryRelative, err := filepath.Rel(s.RepoRoot, path)
		if err != nil {
			// Keep the repository-relative path shape even when RepoRoot
			// is unavailable; never expose an absolute path in the report.
			repositoryRelative = filepath.Join(
				"core-one",
				"libraries",
				"created",
				filepath.Base(path),
			)
		}

		files = append(files, libraryFile{
			Path:   filepath.ToSlash(repositoryRelative),
			SHA256: hashString(string(raw)),
			Bytes:  len(raw),
		})
		totalBytes += int64(len(raw))

		return nil
	})

	if err != nil {
		errorCount++
	}

	sort.Slice(files, func(i, j int) bool {
		return files[i].Path < files[j].Path
	})

	note := "Existing library sources were inventoried read-only; candidate artifacts remain separate proposals."
	if len(files) == 0 {
		note = "No readable Core-One library source files were inventoried; candidate artifacts remain separate proposals."
	}
	if limitReached {
		note += " Inventory limits were reached; the result is partial."
	}
	if errorCount > 0 {
		note += " One or more filesystem entries could not be safely inventoried."
	}

	result["source_files_observed"] = len(files)
	result["files"] = files
	result["bytes_observed"] = totalBytes
	result["scan_error_count"] = errorCount
	result["scan_complete"] = err == nil && errorCount == 0 && !limitReached
	result["note"] = note

	return result
}

// recentEvents returns a detached snapshot so callers cannot mutate the
// service's event history by changing a returned map or nested slice.
func (s *Service) recentEvents() []map[string]any {
	if s == nil {
		return nil
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	start := 0
	if len(s.events) > 20 {
		start = len(s.events) - 20
	}

	out := make([]map[string]any, 0, len(s.events)-start)
	for _, event := range s.events[start:] {
		if event == nil {
			out = append(out, nil)
			continue
		}

		out = append(out, cloneMindMap(event))
	}

	return out
}

func cloneMindMap(input map[string]any) map[string]any {
	out := make(map[string]any, len(input))

	for key, value := range input {
		out[key] = cloneMindValue(value)
	}

	return out
}

func cloneMindValue(value any) any {
	switch item := value.(type) {
	case map[string]any:
		return cloneMindMap(item)

	case []any:
		out := make([]any, len(item))
		for i, value := range item {
			out[i] = cloneMindValue(value)
		}
		return out

	case []string:
		return append([]string(nil), item...)

	case map[string]string:
		out := make(map[string]string, len(item))
		for key, value := range item {
			out[key] = value
		}
		return out

	case []map[string]any:
		out := make([]map[string]any, len(item))
		for i, value := range item {
			if value != nil {
				out[i] = cloneMindMap(value)
			}
		}
		return out

	default:
		return value
	}
}

func nextEvolutionVersion(root string) (string, error) {
	if !directoryExists(root) {
		return "", fmt.Errorf("evolution directory is missing or unsafe")
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}

	maxPatch := -1

	for _, entry := range entries {
		// ReadDir does not follow symbolic-link directories; still explicitly
		// require a real directory before treating its name as a version.
		if !entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			continue
		}

		name := entry.Name()
		if !strings.HasPrefix(name, "v") {
			continue
		}

		parts := strings.Split(strings.TrimPrefix(name, "v"), ".")
		if len(parts) != 3 || parts[0] != "0" || parts[1] != "1" {
			continue
		}

		if parts[2] == "" {
			continue
		}

		onlyDigits := true
		for _, character := range parts[2] {
			if character < '0' || character > '9' {
				onlyDigits = false
				break
			}
		}
		if !onlyDigits {
			continue
		}

		patch, parseErr := strconv.Atoi(parts[2])
		if parseErr != nil {
			continue
		}

		if patch > maxPatch {
			maxPatch = patch
		}
	}

	maxInt := int(^uint(0) >> 1)
	if maxPatch == maxInt {
		return "", errors.New("evolution patch version space exhausted")
	}

	return fmt.Sprintf("v0.1.%d", maxPatch+1), nil
}

// remoteIsLoopback recognizes literal loopback IP addresses and localhost.
// It deliberately does not resolve arbitrary hostnames using DNS.
func remoteIsLoopback(remote string) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		host = strings.Trim(remote, "[]")
	}

	host = strings.TrimSpace(strings.ToLower(host))
	if host == "localhost" {
		return true
	}

	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}

	return ip.IsLoopback()
}

func subtleConstantTimeEqual(a, b string) bool {
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

func validName(name string) bool {
	if name == "" || len(name) > 64 || name == "." || name == ".." {
		return false
	}

	for _, character := range name {
		if !(
			character >= 'a' && character <= 'z' ||
				character >= '0' && character <= '9' ||
				character == '_' ||
				character == '-',
		) {
			return false
		}
	}

	return true
}

func hashString(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

// fileExists accepts only ordinary, non-symlink files.
func fileExists(path string) bool {
	info, err := os.Lstat(path)
	return err == nil &&
		info.Mode()&os.ModeSymlink == 0 &&
		info.Mode().IsRegular()
}

// directoryExists accepts only ordinary, non-symlink directories.
func directoryExists(path string) bool {
	info, err := os.Lstat(path)
	return err == nil &&
		info.Mode()&os.ModeSymlink == 0 &&
		info.IsDir()
}

// countSourceFiles counts direct child Go/RVX source files, retaining the
// original non-recursive behavior.
func countSourceFiles(root string) int {
	if !directoryExists(root) {
		return 0
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return 0
	}

	count := 0

	for _, entry := range entries {
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			continue
		}

		name := entry.Name()
		if !strings.HasSuffix(name, ".go") &&
			!strings.HasSuffix(name, ".rvx") {
			continue
		}

		info, err := entry.Info()
		if err == nil && info.Mode().IsRegular() {
			count++
		}
	}

	return count
}

// countLogLines returns the number of lines matching the optional case-
// insensitive pipe-delimited filter. The boolean indicates that the complete
// file was read successfully, not that a match was found.
func countLogLines(path, filter string) (int, bool) {
	count := 0
	terms := strings.Split(strings.ToLower(filter), "|")

	_, err := scanMindLines(path, func(line []byte) {
		if filter == "" ||
			containsAny(strings.ToLower(string(line)), terms) {
			count++
		}
	})

	return count, err == nil
}

func containsAny(value string, terms []string) bool {
	for _, term := range terms {
		if term != "" && strings.Contains(value, term) {
			return true
		}
	}

	return false
}

func numberField(obj map[string]any, keys ...string) (float64, bool) {
	for _, key := range keys {
		value, exists := obj[key]
		if !exists {
			continue
		}

		switch number := value.(type) {
		case float64:
			return number, true
		case float32:
			return float64(number), true
		case int:
			return float64(number), true
		case int8:
			return float64(number), true
		case int16:
			return float64(number), true
		case int32:
			return float64(number), true
		case int64:
			return float64(number), true
		case uint:
			return float64(number), true
		case uint8:
			return float64(number), true
		case uint16:
			return float64(number), true
		case uint32:
			return float64(number), true
		case uint64:
			return float64(number), true
		case json.Number:
			parsed, err := number.Float64()
			if err == nil {
				return parsed, true
			}
		}
	}

	return 0, false
}

func average(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}

	// Incremental mean reduces overflow risk compared with summing all values
	// first, and preserves the original empty-input behavior.
	mean := 0.0

	for i, value := range values {
		mean += (value - mean) / float64(i+1)
	}

	return mean
}

func writeJSONFile(path string, value any, mode os.FileMode) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}

	if len(raw)+1 > maxMindWriteBytes {
		return fmt.Errorf(
			"JSON output exceeds maximum permitted size of %d bytes",
			maxMindWriteBytes,
		)
	}

	return atomicWrite(path, append(raw, '\n'), mode)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "no-store")

	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeAPIError(
	w http.ResponseWriter,
	status int,
	code string,
	message string,
) {
	writeJSON(w, status, map[string]string{
		"status":  "error",
		"code":    code,
		"message": message,
	})
}

func decodeJSON(
	w http.ResponseWriter,
	r *http.Request,
	out any,
) error {
	if r == nil || r.Body == nil {
		return errors.New("request body is required")
	}
	if out == nil {
		return errors.New("JSON destination is required")
	}

	defer r.Body.Close()

	reader := http.MaxBytesReader(
		w,
		r.Body,
		maxMindJSONBodyBytes,
	)

	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(out); err != nil {
		return err
	}

	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return errors.New(
				"request body must contain exactly one JSON value",
			)
		}
		return err
	}

	return nil
}

// atomicWrite atomically replaces an ordinary file using a temporary file in
// the same directory. It rejects symlink components and special-file targets.
//
// The directory chain is checked component by component before writing.
// As with other filesystem operations, callers must still account for the
// operating system and deployment model when defending against concurrent
// modifications by a hostile local process.
func atomicWrite(path string, data []byte, mode os.FileMode) error {
	if strings.TrimSpace(path) == "" {
		return errors.New("output path is required")
	}

	if len(data) > maxMindWriteBytes {
		return fmt.Errorf(
			"output exceeds maximum permitted size of %d bytes",
			maxMindWriteBytes,
		)
	}

	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	parent := filepath.Dir(absPath)
	if err := ensureMindOutputDirectory(parent); err != nil {
		return err
	}

	targetInfo, err := os.Lstat(absPath)
	switch {
	case err == nil:
		if targetInfo.Mode()&os.ModeSymlink != 0 ||
			!targetInfo.Mode().IsRegular() {
			return errors.New(
				"atomic-write target must be an ordinary non-symlink file",
			)
		}

	case os.IsNotExist(err):
		// The target is expected to be created by the final rename.

	default:
		return err
	}

	tmp, err := os.CreateTemp(parent, ".mind-tmp-*")
	if err != nil {
		return err
	}

	tmpPath := tmp.Name()
	committed := false

	defer func() {
		_ = tmp.Close()
		if !committed {
			_ = os.Remove(tmpPath)
		}
	}()

	if err := tmp.Chmod(mode.Perm()); err != nil {
		return err
	}

	n, err := tmp.Write(data)
	if err != nil {
		return err
	}
	if n != len(data) {
		return io.ErrShortWrite
	}

	if err := tmp.Sync(); err != nil {
		return err
	}

	if err := tmp.Close(); err != nil {
		return err
	}

	// Recheck the destination just before replacement.
	targetInfo, err = os.Lstat(absPath)
	switch {
	case err == nil:
		if targetInfo.Mode()&os.ModeSymlink != 0 ||
			!targetInfo.Mode().IsRegular() {
			return errors.New(
				"atomic-write target changed to a symlink or special file",
			)
		}

	case os.IsNotExist(err):
		// A missing target is valid.

	default:
		return err
	}

	if err := os.Rename(tmpPath, absPath); err != nil {
		return err
	}
	committed = true

	// Best-effort directory sync improves durability on supported filesystems.
	if dir, err := os.Open(parent); err == nil {
		_ = dir.Sync()
		_ = dir.Close()
	}

	return nil
}

// writeNewFile creates a file exactly once and never replaces an existing
// file. Partial output is removed when a write or sync fails.
func writeNewFile(path string, data []byte, mode os.FileMode) error {
	if strings.TrimSpace(path) == "" {
		return errors.New("output path is required")
	}

	if len(data) > maxMindWriteBytes {
		return fmt.Errorf(
			"output exceeds maximum permitted size of %d bytes",
			maxMindWriteBytes,
		)
	}

	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	parent := filepath.Dir(absPath)
	if err := ensureMindOutputDirectory(parent); err != nil {
		return err
	}

	file, err := os.OpenFile(
		absPath,
		os.O_WRONLY|os.O_CREATE|os.O_EXCL,
		mode.Perm(),
	)
	if err != nil {
		return err
	}

	committed := false
	defer func() {
		_ = file.Close()
		if !committed {
			_ = os.Remove(absPath)
		}
	}()

	if err := file.Chmod(mode.Perm()); err != nil {
		return err
	}

	n, err := file.Write(data)
	if err != nil {
		return err
	}
	if n != len(data) {
		return io.ErrShortWrite
	}

	if err := file.Sync(); err != nil {
		return err
	}

	if err := file.Close(); err != nil {
		return err
	}

	committed = true
	return nil
}

// ensureMindOutputDirectory creates a directory chain without knowingly
// traversing symlink components. Each new component is rechecked after create.
func ensureMindOutputDirectory(path string) error {
	if strings.TrimSpace(path) == "" {
		return errors.New("directory path is required")
	}

	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	volume := filepath.VolumeName(abs)
	root := volume + string(os.PathSeparator)

	if volume == "" {
		root = string(os.PathSeparator)
	}

	currentInfo, err := os.Lstat(root)
	if err != nil {
		return err
	}
	if currentInfo.Mode()&os.ModeSymlink != 0 || !currentInfo.IsDir() {
		return errors.New("filesystem root is not a safe directory")
	}

	remaining := strings.TrimPrefix(abs, root)
	if remaining == "" {
		return nil
	}

	parts := strings.Split(remaining, string(os.PathSeparator))

	for _, part := range parts {
		if part == "" || part == "." {
			continue
		}
		if part == ".." {
			return errors.New("parent traversal is not allowed")
		}

		current := filepath.Join(root, part)

		info, err := os.Lstat(current)
		switch {
		case err == nil:
			if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
				return fmt.Errorf(
					"unsafe output directory component: %s",
					current,
				)
			}

		case os.IsNotExist(err):
			if err := os.Mkdir(current, 0o700); err != nil &&
				!os.IsExist(err) {
				return err
			}

			info, err = os.Lstat(current)
			if err != nil {
				return err
			}
			if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
				return fmt.Errorf(
					"output directory changed during creation: %s",
					current,
				)
			}

		default:
			return err
		}

		root = current
	}

	return nil
}

// countToolEndpointUsage counts telemetry events whose tool_name field matches
// the requested tool. The boolean reports successful reading, not a positive
// count, so a valid zero-usage observation differs from missing evidence.
func countToolEndpointUsage(path, toolName string) (int, bool) {
	count := 0

	_, err := scanMindJSONLines(path, func(line []byte) {
		var event map[string]any
		if json.Unmarshal(line, &event) != nil {
			return
		}

		name, _ := event["tool_name"].(string)
		if name == toolName {
			count++
		}
	})

	return count, err == nil
}

// scanMindJSONLines scans a bounded JSONL file. Malformed JSON lines are
// passed to the callback for caller-specific handling, but filesystem or
// scanner errors make the overall observation unsuccessful.
func scanMindJSONLines(
	path string,
	consume func([]byte),
) (int, error) {
	return scanMindLines(path, consume)
}

func scanMindLines(
	path string,
	consume func([]byte),
) (int, error) {
	file, err := openMindRegularFile(path)
	if err != nil {
		return 0, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	scanner.Buffer(
		make([]byte, 4096),
		maxMindLogLineBytes,
	)

	lines := 0
	var bytesRead int64

	for scanner.Scan() {
		line := scanner.Bytes()
		bytesRead += int64(len(line)) + 1

		if bytesRead > maxMindLogBytes {
			return lines, errors.New("log exceeds maximum scan size")
		}

		lines++

		// The scanner reuses its byte buffer on subsequent Scan calls.
		// Give the callback a detached slice to prevent accidental aliasing.
		detached := append([]byte(nil), line...)
		consume(detached)
	}

	if err := scanner.Err(); err != nil {
		return lines, err
	}

	return lines, nil
}

func openMindRegularFile(path string) (*os.File, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}

	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, errors.New("path is not an ordinary non-symlink file")
	}

	if info.Size() < 0 || info.Size() > maxMindLogBytes {
		return nil, errors.New("file exceeds maximum scan size")
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}

	openedInfo, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, err
	}

	currentInfo, err := os.Lstat(path)
	if err != nil {
		_ = file.Close()
		return nil, err
	}

	if currentInfo.Mode()&os.ModeSymlink != 0 ||
		!currentInfo.Mode().IsRegular() ||
		!os.SameFile(openedInfo, currentInfo) {
		_ = file.Close()
		return nil, errors.New("file changed during safe-open validation")
	}

	return file, nil
}
