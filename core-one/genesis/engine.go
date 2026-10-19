package genesis

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"revela-genesis.local/core-one/bom"
	"revela-genesis.local/core-one/hardware"
	"revela-worldwide.local/libs/country"
	"revela-worldwide.local/libs/guardian"
)

const worldwideReportSchema = "genesis.worldwide-readiness.v1"
const maxWorldwideEvidenceBytes int64 = 8 << 20 // 8 MiB

// WorldwideReviewCheck records whether a specific country-adaptation input is
// available. An available check is not proof of legal or technical compliance.
type WorldwideReviewCheck struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Detail string `json:"detail"`
}

// WorldwideReadinessReport summarizes the data Genesis can resolve for a
// country-specific invention. It deliberately never marks an invention as
// production-approved: local engineering, legal, safety, and procurement review
// remain mandatory.
type WorldwideReadinessReport struct {
	SchemaVersion          string                 `json:"schema_version"`
	GeneratedAt            time.Time              `json:"generated_at"`
	CountryCode            string                 `json:"country_code"`
	CountryName            string                 `json:"country_name"`
	ProfileCoverage        string                 `json:"profile_coverage"`
	Language               string                 `json:"language"`
	Currency               string                 `json:"currency,omitempty"`
	CurrencySymbol         string                 `json:"currency_symbol,omitempty"`
	NominalACVoltage       int                    `json:"nominal_ac_voltage_v,omitempty"`
	FrequencyHz            string                 `json:"frequency_hz,omitempty"`
	SupplierDirectory      []string               `json:"supplier_directory,omitempty"`
	LocalStandards         []string               `json:"local_standards,omitempty"`
	LegalFrameworks        []string               `json:"legal_framework_awareness,omitempty"`
	BillOfMaterials        map[string]any         `json:"bill_of_materials,omitempty"`
	Checks                 []WorldwideReviewCheck `json:"checks"`
	Warnings               []string               `json:"warnings,omitempty"`
	HardwareGuide          string                 `json:"hardware_guide,omitempty"`
	HumanReviewRequired    bool                   `json:"human_review_required"`
	ProductionApproval     bool                   `json:"production_approval"`
	ProductionApprovalNote string                 `json:"production_approval_note"`
}

// ApplyWorldwideProfile adds validated country and language configuration to a
// tool specification. It resolves all required data before mutating spec, so a
// country or BOM error does not leave a half-updated specification.
func ApplyWorldwideProfile(spec *ToolSpec, p country.Profile) error {
	if spec == nil {
		return errors.New("genesis: tool specification is required")
	}

	demand := strings.TrimSpace(spec.Demand)
	if demand == "" {
		return errors.New("genesis: invention demand is required for worldwide adaptation")
	}

	decision := guardian.CheckText(demand)
	if !decision.Allowed {
		return fmt.Errorf(
			"genesis: worldwide profile rejected by guardian: %s: %s",
			decision.Code,
			decision.Reason,
		)
	}

	profile, err := ResolveWorldwideProfile(p.Code, p.Language)
	if err != nil {
		return err
	}

	countryBOM, err := ResolveWorldwideBOM(profile.Code, profile.Language)
	if err != nil {
		return fmt.Errorf(
			"genesis: resolve bill of materials for %s: %w",
			profile.Code,
			err,
		)
	}

	// Commit the profile to spec only after country and BOM resolution succeeds.
	spec.Country = profile.Code
	spec.CountryName = profile.Name
	spec.Language = profile.Language
	spec.Currency = profile.Currency
	spec.SupplierDirectory = cloneWorldwideStrings(profile.Suppliers)
	spec.NominalACVoltage = profile.NominalACVoltage
	spec.FrequencyHz = profile.FrequencyHz
	spec.LocalAdaptations = cloneWorldwideStrings(profile.Standards)
	spec.LegalFrameworks = cloneWorldwideStrings(profile.LegalFrameworks)

	spec.BOM = map[string]any{
		"country":             countryBOM.Country,
		"profile_coverage":    worldwideProfileCoverage(profile.Code),
		"currency":            countryBOM.Currency,
		"suppliers":           cloneWorldwideStrings(countryBOM.Suppliers),
		"price_status":        countryBOM.PriceStatus,
		"note":                countryBOM.Note,
		"availability_status": "not_live_verified",
		"price_verification":  "not_live_verified",
	}

	return nil
}

// ResolveWorldwideProfile returns the canonical supported country/language
// profile. Codes are normalized; language tags are trimmed but not rewritten.
func ResolveWorldwideProfile(code, language string) (country.Profile, error) {
	code = strings.ToUpper(strings.TrimSpace(code))
	language = strings.TrimSpace(language)

	if code == "" {
		return country.Profile{}, errors.New("genesis: country code is required")
	}
	if language == "" {
		return country.Profile{}, errors.New("genesis: language is required")
	}

	profile, err := country.Resolve(code, language)
	if err != nil {
		return country.Profile{}, fmt.Errorf(
			"genesis: resolve worldwide profile for country %q and language %q: %w",
			code,
			language,
			err,
		)
	}

	return profile, nil
}

// ResolveWorldwideBOM provides a country- and language-aware bill of materials
// before an invention is created. Returned values are directory/profile data,
// not live stock, quotes, shipping promises, or confirmed supplier availability.
func ResolveWorldwideBOM(code, language string) (bom.GlobalBOM, error) {
	profile, err := ResolveWorldwideProfile(code, language)
	if err != nil {
		return bom.GlobalBOM{}, err
	}

	countryBOM, err := bom.ForCountry(profile.Code, profile.Language)
	if err != nil {
		return bom.GlobalBOM{}, fmt.Errorf(
			"genesis: resolve worldwide BOM: %w",
			err,
		)
	}

	return countryBOM, nil
}

// BuildWorldwideReadinessReport builds a preview before invention generation.
// Missing regional data is reported as a warning rather than silently guessed.
// This report is a preparation aid, not a certification or compliance verdict.
func BuildWorldwideReadinessReport(code, language string) (WorldwideReadinessReport, error) {
	profile, err := ResolveWorldwideProfile(code, language)
	if err != nil {
		return WorldwideReadinessReport{}, err
	}

	countryBOM, err := ResolveWorldwideBOM(profile.Code, profile.Language)
	if err != nil {
		return WorldwideReadinessReport{}, err
	}

	report := WorldwideReadinessReport{
		SchemaVersion:     worldwideReportSchema,
		GeneratedAt:       time.Now().UTC(),
		CountryCode:       profile.Code,
		CountryName:       profile.Name,
		ProfileCoverage:   worldwideProfileCoverage(profile.Code),
		Language:          profile.Language,
		Currency:          profile.Currency,
		CurrencySymbol:    profile.CurrencySymbol,
		NominalACVoltage:  profile.NominalACVoltage,
		FrequencyHz:       profile.FrequencyHz,
		SupplierDirectory: cloneWorldwideStrings(profile.Suppliers),
		LocalStandards:    cloneWorldwideStrings(profile.Standards),
		LegalFrameworks:   cloneWorldwideStrings(profile.LegalFrameworks),
		BillOfMaterials: map[string]any{
			"country":             countryBOM.Country,
			"profile_coverage":    worldwideProfileCoverage(profile.Code),
			"currency":            countryBOM.Currency,
			"suppliers":           cloneWorldwideStrings(countryBOM.Suppliers),
			"price_status":        countryBOM.PriceStatus,
			"note":                countryBOM.Note,
			"availability_status": "not_live_verified",
			"price_verification":  "not_live_verified",
		},
		HumanReviewRequired:    true,
		ProductionApproval:     false,
		ProductionApprovalNote: "Genesis provides a reviewable regional adaptation only. Independent engineering, safety, legal, certification, and procurement checks are required before production.",
	}

	addCheck := func(name, status, detail string) {
		report.Checks = append(report.Checks, WorldwideReviewCheck{
			Name:   name,
			Status: status,
			Detail: detail,
		})
	}
	addWarning := func(message string) {
		report.Warnings = append(report.Warnings, message)
	}

	if worldwideProfileCoverage(profile.Code) == "country_specific" {
		addCheck(
			"country_profile",
			"available",
			"A country-specific profile is present for this country.",
		)
	} else {
		addCheck(
			"country_profile",
			"generic_fallback",
			"Only generic worldwide defaults are available for this country code; country-specific facts are not verified.",
		)
		addWarning(
			"This country has only a generic fallback profile. Currency, suppliers, electrical characteristics, standards and legal requirements need country-specific verification before the guide can be relied on.",
		)
	}

	addCheck(
		"language_profile",
		"available",
		"A country/language profile was resolved; generated wording still requires a fluent local review.",
	)

	if profile.Currency == "" ||
		(worldwideProfileCoverage(profile.Code) != "country_specific" &&
			profile.Currency == "LOCAL") {
		addCheck(
			"currency",
			"incomplete",
			"The profile does not specify a country-verified currency.",
		)
		addWarning("Currency metadata is incomplete; do not infer or quote local prices.")
	} else {
		addCheck(
			"currency",
			"available",
			"Currency metadata is available; no live exchange rate or tax calculation has been performed.",
		)
	}

	if profile.NominalACVoltage <= 0 ||
		strings.TrimSpace(profile.FrequencyHz) == "" {
		addCheck(
			"electrical_baseline",
			"incomplete",
			"Nominal voltage or frequency is missing from the profile.",
		)
		addWarning(
			"Electrical data is incomplete. Verify supply voltage, frequency, phase, grounding, and local installation rules with a qualified professional.",
		)
	} else {
		addCheck(
			"electrical_baseline",
			"review_required",
			"Profile provides a nominal voltage and frequency only; verify actual installation requirements and equipment ratings locally.",
		)
	}

	if len(profile.Suppliers) == 0 ||
		worldwideProfileCoverage(profile.Code) != "country_specific" {
		addCheck(
			"supplier_directory",
			"incomplete",
			"No country-verified supplier directory is available in the profile.",
		)
		addWarning(
			"No country-verified supplier directory is available. Supplier availability, legitimacy, delivery and pricing are not live-verified by this report.",
		)
	} else {
		addCheck(
			"supplier_directory",
			"reference_only",
			"Supplier entries are directory references, not confirmations of inventory, pricing, shipping, quality or warranties.",
		)
		addWarning(
			"Confirm each supplier's current stock, legitimacy, price, taxes, delivery conditions and warranties before ordering.",
		)
	}

	if len(profile.Standards) == 0 ||
		worldwideProfileCoverage(profile.Code) != "country_specific" {
		addCheck(
			"local_standards",
			"incomplete",
			"No country-verified standards/adaptation entries are available in the profile.",
		)
		addWarning(
			"No country-verified standards are listed. Obtain current standards from the appropriate national standards body or regulator.",
		)
	} else {
		addCheck(
			"local_standards",
			"reference_only",
			"Standards listed by the profile are pointers for review, not proof that the design complies with them.",
		)
	}

	if len(profile.LegalFrameworks) == 0 ||
		worldwideProfileCoverage(profile.Code) != "country_specific" {
		addCheck(
			"legal_framework_awareness",
			"incomplete",
			"No country-verified legal-framework entries are available in the profile.",
		)
		addWarning(
			"No country-verified legal frameworks are listed. Seek current legal and regulatory advice for the intended product and use case.",
		)
	} else {
		addCheck(
			"legal_framework_awareness",
			"reference_only",
			"Listed frameworks support issue spotting only; they are not a legal opinion or compliance determination.",
		)
	}

	if strings.TrimSpace(countryBOM.PriceStatus) == "" {
		addCheck(
			"bom_pricing",
			"incomplete",
			"The BOM adapter did not provide a price-status value.",
		)
		addWarning(
			"The BOM does not provide verified live prices. Obtain current supplier quotations and account for taxes, shipping, duties and currency conversion.",
		)
	} else {
		addCheck(
			"bom_pricing",
			"reference_only",
			"BOM price status: "+worldCleanOneLine(countryBOM.PriceStatus, 160)+". This is not a live supplier quote.",
		)
	}

	guide, _, guideErr := hardware.BuildWorldwideGuide(profile.Code, profile.Language)
	if guideErr != nil {
		addCheck(
			"hardware_guide",
			"unavailable",
			"A localized hardware guide could not be generated.",
		)
		addWarning(
			"A localized hardware guide could not be generated. Do not guess regional electrical, supplier, certification or legal requirements.",
		)
	} else if strings.TrimSpace(guide) == "" {
		addCheck(
			"hardware_guide",
			"incomplete",
			"The guide builder returned empty content.",
		)
		addWarning(
			"The localized hardware guide is empty and requires a reviewed local adaptation.",
		)
	} else {
		previewSpec := ToolSpec{
			Country:           profile.Code,
			CountryName:       profile.Name,
			Language:          profile.Language,
			Currency:          profile.Currency,
			NominalACVoltage:  profile.NominalACVoltage,
			FrequencyHz:       profile.FrequencyHz,
			SupplierDirectory: cloneWorldwideStrings(profile.Suppliers),
			LocalAdaptations:  cloneWorldwideStrings(profile.Standards),
			LegalFrameworks:   cloneWorldwideStrings(profile.LegalFrameworks),
			BOM:               report.BillOfMaterials,
		}

		report.HardwareGuide = generatedWorldGuide(previewSpec)

		addCheck(
			"hardware_guide",
			"generated_review_required",
			"Localized reference guidance was generated; all technical claims require source and expert review.",
		)
	}

	return report, nil
}

// generatedWorldGuide expands the library guide with the resolved profile,
// BOM status, suppliers, standards, legal awareness, and review boundaries.
// When localization fails, it emits a conservative fallback instead of
// inventing technical or regulatory details.
func generatedWorldGuide(spec ToolSpec) string {
	guide, _, err := hardware.BuildWorldwideGuide(
		spec.Country,
		spec.Language,
	)

	if err != nil || strings.TrimSpace(guide) == "" {
		guide = fmt.Sprintf(
			"## Worldwide adaptation reference\n\n"+
				"Country: %s\n\nLanguage: %s\n\n"+
				"A verified country-specific hardware guide is unavailable. Obtain a reviewed local adaptation before purchasing, building, installing or operating the design. Do not guess electrical ratings, supplier availability, certification or legal compliance.\n",
			worldEmptyFallback(spec.Country, "Not resolved"),
			worldEmptyFallback(spec.Language, "Not resolved"),
		)
	}

	var b strings.Builder

	b.WriteString(strings.TrimSpace(guide))
	b.WriteString("\n\n## Genesis worldwide adaptation profile\n\n")

	fmt.Fprintf(
		&b,
		"- Country: %s\n",
		worldEmptyFallback(spec.CountryName, worldEmptyFallback(spec.Country, "Not resolved")),
	)
	fmt.Fprintf(
		&b,
		"- Country code: %s\n",
		worldEmptyFallback(spec.Country, "Not resolved"),
	)
	fmt.Fprintf(
		&b,
		"- Profile coverage: %s\n",
		worldMapValue(spec.BOM, "profile_coverage", "unknown"),
	)
	fmt.Fprintf(
		&b,
		"- Language: %s\n",
		worldEmptyFallback(spec.Language, "Not resolved"),
	)
	fmt.Fprintf(
		&b,
		"- Currency: %s\n",
		worldEmptyFallback(spec.Currency, "Not specified by the profile"),
	)

	if spec.NominalACVoltage > 0 {
		fmt.Fprintf(
			&b,
			"- Nominal AC voltage in country profile: %d V\n",
			spec.NominalACVoltage,
		)
	} else {
		b.WriteString(
			"- Nominal AC voltage: Not specified; verify with the local utility and qualified electrician.\n",
		)
	}

	if strings.TrimSpace(spec.FrequencyHz) != "" {
		fmt.Fprintf(
			&b,
			"- Frequency in country profile (Hz): %s\n",
			worldCleanOneLine(spec.FrequencyHz, 40),
		)
	} else {
		b.WriteString(
			"- Frequency: Not specified; verify locally before selecting or operating equipment.\n",
		)
	}

	writeWorldwideList(
		&b,
		"Supplier directory references",
		spec.SupplierDirectory,
		"No supplier entries are present in the country profile.",
	)
	writeWorldwideList(
		&b,
		"Local standards/adaptation references",
		spec.LocalAdaptations,
		"No standards are listed. Check the applicable national standards body and regulator.",
	)
	writeWorldwideList(
		&b,
		"Legal-framework awareness",
		spec.LegalFrameworks,
		"No legal frameworks are listed. Obtain local legal/regulatory guidance.",
	)

	b.WriteString("\n## Bill of materials and commercial status\n\n")

	if spec.BOM == nil {
		b.WriteString(
			"No country-specific BOM metadata is available. Do not estimate local prices or component availability from this guide.\n",
		)
	} else {
		fmt.Fprintf(
			&b,
			"- Country in BOM: %s\n",
			worldMapValue(spec.BOM, "country", "Not supplied"),
		)
		fmt.Fprintf(
			&b,
			"- Currency: %s\n",
			worldMapValue(spec.BOM, "currency", worldEmptyFallback(spec.Currency, "Not supplied")),
		)
		fmt.Fprintf(
			&b,
			"- Price status: %s\n",
			worldMapValue(spec.BOM, "price_status", "Not supplied"),
		)
		fmt.Fprintf(
			&b,
			"- BOM note: %s\n",
			worldMapValue(spec.BOM, "note", "No note supplied"),
		)
		fmt.Fprintf(
			&b,
			"- Live availability: %s\n",
			worldMapValue(spec.BOM, "availability_status", "not live-verified"),
		)
		fmt.Fprintf(
			&b,
			"- Live price verification: %s\n",
			worldMapValue(spec.BOM, "price_verification", "not live-verified"),
		)
	}

	b.WriteString("\n## Mandatory verification before use\n\n")
	b.WriteString(
		"- Verify voltage, frequency, phase, grounding, protection, enclosure and installation requirements for the actual site. The country profile is not a measurement of the site supply.\n",
	)
	b.WriteString(
		"- Verify current standards, licensing, permits, certification and legal obligations with qualified local professionals and the responsible authorities.\n",
	)
	b.WriteString(
		"- Confirm supplier legitimacy, stock, specifications, price, taxes, shipping, import duties, warranties and replacement availability directly with each supplier.\n",
	)
	b.WriteString(
		"- Complete hazard analysis, testing, documented engineering review and any required independent inspection before use.\n",
	)
	b.WriteString(
		"- This generated guide is advisory. It is not a certification, professional engineering sign-off, legal opinion, or authorization to manufacture or deploy.\n",
	)

	return b.String()
}

// WorldwideHardwareGuide loads a previously generated invention's evidence,
// overlays a requested country/language profile without modifying the saved
// invention, then returns both the general and regional hardware guidance.
func (e *Engine) WorldwideHardwareGuide(
	name string,
	countryCode string,
	language string,
) (string, country.Profile, error) {
	if e == nil {
		return "", country.Profile{}, errors.New("genesis: engine is required")
	}

	name = strings.TrimSpace(name)
	if !validResourceName(name) {
		return "", country.Profile{}, errors.New("genesis: invalid tool name")
	}

	if strings.TrimSpace(e.CoreRoot) == "" {
		return "", country.Profile{}, errors.New("genesis: core root is not configured")
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

	inventionsRoot := filepath.Join(coreRoot, "inventions")
	realInventionsRoot, err := filepath.EvalSymlinks(inventionsRoot)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: resolve inventions directory: %w",
			err,
		)
	}

	evidencePath := filepath.Join(inventionsRoot, name, "evidence.json")
	realEvidencePath, err := filepath.EvalSymlinks(evidencePath)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: resolve invention evidence for %q: %w",
			name,
			err,
		)
	}

	relativePath, err := filepath.Rel(realInventionsRoot, realEvidencePath)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: validate invention evidence path: %w",
			err,
		)
	}

	if relativePath == ".." ||
		strings.HasPrefix(relativePath, ".."+string(filepath.Separator)) ||
		filepath.IsAbs(relativePath) {
		return "", country.Profile{}, errors.New(
			"genesis: invention evidence path is outside the inventions directory",
		)
	}

	info, err := os.Stat(realEvidencePath)
	if err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: stat invention evidence: %w",
			err,
		)
	}

	if !info.Mode().IsRegular() {
		return "", country.Profile{}, errors.New(
			"genesis: invention evidence must be a regular file",
		)
	}

	if info.Size() > maxWorldwideEvidenceBytes {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: invention evidence exceeds the %d-byte limit",
			maxWorldwideEvidenceBytes,
		)
	}

	raw, err := os.ReadFile(realEvidencePath)
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

	if strings.TrimSpace(envelope.Specification.Name) != "" &&
		envelope.Specification.Name != name {
		return "", country.Profile{}, errors.New(
			"genesis: invention evidence name does not match the requested resource",
		)
	}

	if err := ApplyWorldwideProfile(&envelope.Specification, profile); err != nil {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: apply worldwide profile: %w",
			err,
		)
	}

	generalGuide := strings.TrimSpace(
		generatedHardwareGuide(envelope.Specification),
	)
	worldwideGuide := strings.TrimSpace(
		generatedWorldGuide(envelope.Specification),
	)

	parts := make([]string, 0, 2)

	if generalGuide != "" {
		parts = append(parts, generalGuide)
	}
	if worldwideGuide != "" {
		parts = append(parts, worldwideGuide)
	}

	result := strings.TrimSpace(strings.Join(parts, "\n\n---\n\n"))
	if result == "" {
		return "", country.Profile{}, errors.New(
			"genesis: hardware guide generation produced no content",
		)
	}

	decision := guardian.CheckText(result)
	if !decision.Allowed {
		return "", country.Profile{}, fmt.Errorf(
			"genesis: generated worldwide hardware guide blocked by guardian: %s",
			decision.Code,
		)
	}

	return result, profile, nil
}

func cloneWorldwideStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}

	return append([]string(nil), values...)
}

func writeWorldwideList(
	b *strings.Builder,
	heading string,
	values []string,
	emptyMessage string,
) {
	b.WriteString("\n### ")
	b.WriteString(heading)
	b.WriteString("\n\n")

	if len(values) == 0 {
		b.WriteString(emptyMessage)
		b.WriteString("\n")
		return
	}

	for _, value := range values {
		value = worldCleanOneLine(value, 300)
		if value == "" {
			continue
		}

		b.WriteString("- ")
		b.WriteString(value)
		b.WriteString("\n")
	}
}

func worldMapValue(
	values map[string]any,
	key string,
	fallback string,
) string {
	if values == nil {
		return fallback
	}

	value, ok := values[key]
	if !ok || value == nil {
		return fallback
	}

	text := worldCleanOneLine(fmt.Sprint(value), 500)
	return worldEmptyFallback(text, fallback)
}

func worldCleanOneLine(value string, maxLength int) string {
	value = strings.TrimSpace(value)
	value = strings.Join(strings.Fields(value), " ")

	if maxLength > 0 {
		runes := []rune(value)
		if len(runes) > maxLength {
			value = string(runes[:maxLength])
		}
	}

	return value
}

func worldEmptyFallback(value, fallback string) string {
	value = worldCleanOneLine(value, 500)
	if value == "" {
		return fallback
	}

	return value
}

// worldwideProfileCoverage distinguishes countries with explicit profile data
// from generic two-letter-code fallbacks returned by the shared resolver.
func worldwideProfileCoverage(code string) string {
	switch strings.ToUpper(strings.TrimSpace(code)) {
	case "KE", "US", "DE", "CN", "JP", "FR", "ES", "GB", "IN", "CA", "AU":
		return "country_specific"
	default:
		return "generic_fallback"
	}
}
