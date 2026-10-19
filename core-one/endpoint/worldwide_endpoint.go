package endpoint

import (
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strings"

	"revela-worldwide.local/libs/country"
)

const (
	defaultWorldCountry = "KE"

	maxWorldCountryBytes  = 3
	maxWorldLanguageBytes = 35
)

var worldLanguagePattern = regexp.MustCompile(
	`^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$`,
)

// ResolveWorldContext resolves country and language settings.
//
// Precedence:
//   1. Query parameter ?country= or ?lang=
//   2. Corresponding request-body field
//   3. Country defaults to KE; language defaults through country.Resolve
//
// Conflicting duplicate query parameters are rejected instead of silently
// choosing one value. The country package remains authoritative for resolving
// supported country profiles and their default languages.
func ResolveWorldContext(
	r *http.Request,
	bodyCountry string,
	bodyLanguage string,
) (country.Profile, error) {
	queryCountry, err := worldQueryValue(r, "country")
	if err != nil {
		return country.Profile{}, err
	}

	queryLanguage, err := worldQueryValue(r, "lang")
	if err != nil {
		return country.Profile{}, err
	}

	code := strings.TrimSpace(queryCountry)
	if code == "" {
		code = strings.TrimSpace(bodyCountry)
	}
	if code == "" {
		code = defaultWorldCountry
	}

	language := strings.TrimSpace(queryLanguage)
	if language == "" {
		language = strings.TrimSpace(bodyLanguage)
	}

	if err := validateWorldCountryInput(code); err != nil {
		return country.Profile{}, err
	}

	if err := validateWorldLanguageInput(language); err != nil {
		return country.Profile{}, err
	}

	profile, err := country.Resolve(code, language)
	if err != nil {
		return country.Profile{}, fmt.Errorf(
			"resolve world context: %w",
			err,
		)
	}

	return profile, nil
}

// worldQueryValue reads a query parameter while rejecting conflicting
// repeated values, such as ?country=KE&country=US.
//
// Repeated identical values are accepted for compatibility with clients
// that may append the same parameter more than once.
func worldQueryValue(
	r *http.Request,
	key string,
) (string, error) {
	if r == nil || r.URL == nil {
		return "", nil
	}

	values, exists := r.URL.Query()[key]
	if !exists || len(values) == 0 {
		return "", nil
	}

	selected := strings.TrimSpace(values[0])

	for _, raw := range values[1:] {
		value := strings.TrimSpace(raw)
		if !strings.EqualFold(value, selected) {
			return "", fmt.Errorf(
				"conflicting values supplied for query parameter %q",
				key,
			)
		}
	}

	return selected, nil
}

func validateWorldCountryInput(code string) error {
	if code == "" {
		return errors.New("country code cannot be empty")
	}

	if len(code) > maxWorldCountryBytes {
		return errors.New("country code must contain at most three ASCII letters")
	}

	for _, r := range code {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') {
			return errors.New("country code must contain ASCII letters only")
		}
	}

	return nil
}

func validateWorldLanguageInput(language string) error {
	if language == "" {
		// An empty language is allowed; country.Resolve selects the default.
		return nil
	}

	if len(language) > maxWorldLanguageBytes {
		return errors.New("language identifier exceeds the permitted length")
	}

	if !worldLanguagePattern.MatchString(language) {
		return errors.New("language must be a valid language tag using letters, digits, and hyphens")
	}

	return nil
}
