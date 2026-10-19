package healer

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode"
	"unicode/utf8"

	"revela-worldwide.local/libs/country"
)

const (
	expectedFailureDBSchema = "usect-zero.worldwide-failure-db.v1"

	maxErrorTextBytes       = 8192
	maxFailureDBBytes       = 4 << 20 // 4 MiB
	maxFailurePatterns      = 20000
	maxMatchesPerPattern    = 128
	maxPatternIDBytes       = 128
	maxPatternCategoryBytes = 128
	maxPatternRiskBytes     = 64
	maxMatchPhraseBytes     = 512
	maxRecommendationBytes  = 8192
)

type Pattern struct {
	ID             string   `json:"id"`
	Category       string   `json:"category"`
	MatchAny       []string `json:"match_any"`
	Recommendation string   `json:"recommendation"`
	Risk           string   `json:"risk"`
}

// failureDB deliberately permits additional top-level fields, such as
// database status, regions, and guardrails, so the shared curated database
// can evolve without breaking this consumer.
//
// Unknown fields are ignored by encoding/json. Pattern fields themselves
// are validated below before any pattern is used.
type failureDB struct {
	Schema   string    `json:"schema"`
	Status   string    `json:"status"`
	Patterns []Pattern `json:"patterns"`
}

type Result struct {
	Country          country.Profile `json:"country_context"`
	Matched          bool            `json:"matched"`
	PatternID        string          `json:"pattern_id,omitempty"`
	Category         string          `json:"category,omitempty"`
	Risk             string          `json:"risk,omitempty"`
	Recommendation   string          `json:"recommendation"`
	AutomaticRepair  bool            `json:"automatic_repair"`
	GuardianRequired bool            `json:"guardian_required"`
	DatabaseStatus   string          `json:"database_status"`
}

// Classify maps diagnostic text to curated advisory patterns.
//
// It never executes a repair, modifies repository files, or grants
// authorization. A matching pattern provides a recommendation only;
// a guardian is always required for any subsequent repair operation.
//
// repositoryRoot must be the repository root containing:
// core-zero/knowledge/worldwide_failure_db/patterns.json
func Classify(
	errorText string,
	countryCode string,
	language string,
	repositoryRoot string,
) (Result, error) {
	if !utf8.ValidString(errorText) {
		return Result{}, errors.New("error_text must be valid UTF-8")
	}

	if strings.TrimSpace(errorText) == "" ||
		len(errorText) > maxErrorTextBytes {
		return Result{}, fmt.Errorf(
			"error_text must contain 1–%d bytes",
			maxErrorTextBytes,
		)
	}

	profile, err := country.Resolve(countryCode, language)
	if err != nil {
		return Result{}, fmt.Errorf("resolve country context: %w", err)
	}

	db, err := loadFailureDB(repositoryRoot)
	if err != nil {
		return Result{}, err
	}

	result := Result{
		Country:          profile,
		Matched:          false,
		Recommendation:   "No curated pattern matched. Collect sanitized diagnostic evidence; do not guess a repair.",
		AutomaticRepair:  false,
		GuardianRequired: true,
		DatabaseStatus:   "loaded_curated_advisory",
	}

	normalizedError := strings.ToLower(errorText)

	// Prefer the most specific matching phrase instead of whichever
	// pattern happens to appear first in the database.
	//
	// Equal-length matches retain database order for deterministic results.
	bestPattern := -1
	bestPhraseLength := 0

	for i := range db.Patterns {
		pattern := &db.Patterns[i]

		for _, phrase := range pattern.MatchAny {
			normalizedPhrase := strings.ToLower(strings.TrimSpace(phrase))
			if normalizedPhrase == "" {
				continue
			}

			if !strings.Contains(normalizedError, normalizedPhrase) {
				continue
			}

			if len(normalizedPhrase) > bestPhraseLength {
				bestPattern = i
				bestPhraseLength = len(normalizedPhrase)
			}
		}
	}

	if bestPattern >= 0 {
		pattern := db.Patterns[bestPattern]

		result.Matched = true
		result.PatternID = pattern.ID
		result.Category = pattern.Category
		result.Risk = pattern.Risk
		result.Recommendation = pattern.Recommendation
	}

	// Keep the safety boundary explicit even if the database is edited.
	result.AutomaticRepair = false
	result.GuardianRequired = true

	return result, nil
}

func loadFailureDB(repositoryRoot string) (failureDB, error) {
	rootInput := strings.TrimSpace(repositoryRoot)
	if rootInput == "" {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}

	absoluteRoot, err := filepath.Abs(rootInput)
	if err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}

	absoluteRoot = filepath.Clean(absoluteRoot)

	// Resolve a symlink supplied as the repository-root argument itself.
	// The database's internal directories and file must not be symlinks.
	realRoot, err := filepath.EvalSymlinks(absoluteRoot)
	if err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}

	rootInfo, err := os.Stat(realRoot)
	if err != nil || !rootInfo.IsDir() {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}

	relativeComponents := []string{
		"core-zero",
		"knowledge",
		"worldwide_failure_db",
		"patterns.json",
	}

	currentPath := realRoot

	for i, component := range relativeComponents {
		currentPath = filepath.Join(currentPath, component)

		info, statErr := os.Lstat(currentPath)
		if statErr != nil {
			return failureDB{}, errors.New(
				"worldwide failure database unavailable; fail closed",
			)
		}

		if info.Mode()&os.ModeSymlink != 0 {
			return failureDB{}, errors.New(
				"worldwide failure database path contains a symlink; fail closed",
			)
		}

		isLast := i == len(relativeComponents)-1

		if !isLast {
			if !info.IsDir() {
				return failureDB{}, errors.New(
					"worldwide failure database path is invalid; fail closed",
				)
			}
			continue
		}

		if !info.Mode().IsRegular() {
			return failureDB{}, errors.New(
				"worldwide failure database must be a regular file; fail closed",
			)
		}

		if info.Size() <= 0 || info.Size() > maxFailureDBBytes {
			return failureDB{}, errors.New(
				"worldwide failure database size is invalid; fail closed",
			)
		}
	}

	// Check resolved path containment as an additional guard against
	// accidental path redirection.
	realDBPath, err := filepath.EvalSymlinks(currentPath)
	if err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}

	if filepath.Clean(realDBPath) != filepath.Clean(currentPath) {
		return failureDB{}, errors.New(
			"worldwide failure database path is redirected; fail closed",
		)
	}

	file, err := os.Open(currentPath)
	if err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database unavailable; fail closed",
		)
	}
	defer file.Close()

	// Recheck the opened file. This also catches a regular-file-to-directory
	// replacement between the earlier path inspection and opening.
	openedInfo, err := file.Stat()
	if err != nil || !openedInfo.Mode().IsRegular() {
		return failureDB{}, errors.New(
			"worldwide failure database file is invalid; fail closed",
		)
	}

	if openedInfo.Size() <= 0 || openedInfo.Size() > maxFailureDBBytes {
		return failureDB{}, errors.New(
			"worldwide failure database size is invalid; fail closed",
		)
	}

	raw, err := io.ReadAll(io.LimitReader(file, maxFailureDBBytes+1))
	if err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database could not be read; fail closed",
		)
	}

	if len(raw) == 0 || len(raw) > maxFailureDBBytes {
		return failureDB{}, errors.New(
			"worldwide failure database size is invalid; fail closed",
		)
	}

	if !utf8.Valid(raw) {
		return failureDB{}, errors.New(
			"worldwide failure database encoding is invalid; fail closed",
		)
	}

	decoder := json.NewDecoder(bytes.NewReader(raw))

	var db failureDB
	if err := decoder.Decode(&db); err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database invalid; fail closed",
		)
	}

	// Reject trailing JSON documents and unexpected trailing values.
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return failureDB{}, errors.New(
			"worldwide failure database contains trailing data; fail closed",
		)
	}

	if db.Schema != "" && db.Schema != expectedFailureDBSchema {
		return failureDB{}, errors.New(
			"worldwide failure database schema is unsupported; fail closed",
		)
	}

	if len(db.Patterns) == 0 || len(db.Patterns) > maxFailurePatterns {
		return failureDB{}, errors.New(
			"worldwide failure database pattern count is invalid; fail closed",
		)
	}

	if err := validateFailurePatterns(db.Patterns); err != nil {
		return failureDB{}, errors.New(
			"worldwide failure database patterns are invalid; fail closed",
		)
	}

	return db, nil
}

func validateFailurePatterns(patterns []Pattern) error {
	seenIDs := make(map[string]struct{}, len(patterns))

	for i, pattern := range patterns {
		if !validPatternField(pattern.ID, maxPatternIDBytes) {
			return fmt.Errorf("pattern %d has an invalid ID", i)
		}

		if !validPatternField(pattern.Category, maxPatternCategoryBytes) {
			return fmt.Errorf("pattern %d has an invalid category", i)
		}

		if !validPatternField(pattern.Risk, maxPatternRiskBytes) {
			return fmt.Errorf("pattern %d has an invalid risk", i)
		}

		if !validPatternField(
			pattern.Recommendation,
			maxRecommendationBytes,
		) {
			return fmt.Errorf("pattern %d has an invalid recommendation", i)
		}

		id := strings.ToLower(strings.TrimSpace(pattern.ID))
		if _, exists := seenIDs[id]; exists {
			return fmt.Errorf("pattern %d has a duplicate ID", i)
		}
		seenIDs[id] = struct{}{}

		if len(pattern.MatchAny) == 0 ||
			len(pattern.MatchAny) > maxMatchesPerPattern {
			return fmt.Errorf("pattern %d has an invalid match_any count", i)
		}

		seenPhrases := make(map[string]struct{}, len(pattern.MatchAny))

		for j, phrase := range pattern.MatchAny {
			phrase = strings.TrimSpace(phrase)

			if !validPatternField(phrase, maxMatchPhraseBytes) {
				return fmt.Errorf(
					"pattern %d match phrase %d is invalid",
					i,
					j,
				)
			}

			normalized := strings.ToLower(phrase)
			if _, exists := seenPhrases[normalized]; exists {
				return fmt.Errorf(
					"pattern %d contains duplicate match phrases",
					i,
				)
			}
			seenPhrases[normalized] = struct{}{}
		}
	}

	return nil
}

func validPatternField(value string, maxBytes int) bool {
	value = strings.TrimSpace(value)

	if value == "" || len(value) > maxBytes || !utf8.ValidString(value) {
		return false
	}

	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}

	return true
}
