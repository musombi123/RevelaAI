package mind

import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	maxMirrorBytesPerSource int64 = 4 << 20
	maxMirrorEventsPerSource      = 2000
	maxMirrorCursorBytes    int64 = 2 << 20
	maxMirrorCursorSources        = 3
	maxMirrorCursorCounts         = 32
	maxMirrorHealthBodyBytes      = 4096
	maxMirrorHealthTimeout        = 900 * time.Millisecond
	maxMirrorFingerprintPrefix    = 4096
	maxMirrorFingerprintTail      = 256
)

type mirrorCursorStore struct {
	SchemaVersion int                           `json:"schema_version,omitempty"`
	Sources       map[string]mirrorSourceCursor `json:"sources"`
}

type mirrorSourceCursor struct {
	Offset         int64            `json:"offset"`
	ObservedSize   int64            `json:"observed_size,omitempty"`
	TotalRecords   int64            `json:"total_records"`
	Counts         map[string]int64 `json:"event_counts"`
	LastObservedAt time.Time        `json:"last_observed_at"`
	Recent         []map[string]any `json:"recent_summaries"`
	PrefixSHA256   string           `json:"prefix_sha256,omitempty"`
	TailSHA256     string           `json:"tail_sha256,omitempty"`
}

type mirrorSourceStatus struct {
	Path               string           `json:"path"`
	Available          bool             `json:"available"`
	Bytes              int64            `json:"bytes"`
	Offset             int64            `json:"offset"`
	NewRecords         int              `json:"new_records"`
	TotalRecords       int64            `json:"total_records"`
	EventCounts        map[string]int64 `json:"event_counts"`
	ContinuityVerified bool             `json:"continuity_verified"`
	Warning            string           `json:"warning,omitempty"`
	Error              string           `json:"error,omitempty"`
}

type healthProbe struct {
	Service    string  `json:"service"`
	URL        string  `json:"url,omitempty"`
	Reachable  bool    `json:"reachable"`
	StatusCode int     `json:"status_code,omitempty"`
	LatencyMS  float64 `json:"latency_ms,omitempty"`
	Error      string  `json:"error,omitempty"`
}

type mirrorSource struct {
	root     string
	relative string
	key      string
}

type mirrorFingerprints struct {
	PrefixSHA256 string
	TailSHA256   string
}

// observeMirror incrementally reads approved Core-One and Core-Zero JSONL
// sources. It never executes source code or exposes raw log lines.
//
// A cursor advances only after complete lines have been parsed and the
// consumed bytes and source identity have been checked. Legacy cursors lacking
// fingerprints are supported but explicitly marked as unverified.
func (s *Service) observeMirror(ctx context.Context) (map[string]any, error) {
	if s == nil {
		return nil, errors.New("mirror service is required")
	}
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if !directoryExists(s.CoreRoot) {
		return nil, errors.New("Core-Two root is missing or unsafe")
	}

	s.mirrorMu.Lock()
	defer s.mirrorMu.Unlock()

	cursorRelative := filepath.Join("state", "mirror-cursor.json")
	cursorPath := filepath.Join(s.CoreRoot, cursorRelative)

	sources := []mirrorSource{
		{
			root:     s.ZeroRoot,
			relative: filepath.Join("audit_log", "events.jsonl"),
			key:      "core-zero/audit_log/events.jsonl",
		},
		{
			root:     s.OneRoot,
			relative: filepath.Join("state", "events", "events.jsonl"),
			key:      "core-one/state/events/events.jsonl",
		},
		{
			root:     s.OneRoot,
			relative: filepath.Join("guardian", "blocked.log"),
			key:      "core-one/guardian/blocked.log",
		},
	}

	store := mirrorCursorStore{
		SchemaVersion: 1,
		Sources:       make(map[string]mirrorSourceCursor, len(sources)),
	}

	rawCursor, cursorErr := readMindFileWithinRoot(
		s.CoreRoot,
		cursorRelative,
		maxMirrorCursorBytes,
	)

	switch {
	case cursorErr == nil:
		if err := json.Unmarshal(rawCursor, &store); err != nil {
			return nil, errors.New(
				"saved mirror cursor is invalid JSON; refusing to overwrite it",
			)
		}
		if store.SchemaVersion != 0 && store.SchemaVersion != 1 {
			return nil, fmt.Errorf(
				"unsupported mirror cursor schema version %d",
				store.SchemaVersion,
			)
		}
		if store.Sources == nil {
			store.Sources = make(map[string]mirrorSourceCursor)
		}

	case os.IsNotExist(cursorErr):
		// First observation starts from the beginning of each available source.

	default:
		return nil, fmt.Errorf("read mirror cursor safely: %w", cursorErr)
	}

	allowedKeys := make(map[string]bool, len(sources))
	for _, source := range sources {
		allowedKeys[source.key] = true
	}
	if len(store.Sources) > maxMirrorCursorSources {
		return nil, errors.New(
			"mirror cursor contains more sources than the current schema permits",
		)
	}

	for key, cursor := range store.Sources {
		if !allowedKeys[key] {
			return nil, fmt.Errorf(
				"mirror cursor contains an unrecognized source %q",
				key,
			)
		}
		if err := validateMirrorCursor(cursor); err != nil {
			return nil, fmt.Errorf("invalid cursor for %q: %w", key, err)
		}
		store.Sources[key] = sanitizeMirrorCursor(key, cursor)
	}

	statuses := make([]mirrorSourceStatus, 0, len(sources))

	for _, source := range sources {
		if err := ctx.Err(); err != nil {
			return nil, err
		}

		cursor, exists := store.Sources[source.key]
		if !exists {
			cursor = newMirrorCursor()
		}

		status := mirrorSourceStatus{
			Path:         source.key,
			EventCounts:  cloneMirrorCounts(cursor.Counts),
			TotalRecords: cursor.TotalRecords,
			Offset:       cursor.Offset,
		}

		absPath, initialInfo, err := mirrorSourceInfo(
			source.root,
			source.relative,
		)

		if os.IsNotExist(err) {
			// Missing evidence is unavailable, not proof of zero events.
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}
		if err != nil {
			status.Error = "source is unavailable or failed safe-path validation"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		status.Available = true
		status.Bytes = initialInfo.Size()

		if initialInfo.Size() < 0 {
			status.Error = "source has an invalid size"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		// Detect shrinkage even when the saved offset would still fit within
		// the shorter file. Do not silently reset and recount the log.
		if cursor.ObservedSize > 0 && initialInfo.Size() < cursor.ObservedSize {
			status.Error = "source was truncated below its previously observed size; manual review is required"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		if cursor.Offset < 0 || cursor.Offset > initialInfo.Size() {
			status.Error = "source length is inconsistent with the saved cursor; manual review is required"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		file, openedInfo, err := openMirrorSource(
			source.root,
			source.relative,
		)
		if err != nil {
			status.Error = "source could not be safely opened"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		working := cloneMirrorCursor(cursor)
		currentFingerprint, err := calculateMirrorFingerprints(
			file,
			cursor.Offset,
		)
		if err != nil {
			_ = file.Close()
			status.Error = "could not validate source continuity"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		switch {
		case cursor.Offset == 0:
			status.ContinuityVerified = true

		case cursor.PrefixSHA256 == "" || cursor.TailSHA256 == "":
			status.Warning = "legacy cursor lacks source fingerprints; previously consumed bytes cannot be verified"
			status.ContinuityVerified = false

		case cursor.PrefixSHA256 != currentFingerprint.PrefixSHA256 ||
			cursor.TailSHA256 != currentFingerprint.TailSHA256:
			_ = file.Close()
			status.Error = "source content before the saved cursor changed; cursor retained for manual review"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue

		default:
			status.ContinuityVerified = true
		}

		availableBytes := initialInfo.Size() - cursor.Offset
		readLimit := availableBytes
		if readLimit > maxMirrorBytesPerSource {
			readLimit = maxMirrorBytesPerSource
		}

		chunk := make([]byte, int(readLimit))
		if len(chunk) > 0 {
			n, readErr := file.ReadAt(chunk, cursor.Offset)
			if readErr != nil && readErr != io.EOF {
				_ = file.Close()
				status.Error = "source segment could not be read"
				statuses = append(statuses, status)
				store.Sources[source.key] = cursor
				continue
			}
			chunk = chunk[:n]
		}

		lastNL := bytes.LastIndexByte(chunk, '\n')

		if lastNL < 0 {
			// No complete record is available. Keep the byte offset unchanged.
			if availableBytes > int64(len(chunk)) {
				status.Error = "no newline found within the per-source byte limit; cursor not advanced"
			} else if len(chunk) > 0 {
				status.Warning = appendMirrorWarning(
					status.Warning,
					"no complete newline-terminated record is available; cursor unchanged",
				)
			}

			if err := verifyMirrorFileStillSame(
				source.root,
				source.relative,
				absPath,
				openedInfo,
			); err != nil {
				status.Error = "source identity changed during observation"
				_ = file.Close()
				statuses = append(statuses, status)
				store.Sources[source.key] = cursor
				continue
			}

			// Fingerprints are computed while the file remains open. This
			// avoids the closed-file bug in the previous version.
			working.PrefixSHA256 = currentFingerprint.PrefixSHA256
			working.TailSHA256 = currentFingerprint.TailSHA256
			working.LastObservedAt = time.Now().UTC()

			fileInfo, statErr := file.Stat()
			if statErr == nil {
				working.ObservedSize = fileInfo.Size()
			}

			_ = file.Close()

			if statErr != nil {
				status.Error = "could not update observed source size"
				store.Sources[source.key] = cursor
			} else {
				store.Sources[source.key] = working
			}

			status.Offset = store.Sources[source.key].Offset
			status.TotalRecords = store.Sources[source.key].TotalRecords
			status.EventCounts = cloneMirrorCounts(store.Sources[source.key].Counts)
			statuses = append(statuses, status)
			continue
		}

		complete := chunk[:lastNL+1]
		newCount := 0
		scanner := bufio.NewScanner(bytes.NewReader(complete))
		scanner.Buffer(make([]byte, 4096), 1<<20)

		scanFailed := false
		for scanner.Scan() {
			if err := ctx.Err(); err != nil {
				_ = file.Close()
				return nil, err
			}

			line := bytes.TrimSpace(scanner.Bytes())
			if len(line) == 0 {
				continue
			}

			var event map[string]any
			if json.Unmarshal(line, &event) != nil || event == nil {
				working.Counts["unparsed_record"]++
				working.TotalRecords++
				newCount++
				continue
			}

			kind := normalizeMirrorEventType(
				firstString(event, "type", "event", "action", "event_type"),
			)

			if _, exists := working.Counts[kind]; !exists &&
				len(working.Counts) >= maxMirrorCursorCounts {
				kind = "other"
			}

			working.Counts[kind]++
			working.TotalRecords++
			newCount++

			working.Recent = append(working.Recent, map[string]any{
				"source":      source.key,
				"type":        kind,
				"at":          normalizeMirrorTimestamp(firstString(event, "at", "created_at", "timestamp", "time")),
				"status":      normalizeMirrorStatus(firstString(event, "status", "result")),
				"observed_at": time.Now().UTC().Format(time.RFC3339Nano),
			})

			if len(working.Recent) > maxMirrorEventsPerSource {
				working.Recent = append(
					[]map[string]any(nil),
					working.Recent[len(working.Recent)-maxMirrorEventsPerSource:]...,
				)
			}
		}

		if scanner.Err() != nil {
			scanFailed = true
		}

		if scanFailed {
			_ = file.Close()
			status.Error = "a JSONL record exceeds the permitted line limit; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		newOffset := cursor.Offset + int64(lastNL+1)

		// Verify that the exact bytes parsed are still present before accepting
		// the new counts and moving the cursor.
		if err := verifyMirrorFileStillSame(
			source.root,
			source.relative,
			absPath,
			openedInfo,
		); err != nil {
			_ = file.Close()
			status.Error = "source identity changed during observation; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		if err := verifyMirrorSegment(file, cursor.Offset, complete); err != nil {
			_ = file.Close()
			status.Error = "consumed source bytes changed during observation; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		fp, err := calculateMirrorFingerprints(file, newOffset)
		if err != nil {
			_ = file.Close()
			status.Error = "could not calculate updated source fingerprints; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		fileInfo, statErr := file.Stat()
		if statErr != nil {
			_ = file.Close()
			status.Error = "could not record source size; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		if fileInfo.Size() < newOffset {
			_ = file.Close()
			status.Error = "source was truncated during observation; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		_ = file.Close()

		working.Offset = newOffset
		working.ObservedSize = fileInfo.Size()
		working.PrefixSHA256 = fp.PrefixSHA256
		working.TailSHA256 = fp.TailSHA256
		working.LastObservedAt = time.Now().UTC()

		store.Sources[source.key] = working

		status.Offset = working.Offset
		status.NewRecords = newCount
		status.TotalRecords = working.TotalRecords
		status.EventCounts = cloneMirrorCounts(working.Counts)
		statuses = append(statuses, status)
	}

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	// Always rebuild the recent view from persisted, sanitized cursors. This
	// ensures a request with no new records still reports recent past events.
	recent := make([]map[string]any, 0, maxMirrorCursorSources*maxMirrorEventsPerSource)
	for _, source := range sources {
		cursor, ok := store.Sources[source.key]
		if !ok {
			continue
		}
		recent = append(recent, cloneMirrorSummaries(cursor.Recent)...)
	}

	sort.SliceStable(recent, func(i, j int) bool {
		return mirrorSummaryObservedAt(recent[i]).Before(
			mirrorSummaryObservedAt(recent[j]),
		)
	})

	if len(recent) > 40 {
		recent = recent[len(recent)-40:]
	}

	store.SchemaVersion = 1
	if err := writeJSONFile(cursorPath, store, 0o600); err != nil {
		return nil, fmt.Errorf("persist mirror cursor safely: %w", err)
	}

	zeroBase := envOr("USECT_ZERO_BASE_URL", "http://127.0.0.1:8780")
	oneBase := envOr("GENESIS_BASE_URL", "http://127.0.0.1:8781")

	zeroHealth := probeHealth(ctx, "Core-Zero", zeroBase, "/v1/health")
	oneHealth := probeHealth(ctx, "Core-One", oneBase, "/v1/genesis/health")

	healingDir := filepath.Join(s.ZeroRoot, "evidence", "heal")
	healCount, lastHeal, healComplete := countRecentFilesDetailed(
		healingDir,
		1000,
	)

	return map[string]any{
		"observed_at":           time.Now().UTC(),
		"mode":                  "read_only_incremental_log_mirror",
		"sources":               statuses,
		"recent_event_summaries": recent,
		"core_zero_health":      zeroHealth,
		"core_one_health":       oneHealth,
		"core_zero_heal_evidence": map[string]any{
			"directory":          "core-zero/evidence/heal",
			"available":          directoryExists(healingDir),
			"file_count":         healCount,
			"latest_modified_at": lastHeal,
			"scan_complete":      healComplete,
		},
		"source_code_executed":    false,
		"raw_log_content_exposed": false,
		"cursor_path":             "core-two/state/mirror-cursor.json",
		"notes": []string{
			"Core-One and Core-Zero logs are consumed incrementally. Missing or unreadable logs are not treated as proof of zero events.",
			"Only complete newline-terminated records are consumed. Malformed JSON records are counted as unparsed without exposing raw content.",
			"Source-size tracking and fingerprints detect common truncation and rewrite cases. A detected inconsistency blocks consumption pending review.",
			"Fingerprint checks cover a bounded prefix and tail, not every previously consumed byte; they are a continuity check, not a tamper-proof audit chain.",
			"Legacy cursors without fingerprints are accepted with a warning because earlier source bytes cannot be independently verified.",
			"Recent summaries use a normalized allowlist and are rebuilt from the saved cursor on every observation.",
			"Health probes use fixed paths, bounded timeouts, and reject redirects. Non-loopback upstreams require HTTPS.",
			"The mirror reads at most 4 MiB per source per pass and advances only through complete records.",
			"Application-level checks do not replace operating-system isolation against a hostile local process.",
		},
	}, nil
}

func newMirrorCursor() mirrorSourceCursor {
	return mirrorSourceCursor{
		Counts: make(map[string]int64),
		Recent: make([]map[string]any, 0),
	}
}

func validateMirrorCursor(cursor mirrorSourceCursor) error {
	if cursor.Offset < 0 {
		return errors.New("negative byte offset")
	}
	if cursor.ObservedSize < 0 {
		return errors.New("negative observed file size")
	}
	if cursor.TotalRecords < 0 {
		return errors.New("negative total record count")
	}
	if cursor.ObservedSize > 0 && cursor.Offset > cursor.ObservedSize {
		return errors.New("offset exceeds recorded observed file size")
	}
	if len(cursor.Counts) > maxMirrorCursorCounts {
		return errors.New("too many event-count categories")
	}
	if len(cursor.Recent) > maxMirrorEventsPerSource {
		return errors.New("too many recent summaries")
	}
	for _, count := range cursor.Counts {
		if count < 0 {
			return errors.New("negative event count")
		}
	}
	for _, fingerprint := range []string{
		cursor.PrefixSHA256,
		cursor.TailSHA256,
	} {
		if fingerprint == "" {
			continue
		}
		if len(fingerprint) != 64 {
			return errors.New("invalid SHA-256 fingerprint length")
		}
		if _, err := hex.DecodeString(fingerprint); err != nil {
			return errors.New("invalid SHA-256 fingerprint encoding")
		}
	}
	return nil
}

func sanitizeMirrorCursor(
	sourceKey string,
	cursor mirrorSourceCursor,
) mirrorSourceCursor {
	out := cloneMirrorCursor(cursor)
	counts := make(map[string]int64)

	for category, count := range out.Counts {
		if count < 0 {
			continue
		}

		category = normalizeMirrorEventType(category)
		counts[category] += count
	}

	if len(counts) > maxMirrorCursorCounts {
		capped := make(map[string]int64, maxMirrorCursorCounts)
		for category, count := range counts {
			if len(capped) >= maxMirrorCursorCounts-1 {
				break
			}
			capped[category] = count
		}
		capped["other"] += counts["other"]
		counts = capped
	}

	out.Counts = counts
	out.Recent = sanitizeMirrorSummaries(sourceKey, out.Recent)
	return out
}

func cloneMirrorCursor(input mirrorSourceCursor) mirrorSourceCursor {
	out := input
	out.Counts = cloneMirrorCounts(input.Counts)
	out.Recent = cloneMirrorSummaries(input.Recent)
	return out
}

func cloneMirrorCounts(input map[string]int64) map[string]int64 {
	out := make(map[string]int64, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}

func cloneMirrorSummaries(input []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(input))

	for _, summary := range input {
		out = append(out, map[string]any{
			"source":      normalizeMirrorSourceLabel(firstString(summary, "source")),
			"type":        normalizeMirrorEventType(firstString(summary, "type")),
			"at":          normalizeMirrorTimestamp(firstString(summary, "at")),
			"status":      normalizeMirrorStatus(firstString(summary, "status")),
			"observed_at": normalizeMirrorTimestamp(firstString(summary, "observed_at")),
		})
	}

	return out
}

func sanitizeMirrorSummaries(
	sourceKey string,
	input []map[string]any,
) []map[string]any {
	if len(input) > maxMirrorEventsPerSource {
		input = input[len(input)-maxMirrorEventsPerSource:]
	}

	out := make([]map[string]any, 0, len(input))
	for _, summary := range input {
		out = append(out, map[string]any{
			"source":      sourceKey,
			"type":        normalizeMirrorEventType(firstString(summary, "type")),
			"at":          normalizeMirrorTimestamp(firstString(summary, "at")),
			"status":      normalizeMirrorStatus(firstString(summary, "status")),
			"observed_at": normalizeMirrorTimestamp(firstString(summary, "observed_at")),
		})
	}
	return out
}

func mirrorSummaryObservedAt(summary map[string]any) time.Time {
	raw := firstString(summary, "observed_at")
	if raw == "" {
		return time.Time{}
	}
	value, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return time.Time{}
	}
	return value
}

func mirrorSourceInfo(root, relative string) (string, os.FileInfo, error) {
	path, info, err := mindPathWithinRoot(root, relative)
	if err != nil {
		return "", nil, err
	}
	if !info.Mode().IsRegular() {
		return "", nil, errors.New("mirror source is not a regular file")
	}
	return path, info, nil
}

func openMirrorSource(root, relative string) (*os.File, os.FileInfo, error) {
	path, before, err := mirrorSourceInfo(root, relative)
	if err != nil {
		return nil, nil, err
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}

	opened, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, nil, err
	}

	current, err := os.Lstat(path)
	if err != nil {
		_ = file.Close()
		return nil, nil, err
	}

	if current.Mode()&os.ModeSymlink != 0 ||
		!current.Mode().IsRegular() ||
		!os.SameFile(opened, current) ||
		!os.SameFile(before, current) {
		_ = file.Close()
		return nil, nil, errors.New("mirror source changed during safe open")
	}

	return file, opened, nil
}

func verifyMirrorFileStillSame(
	root, relative, path string,
	openedInfo os.FileInfo,
) error {
	if openedInfo == nil {
		return errors.New("opened source identity is unavailable")
	}

	currentPath, currentInfo, err := mirrorSourceInfo(root, relative)
	if err != nil {
		return err
	}

	if filepath.Clean(currentPath) != filepath.Clean(path) ||
		!os.SameFile(openedInfo, currentInfo) {
		return errors.New("mirror source path now refers to a different file")
	}

	return nil
}

func verifyMirrorSegment(file *os.File, offset int64, expected []byte) error {
	if file == nil || offset < 0 {
		return errors.New("invalid source segment")
	}

	actual := make([]byte, len(expected))
	if len(actual) == 0 {
		return nil
	}

	n, err := file.ReadAt(actual, offset)
	if err != nil && err != io.EOF {
		return err
	}
	if n != len(expected) {
		return io.ErrUnexpectedEOF
	}
	if !bytes.Equal(actual, expected) {
		return errors.New("source segment changed after reading")
	}

	return nil
}

// calculateMirrorFingerprints hashes a bounded file prefix and the bytes
// immediately preceding the current cursor offset. These are sampled
// continuity fingerprints, not a complete hash of all previously consumed data.
func calculateMirrorFingerprints(
	file *os.File,
	offset int64,
) (mirrorFingerprints, error) {
	var result mirrorFingerprints

	if file == nil || offset < 0 {
		return result, errors.New("invalid file or byte offset")
	}

	info, err := file.Stat()
	if err != nil {
		return result, err
	}
	if offset > info.Size() {
		return result, errors.New("offset exceeds current file size")
	}

	prefixLength := minMirrorInt64(
		int64(maxMirrorFingerprintPrefix),
		offset,
	)
	prefix := make([]byte, int(prefixLength))

	if len(prefix) > 0 {
		n, readErr := file.ReadAt(prefix, 0)
		if readErr != nil && readErr != io.EOF {
			return result, readErr
		}
		if n != len(prefix) {
			return result, io.ErrUnexpectedEOF
		}
	}

	tailLength := minMirrorInt64(
		int64(maxMirrorFingerprintTail),
		offset,
	)
	tail := make([]byte, int(tailLength))

	if len(tail) > 0 {
		start := offset - tailLength
		n, readErr := file.ReadAt(tail, start)
		if readErr != nil && readErr != io.EOF {
			return result, readErr
		}
		if n != len(tail) {
			return result, io.ErrUnexpectedEOF
		}
	}

	result.PrefixSHA256 = hashString(string(prefix))
	result.TailSHA256 = hashString(string(tail))

	return result, nil
}

func minMirrorInt64(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}

func normalizeMirrorEventType(raw string) string {
	value := strings.ToLower(strings.TrimSpace(raw))
	value = strings.ReplaceAll(value, "-", "_")
	value = strings.ReplaceAll(value, " ", "_")

	switch value {
	case "http_request", "endpoint_access", "endpoint_used",
		"guardian_blocked", "blocked", "security_block",
		"heal", "healing", "recovery", "restore",
		"proposal", "proposed", "tested", "await_merge",
		"approved", "rejected", "accepted", "denied",
		"error", "warning", "success", "failure",
		"audit", "audit_event", "unparsed_record", "record":
		return value
	default:
		return "other"
	}
}

func normalizeMirrorStatus(raw string) string {
	value := strings.ToLower(strings.TrimSpace(raw))

	switch value {
	case "ok", "success", "passed", "complete", "completed",
		"accepted", "approved", "pending", "await_merge",
		"blocked", "rejected", "denied", "error", "failed",
		"timeout", "unavailable", "degraded":
		return value
	default:
		return ""
	}
}

func normalizeMirrorTimestamp(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" || len(raw) > 80 {
		return ""
	}

	parsed, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return ""
	}

	return parsed.UTC().Format(time.RFC3339Nano)
}

func normalizeMirrorSourceLabel(source string) string {
	switch source {
	case "core-zero/audit_log/events.jsonl",
		"core-one/state/events/events.jsonl",
		"core-one/guardian/blocked.log":
		return source
	default:
		return ""
	}
}

func appendMirrorWarning(existing, addition string) string {
	if existing == "" {
		return addition
	}
	return existing + "; " + addition
}

func probeHealth(
	ctx context.Context,
	name string,
	base string,
	endpointPath string,
) healthProbe {
	result := healthProbe{Service: name}

	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		result.Error = "health probe context is cancelled"
		return result
	}

	if endpointPath != "/v1/health" &&
		endpointPath != "/v1/genesis/health" {
		result.Error = "unsupported health endpoint"
		return result
	}

	normalized, err := normalizeCoreBase(base)
	if err != nil {
		result.Error = "invalid upstream URL or private-network policy"
		return result
	}

	parsed, err := url.Parse(normalized)
	if err != nil ||
		parsed == nil ||
		parsed.Host == "" ||
		parsed.User != nil ||
		parsed.RawQuery != "" ||
		parsed.Fragment != "" ||
		parsed.Opaque != "" {
		result.Error = "invalid upstream URL"
		return result
	}

	if parsed.Path != "" && parsed.Path != "/" {
		result.Error = "upstream base URL must not contain a custom path"
		return result
	}

	hostname := strings.TrimSuffix(
		strings.ToLower(parsed.Hostname()),
		".",
	)

	loopback := hostname == "localhost"
	if ip := net.ParseIP(hostname); ip != nil && ip.IsLoopback() {
		loopback = true
	}

	if parsed.Scheme != "https" &&
		!(parsed.Scheme == "http" && loopback) {
		result.Error = "non-loopback health endpoints require HTTPS"
		return result
	}

	parsed.Path = endpointPath
	parsed.RawPath = ""
	parsed.RawQuery = ""
	parsed.Fragment = ""

	result.URL = parsed.Scheme + "://" + parsed.Host + parsed.EscapedPath()

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		parsed.String(),
		nil,
	)
	if err != nil {
		result.Error = "could not create health request"
		return result
	}

	client := &http.Client{
		Timeout: maxMirrorHealthTimeout,
		CheckRedirect: func(
			_ *http.Request,
			_ []*http.Request,
		) error {
			return http.ErrUseLastResponse
		},
	}

	start := time.Now()
	response, err := client.Do(request)
	result.LatencyMS = float64(time.Since(start).Microseconds()) / 1000

	if err != nil {
		result.Error = "upstream unreachable or health request failed"
		return result
	}
	defer response.Body.Close()

	result.StatusCode = response.StatusCode
	result.Reachable = response.StatusCode >= 200 &&
		response.StatusCode < 300

	_, _ = io.CopyN(
		io.Discard,
		response.Body,
		maxMirrorHealthBodyBytes,
	)

	if !result.Reachable {
		result.Error = "upstream returned a non-success status"
	}

	return result
}

func countRecentFiles(root string, capFiles int) (int, any) {
	count, latest, _ := countRecentFilesDetailed(root, capFiles)
	return count, latest
}

func countRecentFilesDetailed(
	root string,
	capFiles int,
) (int, any, bool) {
	if capFiles <= 0 {
		capFiles = 1000
	}
	if !directoryExists(root) {
		return 0, nil, false
	}

	count := 0
	var latest time.Time
	complete := true

	err := filepath.WalkDir(root, func(
		path string,
		entry os.DirEntry,
		walkErr error,
	) error {
		if walkErr != nil {
			complete = false
			return nil
		}

		if path == root {
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			complete = false
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.IsDir() {
			return nil
		}

		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			complete = false
			return nil
		}

		count++
		if info.ModTime().After(latest) {
			latest = info.ModTime()
		}
		if count >= capFiles {
			complete = false
			return filepath.SkipAll
		}

		return nil
	})

	if err != nil {
		complete = false
	}
	if latest.IsZero() {
		return count, nil, complete
	}

	return count, latest.UTC(), complete
}

func firstString(obj map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := obj[key].(string); ok {
			value = strings.TrimSpace(value)
			if value != "" {
				return value
			}
		}
	}
	return ""
}

func limitLabel(value string, maximum int) string {
	value = strings.TrimSpace(value)
	if maximum <= 0 {
		return ""
	}
	if len(value) <= maximum {
		return value
	}

	value = value[:maximum]
	for !utf8.ValidString(value) && len(value) > 0 {
		value = value[:len(value)-1]
	}

	return value
}

func countParsedLines(chunk []byte) int {
	scanner := bufio.NewScanner(bytes.NewReader(chunk))
	scanner.Buffer(make([]byte, 4096), 1<<20)

	count := 0
	for scanner.Scan() {
		if strings.TrimSpace(scanner.Text()) != "" {
			count++
		}
	}

	return count
}

func envOr(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}
