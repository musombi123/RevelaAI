package genesis

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"revela-genesis.local/core-one/bom"
	"revela-genesis.local/core-one/hardware"
	"revela-worldwide.local/libs/country"
	"revela-worldwide.local/libs/guardian"
)

// ApplyWorldwideProfile equips a tool specification with country-specific
// configuration, commercial context, electrical requirements, standards,
// legal frameworks, and supplier information.
//
// The original demand is checked by Guardian before any specification is
// modified. Slice values are copied to avoid sharing mutable profile data.
func ApplyWorldwideProfile(spec *ToolSpec, p country.Profile) error {
	if spec == nil {
		return errors.New("genesis: tool specification is required")
	}

	decision := guardian.CheckText(spec.Demand)
	if !decision.Allowed {
		return fmt.Errorf(
			"genesis: worldwide profile rejected by guardian: %s: %s",
			decision.Code,
			decision.Reason,
		)
	}

	code := strings.ToUpper(strings.TrimSpace(p.Code))
	language := strings.TrimSpace(p.Language)

	if code == "" {
		return errors.New("genesis: country code is required")
	}

	if language == "" {
		return errors.New("genesis: language is required")
	}

	// Resolve the profile again so that callers cannot accidentally apply an
	// incomplete or inconsistent country profile.
	profile, err := country.Resolve(code, language)
	if err != nil {
		return fmt.Errorf(
			"genesis: resolve worldwide profile for %s (%s): %w",
			code,
			language,
			err,
		)
	}

	// Resolve commercial and supplier information for the same locale.
	countryBOM, err := bom.ForCountry(profile.Code, profile.Language)
	if err != nil {
		return fmt.Errorf(
			"genesis: resolve bill of materials for %s: %w",
			profile.Code,
			err,
		)
	}

	// Apply the resolved profile only after validation and BOM resolution
	// have completed successfully.
	spec.Country = profile.Code
	spec.CountryName = profile.Name
	spec.Language = profile.Language
	spec.Currency = profile.Currency

	spec.SupplierDirectory = append(
		[]string(nil),
		profile.Suppliers...,
	)

	spec.NominalACVoltage = profile.NominalACVoltage
	spec.FrequencyHz = profile.FrequencyHz

	spec.LocalAdaptations = append(
		[]string(nil),
		profile.Standards...,
	)

	spec.LegalFrameworks = append(
		[]string(nil),
		profile.LegalFrameworks...,
	)

	spec.BOM = map[string]any{
		"country":     countryBOM.Country,
		"currency":    countryBOM.Currency,
		"suppliers":   append([]string(nil), countryBOM.Suppliers...),
		"price_status": countryBOM.PriceStatus,
		"note":         countryBOM.Note,
	}

	return nil
}

// ResolveWorldwideProfile resolves a supported country and language into
// the canonical profile used by Genesis worldwide adaptation features.
func ResolveWorldwideProfile(
	code string,
	language string,
) (country.Profile, error) {
	code = strings.ToUpper(strings.TrimSpace(code))
	language = strings.TrimSpace(language)

	if code == "" {
		return country.Profile{}, errors.New(
			"genesis: country code is required",
		)
	}

	if language == "" {
		return country.Profile{}, errors.New(
			"genesis: language is required",
		)
	}

	profile, err := country.Resolve(code, language)
	if err != nil {
		return country.Profile{}, fmt.Errorf(
			"genesis: resolve worldwide profile: %w",
			err,
		)
	}

	return profile, nil
}

// generatedWorldGuide builds an additional country-aware hardware guide.
//
// If a regional guide cannot be generated, the fallback explicitly avoids
// guessing electrical requirements, supplier availability, or legal rules.
func generatedWorldGuide(spec ToolSpec) string {
	guide, _, err := hardware.BuildWorldwideGuide(
		spec.Country,
		spec.Language,
	)
	if err != nil {
		return fmt.Sprintf(
			"\n\n## Worldwide adaptation\n\n"+
				"Country: %s\n"+
				"Language: %s\n\n"+
				"A verified country-specific hardware guide is currently "+
				"unavailable. Obtain a reviewed local adaptation before "+
				"building, purchasing, installing, or operating the design. "+
				"Do not assume electrical ratings, supplier availability, "+
				"certification, or legal compliance.\n",
			spec.Country,
			spec.Language,
		)
	}

	return "\n\n" + guide
}

// WorldwideHardwareGuide loads an invention's evidence, applies a validated
// country profile, and combines the existing hardware guide with the
// country-specific adaptation guide.
//
// The invention must already exist under:
//
//	<CoreRoot>/inventions/<name>/evidence.json
//
// This function does not claim that a proposed design is certified, legally
// compliant, or safe to manufacture merely because a guide was generated.
func (e *Engine) WorldwideHardwareGuide(
	name string,
	countryCode string,
	language string,
) (string, country.Profile, error) {
	if e == nil {
		return "", country.Profile{}, errors.New(
			"genesis: engine is required",
		)
	}

	name = strings.TrimSpace(name)
	if !validResourceName(name) {
		return "", country.Profile{}, errors.New(
			"genesis: invalid tool name",
		)
	}

	if strings.TrimSpace(e.CoreRoot) == "" {
		return "", country.Profile{}, errors.New(
			"genesis: core root is not configured",
		)
	}

	profile, err := ResolveWorldwideProfile(countryCode, language)
	if err != nil {
		return "", country.Profile{}, err
	}

	coreRoot, err := filepath.Abs(e.CoreRoot)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: resolve core root: %w",
			err,
		)
	}

	evidencePath := filepath.Join(
		coreRoot,
		"inventions",
		name,
		"evidence.json",
	)

	// Resolve filesystem paths when possible to help ensure that a resource
	// cannot escape the inventions directory through a symbolic link.
	inventionsRoot := filepath.Join(coreRoot, "inventions")
	realInventionsRoot, rootErr := filepath.EvalSymlinks(inventionsRoot)
	realEvidencePath, evidenceErr := filepath.EvalSymlinks(evidencePath)

	if rootErr == nil && evidenceErr == nil {
		relativePath, relErr := filepath.Rel(
			realInventionsRoot,
			realEvidencePath,
		)
		if relErr != nil {
			return "", country.Profile{}, fmt.Errorf(
				"genesis: validate invention evidence path: %w",
				relErr,
			)
		}

		if relativePath == ".." ||
			strings.HasPrefix(
				relativePath,
				".."+string(filepath.Separator),
			) ||
			filepath.IsAbs(relativePath) {
			return "", country.Profile{}, errors.New(
				"genesis: invention evidence path is outside the inventions directory",
			)
		}

		evidencePath = realEvidencePath
	}

	raw, err := os.ReadFile(evidencePath)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: read invention evidence for %q: %w",
			name,
			err,
		)
	}

	var envelope struct {
		Specification ToolSpec `json:"specification"`
	}

	if err := json.Unmarshal(raw, &envelope); err != nil {
		return "", country.Profile{}, errors.New(
			"genesis: invention specification evidence is invalid",
		)
	}

	if err := ApplyWorldwideProfile(
		&envelope.Specification,
		profile,
	); err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: apply worldwide profile: %w",
			err,
		)
	}

	// Preserve the existing hardware guide and append the regional
	// adaptation so the output contains both general and local guidance.
	generalGuide := generatedHardwareGuide(envelope.Specification)
	worldwideGuide := generatedWorldGuide(envelope.Specification)

	result := strings.TrimSpace(
		generalGuide + "\n\n" + worldwideGuide,
	)

	if result == "" {
		return "", country.Profile{}, errors.New(
			"genesis: hardware guide generation produced no content",
		)
	}

	return result, profile, nil
}
