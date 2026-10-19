package bom

import (
	"fmt"
	"strings"

	"revela-worldwide.local/libs/bom"
	"revela-worldwide.local/libs/country"
)

// GlobalBOM exposes the shared Bill of Materials adapter for
// country-specific configurations across the Revela ecosystem.
type GlobalBOM = bom.BOMAdapter

// ForCountry resolves the requested country and language, then returns
// a BOM adapter configured for the resolved country profile.
//
// Country codes are normalized to uppercase. Language values are trimmed
// but otherwise preserved to support locale-specific identifiers.
func ForCountry(countryCode, language string) (GlobalBOM, error) {
	countryCode = strings.ToUpper(strings.TrimSpace(countryCode))
	language = strings.TrimSpace(language)

	profile, err := country.Resolve(countryCode, language)
	if err != nil {
		return GlobalBOM{}, fmt.Errorf(
			"bom: resolve country %q with language %q: %w",
			countryCode,
			language,
			err,
		)
	}

	return bom.ForCountry(profile), nil
}
