package mind

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	maxLearningNoteBytes     = 1200
	minLearningNoteBytes     = 8
	maxLearningEvidenceBytes = 500
	maxLearningRecords       = 100000
	maxLearningLineBytes     = 1 << 20
	maxLearningFileBytes     = 64 << 20
)

var learningAppendMu sync.Mutex

type LearningFeedback struct {
	Version     string    `json:"version"`
	ToolName    string    `json:"tool_name"`
	Mutation    string    `json:"mutation"`
	Outcome     string    `json:"outcome"`
	Note        string    `json:"note"`
	EvidenceRef string    `json:"evidence_ref,omitempty"`
	RecordedAt  time.Time `json:"recorded_at"`
}

type mutationLearning struct {
	Mutation      string  `json:"mutation"`
	Merged        int     `json:"merged"`
	Rejected      int     `json:"rejected"`
	Reverted      int     `json:"reverted"`
	NeedsWork     int     `json:"needs_work"`
	Score         float64 `json:"score"`
	FeedbackCount int     `json:"feedback_count"`
}

type LearningSummary struct {
	Status          string             `json:"status"`
	FeedbackRecords int                `json:"feedback_records"`
	LatestDecisions int                `json:"latest_decisions"`
	Mutations       []mutationLearning `json:"mutations"`
	RankingNote     string             `json:"ranking_note"`
	AutomaticMerge  bool               `json:"automatic_merge"`
}

// RecordFeedback accepts a human's decision about an existing staged
// evolution. It never performs a merge, installs a candidate, or executes
// candidate source code.
//
// Feedback is appended to a protected JSONL history. Malformed existing
// records cause a fail-closed error rather than being silently ignored.
func (s *Service) RecordFeedback(
	feedback LearningFeedback,
) (LearningSummary, error) {
	if s == nil {
		return LearningSummary{}, errors.New("Core-Two service is required")
	}

	s.learningMu.Lock()
	defer s.learningMu.Unlock()

	feedback.Version = strings.TrimSpace(feedback.Version)
	feedback.ToolName = strings.TrimSpace(feedback.ToolName)
	feedback.Mutation = strings.TrimSpace(feedback.Mutation)
	feedback.Outcome = strings.ToLower(strings.TrimSpace(feedback.Outcome))
	feedback.Note = strings.TrimSpace(feedback.Note)
	feedback.EvidenceRef = strings.TrimSpace(feedback.EvidenceRef)

	if !validEvolutionVersion(feedback.Version) {
		return LearningSummary{}, errors.New(
			"version must identify a canonical staged evolution version",
		)
	}

	if !validName(feedback.ToolName) || !safeMindToolName(feedback.ToolName) {
		return LearningSummary{}, errors.New("invalid tool_name")
	}

	if !validName(feedback.Mutation) {
		return LearningSummary{}, errors.New("invalid mutation identifier")
	}

	spec, exists := sourceFor(feedback.Mutation)
	if !exists || !isExactAllowlistedCandidate(spec) {
		return LearningSummary{}, errors.New(
			"mutation is not an exact entry in the static candidate catalog",
		)
	}

	switch feedback.Outcome {
	case "merged", "rejected", "reverted", "needs_work":
	default:
		return LearningSummary{}, errors.New(
			"outcome must be merged, rejected, reverted, or needs_work",
		)
	}

	if !utf8.ValidString(feedback.Note) ||
		len(feedback.Note) < minLearningNoteBytes ||
		len(feedback.Note) > maxLearningNoteBytes {
		return LearningSummary{}, fmt.Errorf(
			"feedback note must be valid UTF-8 and %d–%d bytes",
			minLearningNoteBytes,
			maxLearningNoteBytes,
		)
	}

	if strings.ContainsRune(feedback.Note, '\x00') {
		return LearningSummary{}, errors.New(
			"feedback note must not contain NUL characters",
		)
	}

	if len(feedback.EvidenceRef) > maxLearningEvidenceBytes ||
		!utf8.ValidString(feedback.EvidenceRef) {
		return LearningSummary{}, errors.New(
			"evidence_ref must be valid UTF-8 and no more than 500 bytes",
		)
	}

	if feedback.EvidenceRef != "" {
		if err := validateLearningEvidenceRef(feedback.EvidenceRef); err != nil {
			return LearningSummary{}, fmt.Errorf(
				"invalid evidence_ref: %w",
				err,
			)
		}
	}

	if feedback.Outcome == "merged" && feedback.EvidenceRef == "" {
		return LearningSummary{}, errors.New(
			"merged feedback requires an evidence_ref for the human-reviewed merge record",
		)
	}

	// Validate the staged evidence using the bounded, symlink-aware reader.
	evidenceRelative := filepath.Join(
		"evolutions",
		feedback.Version,
		"evidence.json",
	)

	raw, err := readMindFileWithinRoot(
		s.CoreRoot,
		evidenceRelative,
		maxEvidenceBytes,
	)
	if err != nil {
		return LearningSummary{}, errors.New(
			"evolution evidence is missing, unreadable, or unsafe",
		)
	}

	var evidence map[string]any
	if err := json.Unmarshal(raw, &evidence); err != nil || evidence == nil {
		return LearningSummary{}, errors.New(
			"existing evolution evidence is invalid JSON",
		)
	}

	evidenceVersion, _ := evidence["version"].(string)
	evidenceStatus, _ := evidence["status"].(string)
	evidenceTool, _ := evidence["tool_name"].(string)
	evidenceMutation, _ := evidence["selected_mutation"].(string)

	if evidenceVersion != "" && evidenceVersion != feedback.Version {
		return LearningSummary{}, errors.New(
			"feedback version does not match the staged evidence version",
		)
	}

	if evidenceTool != feedback.ToolName ||
		evidenceMutation != feedback.Mutation {
		return LearningSummary{}, errors.New(
			"feedback does not match the evolution's tool and selected mutation",
		)
	}

	if evidenceStatus != "await_merge" {
		return LearningSummary{}, errors.New(
			"feedback can only be recorded against an evolution awaiting human review",
		)
	}

	records, err := s.readLearningRecordsUnlocked()
	if err != nil {
		return LearningSummary{}, fmt.Errorf(
			"read existing human feedback: %w",
			err,
		)
	}

	if err := validateFeedbackTransition(records, feedback); err != nil {
		return LearningSummary{}, err
	}

	feedback.RecordedAt = time.Now().UTC()

	logPath := filepath.Join(s.CoreRoot, "state", "learning.jsonl")
	if err := appendJSONLine(logPath, feedback); err != nil {
		return LearningSummary{}, fmt.Errorf(
			"append human feedback: %w",
			err,
		)
	}

	return s.learningSummaryUnlocked()
}

func validateFeedbackTransition(
	records []LearningFeedback,
	next LearningFeedback,
) error {
	var previous *LearningFeedback
	mergedPreviously := false

	for i := range records {
		if records[i].Version != next.Version {
			continue
		}

		if records[i].Outcome == "merged" {
			mergedPreviously = true
		}

		if previous == nil ||
			records[i].RecordedAt.After(previous.RecordedAt) ||
			records[i].RecordedAt.Equal(previous.RecordedAt) {
			item := records[i]
			previous = &item
		}
	}

	if previous == nil {
		return nil
	}

	if previous.Outcome == next.Outcome {
		return errors.New(
			"duplicate feedback outcome for this evolution is rejected",
		)
	}

	switch previous.Outcome {
	case "reverted":
		return errors.New(
			"a reverted evolution is terminal; create a new evolution version",
		)

	case "rejected":
		if next.Outcome != "needs_work" {
			return errors.New(
				"a rejected evolution may only be marked needs_work; create a new version for another approval decision",
			)
		}

	case "needs_work":
		// A previously merged evolution may later be marked needs_work and
		// subsequently reverted. An unmerged needs_work decision is terminal.
		if next.Outcome != "reverted" || !mergedPreviously {
			return errors.New(
				"this evolution's needs_work decision requires a new evolution version for further review",
			)
		}

	case "merged":
		if next.Outcome != "reverted" && next.Outcome != "needs_work" {
			return errors.New(
				"after merged feedback, only reverted or needs_work may update the record",
			)
		}

	default:
		return errors.New(
			"existing feedback contains an unsupported outcome; refusing to continue",
		)
	}

	return nil
}

func validateLearningEvidenceRef(value string) error {
	if value == "" {
		return errors.New("reference is empty")
	}

	for _, r := range value {
		if r < 32 || r == 127 {
			return errors.New("reference contains control characters")
		}
	}

	// If the reference is a URI, accept only HTTPS links without credentials,
	// query parameters, or fragments. Those fields can expose tokens.
	if strings.Contains(value, "://") {
		parsed, err := url.Parse(value)
		if err != nil ||
			parsed.Scheme != "https" ||
			parsed.Host == "" ||
			parsed.User != nil ||
			parsed.RawQuery != "" ||
			parsed.Fragment != "" {
			return errors.New(
				"URI references must use HTTPS and contain no credentials, query, or fragment",
			)
		}
		return nil
	}

	// Allow concise identifiers such as PR-123, commit hashes, and relative
	// evidence names; reject path traversal and arbitrary whitespace.
	if strings.TrimSpace(value) != value {
		return errors.New("reference has surrounding whitespace")
	}

	for _, r := range value {
		if !(
			r >= 'a' && r <= 'z' ||
				r >= 'A' && r <= 'Z' ||
				r >= '0' && r <= '9' ||
				r == '-' || r == '_' || r == '.' ||
				r == '/' || r == ':' || r == '#'
		) {
			return errors.New("reference contains unsupported characters")
		}
	}

	for _, part := range strings.Split(
		strings.ReplaceAll(value, "\\", "/"),
		"/",
	) {
		if part == ".." || part == "." {
			return errors.New("relative path traversal is not allowed")
		}
	}

	return nil
}

// readLearningRecords uses the service-level lock so an individual service
// does not observe its own partially updated feedback stream.
func (s *Service) readLearningRecords() ([]LearningFeedback, error) {
	if s == nil {
		return nil, errors.New("service is nil")
	}

	s.learningMu.Lock()
	defer s.learningMu.Unlock()

	return s.readLearningRecordsUnlocked()
}

// readLearningRecordsUnlocked expects the caller to hold the service's
// learningMu. A package-level mutex coordinates append/read operations among
// multiple Service instances within this process.
func (s *Service) readLearningRecordsUnlocked() ([]LearningFeedback, error) {
	learningAppendMu.Lock()
	defer learningAppendMu.Unlock()

	path := filepath.Join(s.CoreRoot, "state", "learning.jsonl")

	file, err := openMindRegularFile(path)
	if os.IsNotExist(err) {
		return []LearningFeedback{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf(
			"learning history is unavailable or unsafe: %w",
			err,
		)
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() > maxLearningFileBytes {
		return nil, errors.New("learning history exceeds the configured size limit")
	}

	// A truncated final line cannot be accepted as a completed feedback record.
	if info.Size() > 0 {
		var finalByte [1]byte
		n, readErr := file.ReadAt(finalByte[:], info.Size()-1)
		if readErr != nil && readErr != io.EOF {
			return nil, readErr
		}
		if n != 1 || finalByte[0] != '\n' {
			return nil, errors.New(
				"learning history has an incomplete final line; manual repair is required",
			)
		}
	}

	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}

	records := make([]LearningFeedback, 0)
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 4096), maxLearningLineBytes)

	for scanner.Scan() {
		if len(records) >= maxLearningRecords {
			return nil, errors.New(
				"learning history exceeds the maximum record count",
			)
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			return nil, errors.New(
				"learning history contains an empty record line",
			)
		}

		var item LearningFeedback
		if err := json.Unmarshal([]byte(line), &item); err != nil {
			return nil, fmt.Errorf(
				"learning history contains an invalid JSON record at line %d",
				len(records)+1,
			)
		}

		if err := validateStoredLearningRecord(item); err != nil {
			return nil, fmt.Errorf(
				"learning history contains an invalid record at line %d: %w",
				len(records)+1,
				err,
			)
		}

		records = append(records, item)
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan learning history: %w", err)
	}

	return records, nil
}

func validateStoredLearningRecord(item LearningFeedback) error {
	if !validEvolutionVersion(item.Version) {
		return errors.New("invalid evolution version")
	}
	if !validName(item.ToolName) || !safeMindToolName(item.ToolName) {
		return errors.New("invalid tool name")
	}
	if !validName(item.Mutation) {
		return errors.New("invalid mutation")
	}

	if _, exists := sourceFor(item.Mutation); !exists {
		return errors.New("unknown mutation")
	}

	switch item.Outcome {
	case "merged", "rejected", "reverted", "needs_work":
	default:
		return errors.New("invalid outcome")
	}

	if !utf8.ValidString(item.Note) ||
		len(item.Note) < minLearningNoteBytes ||
		len(item.Note) > maxLearningNoteBytes {
		return errors.New("invalid note length or encoding")
	}

	if item.RecordedAt.IsZero() {
		return errors.New("recorded_at is missing")
	}

	if item.EvidenceRef != "" {
		if err := validateLearningEvidenceRef(item.EvidenceRef); err != nil {
			return errors.New("invalid evidence reference")
		}
	}

	if item.Outcome == "merged" && item.EvidenceRef == "" {
		return errors.New("merged outcome lacks evidence_ref")
	}

	return nil
}

func (s *Service) learningSummary() (LearningSummary, error) {
	if s == nil {
		return LearningSummary{}, errors.New("service is nil")
	}

	s.learningMu.Lock()
	defer s.learningMu.Unlock()

	return s.learningSummaryUnlocked()
}

// learningSummaryUnlocked expects the caller to hold learningMu.
func (s *Service) learningSummaryUnlocked() (LearningSummary, error) {
	records, err := s.readLearningRecordsUnlocked()
	if err != nil {
		return LearningSummary{}, err
	}

	latestByVersion := make(map[string]LearningFeedback)
	for _, record := range records {
		previous, exists := latestByVersion[record.Version]
		if !exists ||
			record.RecordedAt.After(previous.RecordedAt) ||
			record.RecordedAt.Equal(previous.RecordedAt) {
			latestByVersion[record.Version] = record
		}
	}

	stats := make(map[string]*mutationLearning)

	for _, record := range latestByVersion {
		entry := stats[record.Mutation]
		if entry == nil {
			entry = &mutationLearning{Mutation: record.Mutation}
			stats[record.Mutation] = entry
		}

		switch record.Outcome {
		case "merged":
			entry.Merged++
		case "rejected":
			entry.Rejected++
		case "reverted":
			entry.Reverted++
		case "needs_work":
			entry.NeedsWork++
		}
	}

	out := make([]mutationLearning, 0, len(stats))
	for _, item := range stats {
		item.FeedbackCount = item.Merged +
			item.Rejected +
			item.Reverted +
			item.NeedsWork

		item.Score = float64(
			item.Merged*3 -
				item.Rejected*2 -
				item.Reverted*5 -
				item.NeedsWork,
		)

		out = append(out, *item)
	}

	sort.Slice(out, func(i, j int) bool {
		if out[i].Score == out[j].Score {
			return out[i].Mutation < out[j].Mutation
		}
		return out[i].Score > out[j].Score
	})

	status := "learning_from_human_feedback"
	if len(latestByVersion) == 0 {
		status = "awaiting_human_feedback"
	}

	return LearningSummary{
		Status:          status,
		FeedbackRecords: len(records),
		LatestDecisions: len(latestByVersion),
		Mutations:       out,
		RankingNote: "Scores use the latest recorded decision for each evolution: " +
			"merged +3, rejected -2, reverted -5, needs_work -1. " +
			"Scores are bounded ranking hints only. They cannot override objective matching, " +
			"Guardian decisions, evidence checks, or candidate qualification. " +
			"Feedback does not authorize automatic merge.",
		AutomaticMerge: false,
	}, nil
}

func (s *Service) learningScores() map[string]float64 {
	summary, err := s.learningSummary()
	if err != nil {
		return map[string]float64{}
	}

	out := make(map[string]float64, len(summary.Mutations))
	for _, item := range summary.Mutations {
		score := item.Score

		if score > 15 {
			score = 15
		}
		if score < -25 {
			score = -25
		}

		out[item.Mutation] = score
	}

	return out
}

// selectCandidateWithLearning selects an objective-matched candidate that
// passed qualification. Human-feedback scores are exposed as decision context,
// but do not let an unrelated category replace the requested candidate.
func (s *Service) selectCandidateWithLearning(
	objective string,
	evals []CandidateEvaluation,
) (
	CandidateEvaluation,
	string,
	map[string]float64,
	bool,
) {
	fallback, ok := selectCandidate(objective, evals)
	if !ok {
		return CandidateEvaluation{}, "", map[string]float64{}, false
	}

	scores := s.learningScores()
	score := scores[fallback.ID]

	reason := fmt.Sprintf(
		"Objective-matched candidate %q passed qualification. Human-feedback score %.0f is recorded as ranking context only and does not override objective routing, Guardian checks, or candidate qualification.",
		fallback.ID,
		score,
	)

	return fallback, reason, scores, true
}

func validEvolutionVersion(version string) bool {
	if !strings.HasPrefix(version, "v0.1.") {
		return false
	}

	part := strings.TrimPrefix(version, "v0.1.")
	if part == "" {
		return false
	}

	for _, character := range part {
		if character < '0' || character > '9' {
			return false
		}
	}

	value, err := strconv.Atoi(part)
	if err != nil || value < 0 {
		return false
	}

	// Enforce canonical formatting to avoid multiple names for the same patch.
	return strconv.Itoa(value) == part
}

// appendJSONLine appends one bounded JSON record with a terminating newline.
// It serializes in-process writers and rejects non-regular or symlink log paths.
func appendJSONLine(path string, value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}

	if len(raw)+1 > maxLearningLineBytes {
		return errors.New("JSONL record exceeds the configured line limit")
	}

	line := append(raw, '\n')

	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}

	learningAppendMu.Lock()
	defer learningAppendMu.Unlock()

	parent := filepath.Dir(absPath)
	if err := ensureMindOutputDirectory(parent); err != nil {
		return fmt.Errorf("validate learning log directory: %w", err)
	}

	before, err := os.Lstat(absPath)
	switch {
	case err == nil:
		if before.Mode()&os.ModeSymlink != 0 ||
			!before.Mode().IsRegular() {
			return errors.New("learning log is not an ordinary file")
		}

		if before.Size() < 0 ||
			before.Size()+int64(len(line)) > maxLearningFileBytes {
			return errors.New("learning log would exceed its configured size limit")
		}

	case os.IsNotExist(err):
		// Create exclusively below.

	default:
		return err
	}

	file, err := os.OpenFile(
		absPath,
		os.O_CREATE|os.O_APPEND|os.O_WRONLY,
		0o600,
	)
	if err != nil {
		return err
	}

	committed := false
	defer func() {
		_ = file.Close()
		if !committed {
			// Do not remove a file that existed before this append attempt.
			if os.IsNotExistError(nil) {
				_ = os.Remove(absPath)
			}
		}
	}()

	opened, err := file.Stat()
	if err != nil {
		return err
	}

	current, err := os.Lstat(absPath)
	if err != nil {
		return err
	}
	if current.Mode()&os.ModeSymlink != 0 ||
		!current.Mode().IsRegular() ||
		!os.SameFile(opened, current) {
		return errors.New("learning log changed during safe-open validation")
	}

	if opened.Size() < 0 ||
		opened.Size()+int64(len(line)) > maxLearningFileBytes {
		return errors.New("learning log would exceed its configured size limit")
	}

	if err := file.Chmod(0o600); err != nil {
		return err
	}

	n, err := file.Write(line)
	if err != nil {
		return err
	}
	if n != len(line) {
		return io.ErrShortWrite
	}

	if err := file.Sync(); err != nil {
		return err
	}

	committed = true
	return nil
}
