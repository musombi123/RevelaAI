package mind

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
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
	SchemaVersion int                               `json:"schema_version,omitempty"`
	Sources       map[string]mirrorSourceCursor     `json:"sources"`
}

type mirrorSourceCursor struct {
	Offset            int64             `json:"offset"`
	TotalRecords      int64             `json:"total_records"`
	Counts            map[string]int64  `json:"event_counts"`
	LastObservedAt    time.Time         `json:"last_observed_at"`
	Recent            []map[string]any  `json:"recent_summaries"`
	PrefixSHA256      string            `json:"prefix_sha256,omitempty"`
	TailSHA256        string            `json:"tail_sha256,omitempty"`
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

// observeMirror consumes append-only Core-One/Core-Zero evidence using saved
// byte offsets. It never executes source, reads arbitrary upstream URLs, or
// returns raw log lines. Each source is advanced only through complete,
// successfully parsed newline-terminated records.
func (s *Service) observeMirror(ctx context.Context) (map[string]any, error) {
	if s == nil {
		return nil, errors.New("mirror service is required")
	}

	if ctx == nil {
		ctx = context.Background()
	}

	s.mirrorMu.Lock()
	defer s.mirrorMu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

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
		// First observation: start from the beginning of each available log.

	default:
		return nil, fmt.Errorf(
			"read mirror cursor safely: %w",
			cursorErr,
		)
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
			return nil, fmt.Errorf(
				"invalid cursor for %q: %w",
				key,
				err,
			)
		}

		store.Sources[key] = sanitizeMirrorCursor(key, cursor)
	}

	statuses := make([]mirrorSourceStatus, 0, len(sources))
	recent := make([]map[string]any, 0, maxMirrorCursorSources*maxMirrorEventsPerSource)

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

		absPath, info, err := mirrorSourceInfo(source.root, source.relative)
		if os.IsNotExist(err) {
			// An absent log is unavailable evidence, not proof of zero events.
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		if err != nil {
			status.Error = "source file is unavailable or failed safe-path validation"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		status.Available = true
		status.Bytes = info.Size()

		if info.Size() < 0 {
			status.Error = "source has an invalid size"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		if cursor.Offset < 0 || cursor.Offset > info.Size() {
			status.Error = "source length is inconsistent with the saved cursor; manual cursor reset is required"
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

		continuityVerified := false
		workingCursor := cloneMirrorCursor(cursor)

		currentFingerprint, fpErr := calculateMirrorFingerprints(
			file,
			cursor.Offset,
		)
		if fpErr != nil {
			_ = file.Close()
			status.Error = "could not validate source continuity"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		switch {
		case cursor.Offset == 0:
			continuityVerified = true

		case cursor.PrefixSHA256 == "" || cursor.TailSHA256 == "":
			// Backward-compatible initialization for cursors created before
			// fingerprints existed. Past content cannot be proven unchanged.
			status.Warning = "legacy cursor has no complete source fingerprints; current bytes were adopted as a continuity baseline"

		case cursor.PrefixSHA256 != currentFingerprint.PrefixSHA256 ||
			cursor.TailSHA256 != currentFingerprint.TailSHA256:
			_ = file.Close()
			status.Error = "source content before the saved cursor has changed; cursor retained and manual review is required"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue

		default:
			continuityVerified = true
		}

		// Restrict this pass to the file size observed before reading. Bytes
		// appended concurrently will be consumed on a later observation.
		availableBytes := info.Size() - cursor.Offset
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

		// Process only complete lines. A partially written final line remains
		// pending and is not parsed or counted yet.
		lastNL := bytes.LastIndexByte(chunk, '\n')

		if lastNL < 0 {
			if availableBytes > int64(len(chunk)) {
				status.Error = "no newline found within the source byte limit; cursor not advanced"
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
			}

			_ = file.Close()

			if status.Error == "" {
				fp, e := calculateMirrorFingerprints(file, cursor.Offset)
				if e == nil {
					workingCursor.PrefixSHA256 = fp.PrefixSHA256
					workingCursor.TailSHA256 = fp.TailSHA256
					workingCursor.LastObservedAt = time.Now().UTC()
					store.Sources[source.key] = workingCursor
				} else {
					status.Error = "could not update source continuity fingerprints"
					store.Sources[source.key] = cursor
				}
			} else {
				store.Sources[source.key] = cursor
			}

			status.Offset = store.Sources[source.key].Offset
			status.TotalRecords = store.Sources[source.key].TotalRecords
			status.EventCounts = cloneMirrorCounts(store.Sources[source.key].Counts)
			status.ContinuityVerified = continuityVerified
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

			// Work on a detached cursor. A scanner or read failure must never
			// partially commit event counts while leaving the old byte offset.
			var event map[string]any
			if json.Unmarshal(line, &event) != nil || event == nil {
				workingCursor.Counts["unparsed_record"]++
				workingCursor.TotalRecords++
				newCount++
				continue
			}

			kind := normalizeMirrorEventType(
				firstString(event, "type", "event", "action", "event_type"),
			)

			if _, exists := workingCursor.Counts[kind]; !exists &&
				len(workingCursor.Counts) >= maxMirrorCursorCounts {
				kind = "other"
			}

			workingCursor.Counts[kind]++
			workingCursor.TotalRecords++
			newCount++

			summary := map[string]any{
				"source":      source.key,
				"type":        kind,
				"at":          normalizeMirrorTimestamp(firstString(event, "at", "created_at", "timestamp", "time")),
				"status":      normalizeMirrorStatus(firstString(event, "status", "result")),
				"observed_at": time.Now().UTC(),
			}

			workingCursor.Recent = append(
				workingCursor.Recent,
				summary,
			)

			if len(workingCursor.Recent) > maxMirrorEventsPerSource {
				workingCursor.Recent = append(
					[]map[string]any(nil),
					workingCursor.Recent[len(workingCursor.Recent)-maxMirrorEventsPerSource:]...,
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
		workingCursor.Offset = newOffset
		workingCursor.LastObservedAt = time.Now().UTC()

		// A path replaced or truncated during the scan is not committed.
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

		fp, err := calculateMirrorFingerprints(file, newOffset)
		if err != nil {
			_ = file.Close()
			status.Error = "could not calculate updated source fingerprints; cursor retained"
			statuses = append(statuses, status)
			store.Sources[source.key] = cursor
			continue
		}

		_ = file.Close()

		workingCursor.PrefixSHA256 = fp.PrefixSHA256
		workingCursor.TailSHA256 = fp.TailSHA256

		store.Sources[source.key] = workingCursor

		status.Offset = workingCursor.Offset
		status.NewRecords = newCount
		status.TotalRecords = workingCursor.TotalRecords
		status.EventCounts = cloneMirrorCounts(workingCursor.Counts)
		status.ContinuityVerified = continuityVerified

		statuses = append(statuses, status)
		recent = append(recent, cloneMirrorSummaries(workingCursor.Recent)...)
	}

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	store.SchemaVersion = 1

	if err := writeJSONFile(cursorPath, store, 0o600); err != nil {
		return nil, fmt.Errorf("persist mirror cursor safely: %w", err)
	}

	if len(recent) > 40 {
		recent = recent[len(recent)-40:]
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
		"observed_at": time.Now().UTC(),
		"mode":        "read_only_incremental_log_mirror",
		"sources":     statuses,
		"recent_event_summaries": recent,

		"core_zero_health": zeroHealth,
		"core_one_health":  oneHealth,

		"core_zero_heal_evidence": map[string]any{
			"directory":          "core-zero/evidence/heal",
			"available":          directoryExists(healingDir),
			"file_count":         healCount,
			"latest_modified_at": lastHeal,
			"scan_complete":      healComplete,
		},

		"source_code_executed":   false,
		"raw_log_content_exposed": false,
		"cursor_path":            "core-two/state/mirror-cursor.json",

		"notes": []string{
			"Core-Zero and Core-One logs are consumed incrementally. Unavailable, unreadable, or inconsistent logs are not treated as evidence of zero events.",
			"Only newline-terminated records that fit the configured line limit are consumed. A malformed JSON record is counted as unparsed without exposing its raw content.",
			"Cursor fingerprints detect many forms of source truncation or rewriting. A mismatch blocks further consumption until the source or cursor is reviewed.",
			"Legacy cursors without fingerprints receive a warning because their previously consumed bytes cannot be independently verified.",
			"Recent summaries contain normalized event categories and statuses, not raw log lines or arbitrary input fields.",
			"Health probes use fixed endpoint paths, disable redirects, have a bounded timeout, and do not expose response bodies.",
			"The mirror reads at most 4 MiB per source per pass and advances only through complete records.",
			"These controls are application-level safeguards, not a substitute for operating-system isolation against a hostile local process.",
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
	if cursor.TotalRecords < 0 {
		return errors.New("negative total record count")
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
		if counts[category] > int64(^uint64(0)>>1)-count {
			counts[category] = int64(^uint64(0) >> 1)
			continue
		}
		counts[category] += count
	}

	if len(counts) > maxMirrorCursorCounts {
		// All categories are normalized to a small, predefined vocabulary,
		// but retain a defensive cap in case that vocabulary changes.
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
		copy := map[string]any{
			"source": normalizeMirrorSourceLabel(firstString(summary, "source")),
			"type":   normalizeMirrorEventType(firstString(summary, "type")),
			"at":     normalizeMirrorTimestamp(firstString(summary, "at")),
			"status": normalizeMirrorStatus(firstString(summary, "status")),
		}

		if observed, ok := summary["observed_at"].(string); ok {
			copy["observed_at"] = normalizeMirrorTimestamp(observed)
		} else if observed, ok := summary["observed_at"].(time.Time); ok {
			copy["observed_at"] = observed.UTC()
		}

		out = append(out, copy)
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
		// Old cursor summaries may contain arbitrary values. Rebuild every
		// summary from the narrow allowlist instead of returning persisted data.
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

func mirrorSourceInfo(
	root string,
	relative string,
) (string, os.FileInfo, error) {
	path, info, err := mindPathWithinRoot(root, relative)
	if err != nil {
		return "", nil, err
	}
	if !info.Mode().IsRegular() {
		return "", nil, errors.New("mirror source is not a regular file")
	}
	return path, info, nil
}

func openMirrorSource(
	root string,
	relative string,
) (*os.File, os.FileInfo, error) {
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
	root string,
	relative string,
	path string,
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

func calculateMirrorFingerprints(
	file *os.File,
	offset int64,
) (mirrorFingerprints, error) {
	result := mirrorFingerprints{}

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

	prefixLength := int64(maxMirrorFingerprintPrefix)
	if offset < prefixLength {
		prefixLength = offset
	}

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

	tailLength := int64(maxMirrorFingerprintTail)
	if offset < tailLength {
		tailLength = offset
	}

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

	// Do not include credentials, query parameters, arbitrary request paths,
	// or response bodies in the health-probe result.
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
			request *http.Request,
			via []*http.Request,
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

	// Consume only a small bounded amount. The body is never returned or logged.
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
