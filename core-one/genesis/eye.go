package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	maxEyeResearchSources = 200
	maxEyeResearchFindings = 100
	maxEyeResearchFieldBytes = 4000
	maxEyeSourceNameBytes = 200
	maxEyeSourceTitleBytes = 500
	maxEyeSourceURLBytes = 2048

	maxEyeScanFiles = 25000
	maxEyeScanFileBytes int64 = 1 << 20
	maxEyeGapSignals = 30
	maxEyePersistedSourceSnippet = 4000

	eyeTriggerPendingTTL = 60 * time.Minute
)

var (
	workaroundMarker = regexp.MustCompile(
		`(?i)\b(todo|fixme|workaround|temporary|hack)\b[: -]*`,
	)
	gapNonAlphanumeric = regexp.MustCompile(`[^a-z0-9]+`)

	// Serializes trigger-state reads and writes so concurrent Eye scans cannot
	// initiate duplicate proposals for the same key within this process.
	eyeTriggerStateMu sync.Mutex

	topicStopWords = map[string]bool{
		"about": true, "after": true, "again": true, "being": true,
		"build": true, "could": true, "create": true, "first": true,
		"from": true, "have": true, "into": true, "just": true,
		"make": true, "more": true, "most": true, "other": true,
		"over": true, "same": true, "should": true, "since": true,
		"some": true, "such": true, "than": true, "that": true,
		"their": true, "them": true, "then": true, "there": true,
		"these": true, "they": true, "this": true, "those": true,
		"through": true, "tool": true, "tools": true, "using": true,
		"very": true, "when": true, "where": true, "which": true,
		"while": true, "with": true, "work": true, "would": true,
		"system": true, "based": true, "data": true, "project": true,
		"research": true, "technology": true, "result": true,
		"source": true, "github": true, "software": true,
		"repository": true, "kenya": true, "demand": true,
		"emerging": true, "hardware": true, "integration": true,
		"standards": true, "innovation": true, "available": true,
		"recent": true, "search": true, "their": true,
	}
)

type gapSignal struct {
	Signature string `json:"signature"`
	Count     int    `json:"count"`
	Marker    string `json:"marker"`
}

type eyeGapScanStats struct {
	FilesScanned     int   `json:"files_scanned"`
	FilesSkipped     int   `json:"files_skipped"`
	BytesScanned     int64 `json:"bytes_scanned"`
	FilesWithMarkers int   `json:"files_with_markers"`
	UniqueSignatures int   `json:"unique_signatures"`
	FileLimitReached bool  `json:"file_limit_reached"`
}

type eyeTopicCandidate struct {
	Topic   string
	Sources int
}

// EyeScan runs one discovery cycle:
//   - screens and records external research;
//   - fingerprints repeated repository workaround patterns;
//   - identifies recurring themes across distinct research sources;
//   - records evidence before triggering threshold-based proposal generation.
//
// Eye never executes discovered source code, modifies existing inventions, or
// merges/deploys proposals. Triggered inventions must still pass the normal
// Genesis Guardian, validation, and human-review workflow.
func (e *Engine) EyeScan(ctx context.Context) error {
	if e == nil {
		return errors.New("genesis eye: engine is required")
	}

	if ctx == nil {
		ctx = context.Background()
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	e.mu.RLock()
	researcher := e.Researcher
	e.mu.RUnlock()

	if researcher == nil {
		researcher = NewWebResearcher()
	}

	query := strings.TrimSpace(os.Getenv("GENESIS_EYE_RESEARCH_QUERY"))
	if query == "" {
		query = "emerging technology recurring engineering problems software reliability hardware integration accessibility local standards and reusable solutions"
	}
	query = limitText(query, 500)

	if query == "" {
		return errors.New("genesis eye: research query is required")
	}

	if decision := e.Guardian.Check(query); !decision.Allowed {
		_ = e.Guardian.LogBlocked(
			"eye_research_query",
			query,
			decision.Reason,
		)

		e.publish(Event{
			Type:    "eye_scan_blocked",
			At:      time.Now().UTC(),
			Message: "Guardian blocked the research query before external research began.",
			Status:  decision.Code,
		})

		return ErrBlocked
	}

	e.publish(Event{
		Type:    "eye_scan_started",
		At:      time.Now().UTC(),
		Message: "Eye began a bounded research and repository-gap discovery cycle.",
		Status:  "running",
	})

	evidence, err := researcher.Research(ctx, query)
	if err != nil {
		e.publish(Event{
			Type:    "eye_scan_error",
			At:      time.Now().UTC(),
			Message: "Eye research failed before evidence could be processed.",
			Status:  "research_error",
		})

		return fmt.Errorf("genesis eye: research: %w", err)
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	if err := validateAndScreenEyeEvidence(e, &evidence); err != nil {
		e.publish(Event{
			Type:    "eye_scan_blocked",
			At:      time.Now().UTC(),
			Message: "Eye rejected research evidence during validation or Guardian screening.",
			Status:  "evidence_rejected",
		})

		return err
	}

	evidence.Query = query

	if evidence.ID == "" {
		evidence.ID = newID("eye")
	}

	if evidence.CollectedAt.IsZero() {
		evidence.CollectedAt = time.Now().UTC()
	}

	if evidence.Mode == "" {
		evidence.Mode = "unspecified"
	}

	gaps, stats, scanErr := scanRepositoryGapReport(ctx, e.RepoRoot)
	if err := ctx.Err(); err != nil {
		return err
	}

	additionalFindings := make([]string, 0, maxEyeGapSignals+3)

	if scanErr != nil {
		additionalFindings = append(
			additionalFindings,
			"Repository gap scan incomplete: "+limitText(scanErr.Error(), 180),
		)
	}

	additionalFindings = append(
		additionalFindings,
		fmt.Sprintf(
			"Repository scan summary: files_scanned=%d, files_skipped=%d, bytes_scanned=%d, files_with_markers=%d, unique_repeated_signatures=%d, file_limit_reached=%t.",
			stats.FilesScanned,
			stats.FilesSkipped,
			stats.BytesScanned,
			stats.FilesWithMarkers,
			stats.UniqueSignatures,
			stats.FileLimitReached,
		),
	)

	addedSignals := 0

	for i, gap := range gaps {
		if i >= maxEyeGapSignals {
			break
		}

		additionalFindings = append(
			additionalFindings,
			fmt.Sprintf(
				"Local gap signal: marker=%s, distinct_files=%d, signature=%s.",
				gap.Marker,
				gap.Count,
				gap.Signature,
			),
		)

		addedSignals++
	}

	if len(gaps) > addedSignals {
		additionalFindings = append(
			additionalFindings,
			fmt.Sprintf(
				"Repository scan omitted %d lower-ranked gap signatures from the evidence summary because of the configured reporting limit.",
				len(gaps)-addedSignals,
			),
		)
	}

	additionalFindings = append(
		additionalFindings,
		"Eye fingerprints repeated marker text only; a detected signature is a review candidate, not proof of a defect, vulnerability, or required remediation.",
		"Eye does not execute scanned source code or treat external research as verified market demand, legal advice, standards compliance, patent clearance, or engineering approval.",
	)

	if len(evidence.Findings)+len(additionalFindings) > maxEyeResearchFindings {
		return fmt.Errorf(
			"genesis eye: research findings (%d) plus discovery findings (%d) exceed the configured limit of %d",
			len(evidence.Findings),
			len(additionalFindings),
			maxEyeResearchFindings,
		)
	}

	for _, finding := range additionalFindings {
		if len(finding) > maxEyeResearchFieldBytes {
			return errors.New(
				"genesis eye: generated discovery finding exceeded the configured field limit",
			)
		}

		if decision := e.Guardian.Check(finding); !decision.Allowed {
			_ = e.Guardian.LogBlocked(
				"eye_generated_finding",
				finding,
				decision.Reason,
			)

			return ErrBlocked
		}

		evidence.Findings = append(evidence.Findings, finding)
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	// Evidence is persisted before triggering proposals, preserving a record
	// of the discovery cycle even if proposal generation later fails.
	if err := e.saveResearchEvidence(evidence); err != nil {
		return fmt.Errorf("genesis eye: save research evidence: %w", err)
	}

	triggered := 0
	workaroundThreshold := configuredThreshold(
		"GENESIS_WORKAROUND_THRESHOLD",
		6,
	)

	for _, gap := range gaps {
		if err := ctx.Err(); err != nil {
			return err
		}

		if gap.Count < workaroundThreshold {
			continue
		}

		demand := fmt.Sprintf(
			"Create a generic remediation tool for repeated repository workaround signature %s",
			gap.Signature,
		)

		if e.triggerOnce(ctx, "workaround:"+gap.Signature, demand) {
			triggered++
		}

		// Only one repository-gap proposal is attempted per scan, avoiding
		// a burst of inventions from a single repository inspection.
		if triggered > 0 {
			break
		}
	}

	if err := ctx.Err(); err != nil {
		return err
	}

	demandThreshold := configuredThreshold(
		"GENESIS_DEMAND_THRESHOLD",
		5,
	)

	if topic, count := repeatedTopic(evidence.Sources); topic != "" && count >= demandThreshold {
		demand := fmt.Sprintf(
			"Create a reusable tool for emerging cross-source demand theme %s",
			topic,
		)

		if e.triggerOnce(ctx, "demand:"+topic, demand) {
			triggered++
		}
	}

	e.publish(Event{
		Type:    "eye_scan_completed",
		At:      time.Now().UTC(),
		Message: fmt.Sprintf("Eye scan completed: %d source records, %d files inspected, %d repeated workaround signatures, and %d proposals generated.", len(evidence.Sources), stats.FilesScanned, len(gaps), triggered),
		Status:  "ok",
	})

	return nil
}

// validateAndScreenEyeEvidence bounds external data and screens source
// metadata and findings before either is persisted or used for topic discovery.
func validateAndScreenEyeEvidence(
	e *Engine,
	evidence *ResearchEvidence,
) error {
	if e == nil || evidence == nil {
		return errors.New("genesis eye: engine and research evidence are required")
	}

	if len(evidence.Sources) > maxEyeResearchSources {
		return errors.New(
			"genesis eye: research evidence exceeded the configured source limit",
		)
	}

	if len(evidence.Findings) > maxEyeResearchFindings {
		return errors.New(
			"genesis eye: research evidence exceeded the configured finding limit",
		)
	}

	for _, finding := range evidence.Findings {
		if len(finding) > maxEyeResearchFieldBytes {
			return errors.New(
				"genesis eye: research finding exceeded the configured field limit",
			)
		}

		if decision := e.Guardian.Check(finding); !decision.Allowed {
			_ = e.Guardian.LogBlocked(
				"eye_research_finding",
				finding,
				decision.Reason,
			)

			return ErrBlocked
		}
	}

	for _, source := range evidence.Sources {
		if len(source.Name) > maxEyeSourceNameBytes ||
			len(source.URL) > maxEyeSourceURLBytes ||
			len(source.Title) > maxEyeSourceTitleBytes ||
			len(source.Snippet) > maxEyePersistedSourceSnippet {
			return errors.New(
				"genesis eye: research source exceeded a configured field limit",
			)
		}

		sourceText := strings.Join(
			[]string{
				source.Name,
				source.Title,
				source.Snippet,
				source.URL,
			},
			" ",
		)

		if decision := e.Guardian.Check(sourceText); !decision.Allowed {
			_ = e.Guardian.LogBlocked(
				"eye_research_source",
				source.URL+" "+source.Title+" "+source.Snippet,
				decision.Reason,
			)

			e.publish(Event{
				Type:    "eye_source_blocked",
				At:      time.Now().UTC(),
				Message: "Guardian rejected a research source before persistence or demand analysis.",
				Status:  decision.Code,
			})

			return ErrBlocked
		}
	}

	return nil
}

// triggerOnce persistently deduplicates automatic invention triggers.
//
// The state file supports legacy key-to-invention entries as well as temporary
// reservations. A pending reservation expires after a bounded interval so an
// interrupted process does not permanently suppress a future retry.
func (e *Engine) triggerOnce(
	ctx context.Context,
	key string,
	demand string,
) bool {
	if e == nil || strings.TrimSpace(e.CoreRoot) == "" {
		return false
	}

	if ctx == nil {
		ctx = context.Background()
	}

	if strings.TrimSpace(key) == "" || strings.TrimSpace(demand) == "" {
		return false
	}

	if err := ctx.Err(); err != nil {
		return false
	}

	eyeTriggerStateMu.Lock()
	defer eyeTriggerStateMu.Unlock()

	statePath := filepath.Join(
		e.CoreRoot,
		"state",
		"eye",
		"triggered.json",
	)

	seen := make(map[string]string)

	raw, err := os.ReadFile(statePath)
	if err == nil {
		if decodeErr := json.Unmarshal(raw, &seen); decodeErr != nil {
			// Fail closed: malformed state must not silently reset deduplication.
			return false
		}
	} else if !os.IsNotExist(err) {
		return false
	}

	if seen == nil {
		seen = make(map[string]string)
	}

	if previous, exists := seen[key]; exists {
		if isExpiredEyeReservation(previous, time.Now().UTC()) {
			delete(seen, key)
		} else {
			return false
		}
	}

	if err := ctx.Err(); err != nil {
		return false
	}

	reservation := "pending:" + time.Now().UTC().Format(time.RFC3339Nano)
	seen[key] = reservation

	if err := writeJSON(statePath, seen); err != nil {
		return false
	}

	countryCode := strings.TrimSpace(os.Getenv("GENESIS_EYE_COUNTRY"))
	if countryCode == "" {
		countryCode = "KE"
	}

	language := strings.TrimSpace(os.Getenv("GENESIS_EYE_LANGUAGE"))
	if language == "" {
		language = "en"
	}

	invention, err := e.InventWorldwide(
		ctx,
		demand,
		countryCode,
		language,
	)
	if err != nil {
		delete(seen, key)
		_ = writeJSON(statePath, seen)
		return false
	}

	seen[key] = invention.Name
	stateErr := writeJSON(statePath, seen)

	message := "A discovery threshold created a reviewable invention proposal; human review and explicit merge remain required."
	status := "await_merge"

	if stateErr != nil {
		// Keep the in-memory state reserved. On disk the pending entry remains
		// and expires later if it cannot be replaced by the completed record.
		message += " Persistent completion tracking failed; the on-disk reservation will expire if not repaired."
		status = "tracking_warning"
	}

	e.publish(Event{
		Type:      "eye_auto_invention",
		At:        time.Now().UTC(),
		Message:   message,
		Invention: invention.Name,
		Status:    status,
	})

	return true
}

func isExpiredEyeReservation(value string, now time.Time) bool {
	if !strings.HasPrefix(value, "pending:") {
		// Legacy entries hold an invention name and remain deduplicated.
		return false
	}

	rawTime := strings.TrimPrefix(value, "pending:")
	createdAt, err := time.Parse(time.RFC3339Nano, rawTime)
	if err != nil {
		// Invalid reservations are not considered completed inventions.
		return true
	}

	return now.Sub(createdAt) >= eyeTriggerPendingTTL
}

// configuredThreshold reads a positive bounded integer from the environment.
func configuredThreshold(env string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(env))
	if raw == "" {
		return fallback
	}

	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 || n > 1000 {
		return fallback
	}

	return n
}

// scanRepositoryGaps preserves the original helper signature for callers that
// only need repeated gap signals and an error.
func scanRepositoryGaps(repoRoot string) ([]gapSignal, error) {
	gaps, _, err := scanRepositoryGapReport(context.Background(), repoRoot)
	return gaps, err
}

// scanRepositoryGapReport fingerprints repeated markers across a bounded
// repository walk. Counts represent distinct files, not repeated lines in one
// file, which reduces false positives caused by a single noisy source file.
//
// It never executes source code and does not persist source-line contents.
func scanRepositoryGapReport(
	ctx context.Context,
	repoRoot string,
) ([]gapSignal, eyeGapScanStats, error) {
	stats := eyeGapScanStats{}

	if ctx == nil {
		ctx = context.Background()
	}

	if strings.TrimSpace(repoRoot) == "" {
		return nil, stats, errors.New("repository root is required")
	}

	root, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, stats, fmt.Errorf("resolve repository root: %w", err)
	}

	rootInfo, err := os.Stat(root)
	if err != nil {
		return nil, stats, fmt.Errorf("inspect repository root: %w", err)
	}

	if !rootInfo.IsDir() {
		return nil, stats, errors.New("repository root must be a directory")
	}

	counts := make(map[string]int)
	markerBySignature := make(map[string]string)

	var firstErr error

	walkErr := filepath.WalkDir(root, func(
		path string,
		entry fs.DirEntry,
		walkErr error,
	) error {
		if ctxErr := ctx.Err(); ctxErr != nil {
			return ctxErr
		}

		if walkErr != nil {
			stats.FilesSkipped++

			if firstErr == nil {
				firstErr = walkErr
			}

			return nil
		}

		if entry.IsDir() {
			if shouldSkipEyeDirectory(root, path, entry.Name()) {
				return filepath.SkipDir
			}

			return nil
		}

		// Do not follow symlinked files out of the repository.
		if entry.Type()&fs.ModeSymlink != 0 {
			stats.FilesSkipped++
			return nil
		}

		if !isTextSource(path) {
			return nil
		}

		if stats.FilesScanned >= maxEyeScanFiles {
			stats.FileLimitReached = true
			return fs.SkipAll
		}

		stats.FilesScanned++

		info, err := entry.Info()
		if err != nil {
			stats.FilesSkipped++

			if firstErr == nil {
				firstErr = err
			}

			return nil
		}

		if info.Size() < 0 || info.Size() > maxEyeScanFileBytes {
			stats.FilesSkipped++
			return nil
		}

		raw, err := os.ReadFile(path)
		if err != nil {
			stats.FilesSkipped++

			if firstErr == nil {
				firstErr = err
			}

			return nil
		}

		stats.BytesScanned += int64(len(raw))

		// A signature is counted at most once per file. The marker itself is
		// retained as a label; only a hash of the normalized phrase is stored.
		fileSignatures := make(map[string]string)

		for _, line := range strings.Split(string(raw), "\n") {
			match := workaroundMarker.FindStringSubmatchIndex(line)
			if match == nil || len(match) < 4 {
				continue
			}

			phrase := normalizeGapPhrase(line[match[1]:])
			if len(phrase) < 12 {
				continue
			}

			phrase = limitText(phrase, 120)
			if len(phrase) < 12 {
				continue
			}

			signature := sha256String(phrase)[:12]
			marker := strings.ToLower(
				strings.TrimSpace(line[match[2]:match[3]]),
			)

			if _, exists := fileSignatures[signature]; !exists {
				fileSignatures[signature] = marker
			}
		}

		if len(fileSignatures) > 0 {
			stats.FilesWithMarkers++
		}

		for signature, marker := range fileSignatures {
			counts[signature]++

			if _, exists := markerBySignature[signature]; !exists {
				markerBySignature[signature] = marker
			}
		}

		return nil
	})

	if walkErr != nil {
		if ctxErr := ctx.Err(); ctxErr != nil {
			return nil, stats, ctxErr
		}

		if !errors.Is(walkErr, fs.SkipAll) && firstErr == nil {
			firstErr = walkErr
		}
	}

	gaps := make([]gapSignal, 0, len(counts))

	for signature, count := range counts {
		// Repetition means at least two distinct files contain the same
		// normalized marker phrase.
		if count < 2 {
			continue
		}

		gaps = append(gaps, gapSignal{
			Signature: signature,
			Count:     count,
			Marker:    markerBySignature[signature],
		})
	}

	sort.Slice(gaps, func(i, j int) bool {
		if gaps[i].Count == gaps[j].Count {
			return gaps[i].Signature < gaps[j].Signature
		}

		return gaps[i].Count > gaps[j].Count
	})

	stats.UniqueSignatures = len(gaps)

	return gaps, stats, firstErr
}

func shouldSkipEyeDirectory(root, path, base string) bool {
	switch base {
	case ".git", "node_modules", "vendor", "dist", "build",
		".venv", "venv", ".next", ".cache", "coverage", "target":
		return true
	}

	if strings.HasPrefix(base, ".staging-") {
		return true
	}

	relative, err := filepath.Rel(root, path)
	if err != nil {
		return false
	}

	relative = filepath.ToSlash(relative)

	// Skip Genesis-generated data but continue inspecting Genesis source
	// files, so Eye can discover patterns within Core One's own code.
	switch relative {
	case "core-one/inventions",
		"core-one/research",
		"core-one/state",
		"core-one/libraries/created",
		"core-one/models":
		return true
	}

	return false
}

func normalizeGapPhrase(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = gapNonAlphanumeric.ReplaceAllString(value, " ")
	return strings.Join(strings.Fields(value), " ")
}

func isTextSource(path string) bool {
	ext := strings.ToLower(filepath.Ext(path))

	switch ext {
	case ".go", ".py", ".js", ".jsx", ".ts", ".tsx",
		".md", ".json", ".yaml", ".yml", ".toml",
		".rs", ".java", ".sh", ".sql", ".html",
		".css", ".txt", ".tf", ".c", ".h", ".cpp", ".xml":
		return true
	}

	return false
}

// repeatedTopic discovers recurring words and adjacent keyword pairs across
// distinct retrieved sources. It returns a deterministic, human-readable
// topic and the number of distinct source records supporting that topic.
func repeatedTopic(sources []ResearchSource) (string, int) {
	candidates := make(map[string]map[string]struct{})

	for _, source := range sources {
		if source.Status != "retrieved" {
			continue
		}

		if strings.TrimSpace(source.Title) == "" &&
			strings.TrimSpace(source.Snippet) == "" {
			continue
		}

		sourceID := canonicalEyeSourceID(source)
		if sourceID == "" {
			continue
		}

		text := strings.ToLower(source.Title + " " + source.Snippet)

		tokens := strings.FieldsFunc(text, func(r rune) bool {
			return !(
				(r >= 'a' && r <= 'z') ||
					(r >= '0' && r <= '9')
			)
		})

		sourceTopics := make(map[string]struct{})

		for i, token := range tokens {
			if len(token) >= 5 && !topicStopWords[token] {
				sourceTopics[token] = struct{}{}
			}

			if i+1 >= len(tokens) {
				continue
			}

			next := tokens[i+1]

			if len(token) < 4 ||
				len(next) < 4 ||
				topicStopWords[token] ||
				topicStopWords[next] {
				continue
			}

			sourceTopics[token+" "+next] = struct{}{}
		}

		for topic := range sourceTopics {
			if candidates[topic] == nil {
				candidates[topic] = make(map[string]struct{})
			}

			candidates[topic][sourceID] = struct{}{}
		}
	}

	ranked := make([]eyeTopicCandidate, 0, len(candidates))

	for topic, sourceSet := range candidates {
		ranked = append(ranked, eyeTopicCandidate{
			Topic:   topic,
			Sources: len(sourceSet),
		})
	}

	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].Sources != ranked[j].Sources {
			return ranked[i].Sources > ranked[j].Sources
		}

		wordsI := len(strings.Fields(ranked[i].Topic))
		wordsJ := len(strings.Fields(ranked[j].Topic))

		if wordsI != wordsJ {
			return wordsI > wordsJ
		}

		return ranked[i].Topic < ranked[j].Topic
	})

	if len(ranked) == 0 {
		return "", 0
	}

	return ranked[0].Topic, ranked[0].Sources
}

func canonicalEyeSourceID(source ResearchSource) string {
	rawURL := strings.TrimSpace(source.URL)

	if rawURL != "" {
		parsed, err := url.Parse(rawURL)
		if err == nil && parsed.Host != "" {
			scheme := strings.ToLower(parsed.Scheme)
			host := strings.ToLower(parsed.Hostname())

			if port := parsed.Port(); port != "" {
				host += ":" + port
			}

			path := strings.TrimRight(parsed.EscapedPath(), "/")
			if path == "" {
				path = "/"
			}

			return scheme + "://" + host + path
		}
	}

	name := strings.ToLower(
		strings.Join(strings.Fields(source.Name), " "),
	)

	if name != "" {
		return "name:" + name
	}

	fingerprint := strings.ToLower(
		strings.TrimSpace(source.Title) + "\x00" +
			strings.TrimSpace(source.Snippet),
	)

	if fingerprint == "\x00" {
		return ""
	}

	return "record:" + sha256String(fingerprint)
}
