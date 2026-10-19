package knowledge

import (
	"bytes"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
)

const (
	worldwideFailureSchemaVersion = "usect-zero.worldwide-failure-db.v1"
	worldwideFailureStatus        = "curated_advisory_patterns_not_exhaustive"

	maxWorldwidePatterns = 10000
)

// worldwideFiles embeds the curated advisory database into the binary.
// The database does not require a runtime network connection.
//
//go:embed worldwide_failure_db/patterns.json
var worldwideFiles embed.FS

// FailurePattern represents one advisory diagnostic pattern.
//
// A pattern match is not proof of root cause and does not authorize execution
// of a repair, shell command, deployment, database mutation or hardware action.
type FailurePattern struct {
	ID             string   `json:"id"`
	Category       string   `json:"category"`
	MatchAny       []string `json:"match_any"`
	Recommendation string   `json:"recommendation"`
	Risk           string   `json:"risk"`
}

// FailureDatabase is the validated worldwide failure knowledge base.
type FailureDatabase struct {
	SchemaVersion string           `json:"schema_version"`
	Status        string           `json:"status"`
	Regions       []string         `json:"regions"`
	Patterns      []FailurePattern `json:"patterns"`
	Guardrails    []string         `json:"guardrails"`
}

var (
	worldwideOnce sync.Once
	worldwideDB   FailureDatabase
	worldwideErr  error
)

// WorldwideFailureDatabase returns the complete validated embedded database.
//
// The returned value is a deep copy. Callers may modify its slices without
// changing the cached database used by other components.
//
// The result is cached after the first load because the embedded file is
// immutable for the lifetime of the running binary.
func WorldwideFailureDatabase() (FailureDatabase, error) {
	worldwideOnce.Do(loadWorldwideFailureDatabase)

	if worldwideErr != nil {
		return FailureDatabase{}, worldwideErr
	}

	return cloneFailureDatabase(worldwideDB), nil
}

// WorldwideFailurePatterns preserves the original API for existing callers.
// It returns validated patterns with independently owned slices.
func WorldwideFailurePatterns() ([]FailurePattern, error) {
	db, err := WorldwideFailureDatabase()
	if err != nil {
		return nil, err
	}

	return db.Patterns, nil
}

func loadWorldwideFailureDatabase() {
	raw, err := worldwideFiles.ReadFile("worldwide_failure_db/patterns.json")
	if err != nil {
		worldwideErr = fmt.Errorf("read embedded worldwide failure database: %w", err)
		return
	}

	if len(bytes.TrimSpace(raw)) == 0 {
		worldwideErr = errors.New("embedded worldwide failure database is empty")
		return
	}

	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()

	var db FailureDatabase
	if err := decoder.Decode(&db); err != nil {
		worldwideErr = fmt.Errorf("decode embedded worldwide failure database: %w", err)
		return
	}

	// Reject multiple JSON values or trailing malformed data.
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			worldwideErr = errors.New(
				"embedded worldwide failure database must contain exactly one JSON value",
			)
			return
		}

		worldwideErr = fmt.Errorf(
			"invalid trailing data in embedded worldwide failure database: %w",
			err,
		)
		return
	}

	if err := validateFailureDatabase(db); err != nil {
		worldwideErr = fmt.Errorf("embedded worldwide failure database validation failed: %w", err)
		return
	}

	worldwideDB = cloneFailureDatabase(db)
}

// validateFailureDatabase verifies structural integrity before patterns become
// available to diagnostic callers.
func validateFailureDatabase(db FailureDatabase) error {
	if db.SchemaVersion != worldwideFailureSchemaVersion {
		return fmt.Errorf(
			"unsupported schema_version %q; expected %q",
			db.SchemaVersion,
			worldwideFailureSchemaVersion,
		)
	}

	if db.Status != worldwideFailureStatus {
		return fmt.Errorf(
			"unsupported database status %q; expected %q",
			db.Status,
			worldwideFailureStatus,
		)
	}

	if len(db.Regions) == 0 {
		return errors.New("regions must contain at least one entry")
	}

	if len(db.Patterns) == 0 {
		return errors.New("patterns must contain at least one entry")
	}

	if len(db.Patterns) > maxWorldwidePatterns {
		return fmt.Errorf(
			"pattern count %d exceeds maximum %d",
			len(db.Patterns),
			maxWorldwidePatterns,
		)
	}

	if len(db.Guardrails) == 0 {
		return errors.New("guardrails must contain at least one entry")
	}

	if err := validateUniqueTextList("regions", db.Regions); err != nil {
		return err
	}

	if err := validateUniqueTextList("guardrails", db.Guardrails); err != nil {
		return err
	}

	seenIDs := make(map[string]struct{}, len(db.Patterns))

	for i, pattern := range db.Patterns {
		prefix := fmt.Sprintf("patterns[%d]", i)

		if !validIdentifier(pattern.ID) {
			return fmt.Errorf(
				"%s has invalid id %q; use lowercase letters, digits, underscores or hyphens",
				prefix,
				pattern.ID,
			)
		}

		if _, exists := seenIDs[pattern.ID]; exists {
			return fmt.Errorf("%s duplicates pattern id %q", prefix, pattern.ID)
		}
		seenIDs[pattern.ID] = struct{}{}

		if !validIdentifier(pattern.Category) {
			return fmt.Errorf("%s has invalid category %q", prefix, pattern.Category)
		}

		switch pattern.Risk {
		case "low", "medium", "high", "critical":
			// Accepted risk levels.
		default:
			return fmt.Errorf(
				"%s has unsupported risk %q; expected low, medium, high or critical",
				prefix,
				pattern.Risk,
			)
		}

		if strings.TrimSpace(pattern.Recommendation) == "" {
			return fmt.Errorf("%s has an empty recommendation", prefix)
		}

		if len(pattern.MatchAny) == 0 {
			return fmt.Errorf("%s must contain at least one match_any phrase", prefix)
		}

		seenPhrases := make(map[string]struct{}, len(pattern.MatchAny))

		for j, phrase := range pattern.MatchAny {
			normalized := normalizePhrase(phrase)
			if normalized == "" {
				return fmt.Errorf("%s.match_any[%d] is empty", prefix, j)
			}

			if _, exists := seenPhrases[normalized]; exists {
				return fmt.Errorf(
					"%s contains a duplicate match phrase %q",
					prefix,
					phrase,
				)
			}

			seenPhrases[normalized] = struct{}{}
		}
	}

	return nil
}

// validIdentifier accepts simple lowercase identifiers rather than arbitrary
// text. This keeps pattern IDs and categories predictable in logs and APIs.
func validIdentifier(value string) bool {
	if value == "" || strings.TrimSpace(value) != value {
		return false
	}

	for _, ch := range value {
		switch {
		case ch >= 'a' && ch <= 'z':
		case ch >= '0' && ch <= '9':
		case ch == '_', ch == '-':
		default:
			return false
		}
	}

	return true
}

// normalizePhrase is used only for validating duplicate phrases. Matching
// behavior remains the responsibility of the classifier.
func normalizePhrase(value string) string {
	return strings.ToLower(strings.Join(strings.Fields(value), " "))
}

func validateUniqueTextList(name string, values []string) error {
	seen := make(map[string]struct{}, len(values))

	for i, value := range values {
		normalized := normalizePhrase(value)
		if normalized == "" {
			return fmt.Errorf("%s[%d] is empty", name, i)
		}

		if _, exists := seen[normalized]; exists {
			return fmt.Errorf("%s contains a duplicate entry %q", name, value)
		}

		seen[normalized] = struct{}{}
	}

	return nil
}

// cloneFailureDatabase deep-copies all slices so consumers cannot mutate
// package-level cached data.
func cloneFailureDatabase(source FailureDatabase) FailureDatabase {
	result := FailureDatabase{
		SchemaVersion: source.SchemaVersion,
		Status:        source.Status,
		Regions:       append([]string(nil), source.Regions...),
		Guardrails:    append([]string(nil), source.Guardrails...),
		Patterns:      make([]FailurePattern, len(source.Patterns)),
	}

	for i, pattern := range source.Patterns {
		result.Patterns[i] = FailurePattern{
			ID:             pattern.ID,
			Category:       pattern.Category,
			Recommendation: pattern.Recommendation,
			Risk:           pattern.Risk,
			MatchAny:       append([]string(nil), pattern.MatchAny...),
		}
	}

	return result
}
