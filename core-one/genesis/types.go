package genesis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	Version            = "0.3.0-alpha"
	CoreSchemaVersion  = 1

	SchemaMaxDemandBytes      = 4000
	SchemaMaxNameBytes        = 64
	SchemaMaxTitleBytes       = 200
	SchemaMaxPurposeBytes     = 2000
	SchemaMaxMetadataBytes    = 500
	SchemaMaxListItems        = 128
	SchemaMaxSourceURLBytes   = 2048
	SchemaMaxEvidenceBytes    = 4 << 20
	SchemaMaxBOMBytes         = 1 << 20
	SchemaMaxModelNoteBytes   = 1000
	SchemaMaxEventMessageBytes = 2000
)

// Lifecycle constants provide shared names for the main Genesis states.
const (
	DemandStatusPending    = "pending"
	DemandStatusProcessing = "processing"
	DemandStatusQueued     = "queued"
	DemandStatusBlocked    = "blocked"
	DemandStatusFailed     = "failed"

	ProposalStatusAwaitMerge = "await_merge"
	ProposalStatusBlocked    = "blocked"
	ProposalStatusFailed     = "failed"

	ResearchStatusRetrieved     = "retrieved"
	ResearchStatusReferenceLink = "reference_link"
	ResearchStatusUnavailable   = "unavailable"
	ResearchStatusParseError    = "parse_error"

	ResearchModeOffline                = "offline"
	ResearchModeOnlineWithOfflineFallback = "online-with-offline-fallback"

	ExecutionModeProposalOnly = "proposal_only"
)

// Demand is an untrusted request to propose a new tool.
// It is never executed as code.
type Demand struct {
	ID        string    `json:"id"`
	Demand    string    `json:"demand"`
	Source    string    `json:"source,omitempty"`
	CreatedAt time.Time `json:"created_at"`
	Status    string    `json:"status"`
	Error     string    `json:"error,omitempty"`
	Country   string    `json:"country,omitempty"`
	Language  string    `json:"language,omitempty"`
}

// ResearchSource describes a retrieved research record or an explicitly
// identified research link. Retrieved content is not automatically trusted.
type ResearchSource struct {
	Name      string    `json:"name"`
	URL       string    `json:"url"`
	Status    string    `json:"status"`
	Title     string    `json:"title,omitempty"`
	Snippet   string    `json:"snippet,omitempty"`
	Retrieved time.Time `json:"retrieved_at,omitempty"`
}

// ResearchEvidence holds the collected information used during invention.
// Evidence is advisory and does not establish legal, technical, or commercial
// verification by itself.
type ResearchEvidence struct {
	ID          string           `json:"id"`
	Query       string           `json:"query"`
	CollectedAt time.Time        `json:"collected_at"`
	Mode        string           `json:"mode"`
	Sources     []ResearchSource `json:"sources"`
	Findings    []string         `json:"findings"`
}

// ToolSpec represents the deterministic specification for a proposed tool.
// Model assistance may enrich metadata but must not override deterministic
// safety, category, industry, or hardware boundaries.
type ToolSpec struct {
	Name               string         `json:"name"`
	Title              string         `json:"title"`
	Demand              string         `json:"demand"`
	Purpose             string         `json:"purpose"`
	Category            string         `json:"category"`
	Industry            string         `json:"industry"`
	Capabilities        []string       `json:"capabilities"`
	Inputs              []string       `json:"inputs"`
	Outputs             []string       `json:"outputs"`
	Safeguards          []string       `json:"safeguards"`
	NeedsHardwareGuide  bool           `json:"needs_hardware_guide"`
	Country             string         `json:"country,omitempty"`
	CountryName         string         `json:"country_name,omitempty"`
	Language            string         `json:"language,omitempty"`
	Currency            string         `json:"currency,omitempty"`
	SupplierDirectory   []string       `json:"supplier_directory,omitempty"`
	NominalACVoltage    int            `json:"nominal_ac_voltage_v,omitempty"`
	FrequencyHz         string         `json:"frequency_hz,omitempty"`
	LocalAdaptations    []string       `json:"local_adaptations,omitempty"`
	LegalFrameworks     []string       `json:"legal_framework_awareness,omitempty"`
	BOM                 map[string]any `json:"bom,omitempty"`
	ModelAssisted       bool           `json:"model_assisted"`
	ModelNote           string         `json:"model_note,omitempty"`
}

// Invention describes a generated proposal and its associated evidence,
// artifacts, and capability coverage.
type Invention struct {
	ID                  string            `json:"id"`
	Name                string            `json:"name"`
	Title               string            `json:"title"`
	Status              string            `json:"status"`
	CreatedAt           time.Time         `json:"created_at"`
	Directory           string            `json:"directory"`
	Library             string            `json:"library"`
	Model               string            `json:"model"`
	Category            string            `json:"category"`
	Industry            string            `json:"industry"`
	Country             string            `json:"country,omitempty"`
	CountryName         string            `json:"country_name,omitempty"`
	Language            string            `json:"language,omitempty"`
	Currency            string            `json:"currency,omitempty"`
	SupplierDirectory   []string          `json:"supplier_directory,omitempty"`
	BOM                 map[string]any    `json:"bom,omitempty"`
	Files               []string          `json:"files"`
	Evidence            ResearchEvidence  `json:"evidence"`
	Summary             string            `json:"summary"`
	CapabilityPlanPath  string            `json:"capability_plan_path"`
	CapabilityCoverage  CapabilityCoverage `json:"capability_coverage"`
}

// Event describes an observable Genesis lifecycle event.
type Event struct {
	ID        string    `json:"id"`
	Type      string    `json:"type"`
	At        time.Time `json:"at"`
	Message   string    `json:"message"`
	Invention string    `json:"invention,omitempty"`
	Status    string    `json:"status,omitempty"`
}

// SchemaValidationIssue describes one validation finding without retaining
// the potentially sensitive input value.
type SchemaValidationIssue struct {
	Field    string `json:"field"`
	Code     string `json:"code"`
	Message  string `json:"message"`
	Severity string `json:"severity"`
}

// SchemaValidationReport provides machine-readable schema validation results.
// Warnings do not make the report invalid; errors do.
type SchemaValidationReport struct {
	SchemaVersion int                     `json:"schema_version"`
	Valid         bool                    `json:"valid"`
	Issues        []SchemaValidationIssue `json:"issues"`
}

// Researcher retrieves advisory evidence for a demand.
type Researcher interface {
	Research(ctx context.Context, demand string) (ResearchEvidence, error)
}

// ModelAdapter optionally suggests bounded metadata for a tool specification.
// Its output remains untrusted and must pass the engine's safety checks.
type ModelAdapter interface {
	Suggest(ctx context.Context, demand string, evidence ResearchEvidence, fallback ToolSpec) (ToolSpec, error)
}

// Validate checks a demand's data shape and basic input constraints.
func (d Demand) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "demand", d.Demand, SchemaMaxDemandBytes, true, false)
	schemaCheckText(&report, "id", d.ID, 200, false, true)
	schemaCheckText(&report, "source", d.Source, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "status", d.Status, 100, false, true)
	schemaCheckText(&report, "error", d.Error, SchemaMaxMetadataBytes, false, true)

	schemaCheckCountry(&report, d.Country)
	schemaCheckLanguage(&report, d.Language)

	if !d.CreatedAt.IsZero() && d.CreatedAt.Year() < 2000 {
		report.addWarning("created_at", "unusual_timestamp", "Creation timestamp is unusually old.")
	}

	return report
}

// Validate checks the structure and bounds of a research source.
func (s ResearchSource) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "name", s.Name, SchemaMaxMetadataBytes, true, true)
	schemaCheckText(&report, "title", s.Title, SchemaMaxTitleBytes, false, true)
	schemaCheckText(&report, "snippet", s.Snippet, SchemaMaxMetadataBytes, false, false)
	schemaCheckText(&report, "status", s.Status, 100, true, true)
	schemaCheckURL(&report, "url", s.URL)

	switch s.Status {
	case ResearchStatusRetrieved,
		ResearchStatusReferenceLink,
		ResearchStatusUnavailable,
		ResearchStatusParseError:
		// Known source states.
	case "":
		// The required text check reports the missing status.
	default:
		report.addWarning(
			"status",
			"unknown_research_status",
			"Research status is not one of the standard Genesis research states.",
		)
	}

	if s.Status == ResearchStatusRetrieved && strings.TrimSpace(s.URL) == "" {
		report.addWarning(
			"url",
			"retrieved_source_without_url",
			"A retrieved source has no URL for follow-up verification.",
		)
	}

	return report
}

// Validate checks a research evidence bundle before it is persisted or
// consumed by a downstream workflow.
func (e ResearchEvidence) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "id", e.ID, 200, true, true)
	schemaCheckText(&report, "query", e.Query, SchemaMaxDemandBytes, true, false)
	schemaCheckText(&report, "mode", e.Mode, 100, true, true)

	if e.CollectedAt.IsZero() {
		report.addWarning(
			"collected_at",
			"missing_timestamp",
			"Research evidence has no collection timestamp.",
		)
	}

	if len(e.Sources) > SchemaMaxListItems {
		report.addError(
			"sources",
			"too_many_sources",
			"Research evidence exceeds the permitted source count.",
		)
	}

	if len(e.Findings) > SchemaMaxListItems {
		report.addError(
			"findings",
			"too_many_findings",
			"Research evidence exceeds the permitted findings count.",
		)
	}

	if len(e.Sources) == 0 {
		report.addWarning(
			"sources",
			"no_sources",
			"No source records are attached to the research evidence.",
		)
	}

	for i, source := range e.Sources {
		sourceReport := source.Validate()
		for _, issue := range sourceReport.Issues {
			report.addIssue(SchemaValidationIssue{
				Field:    fmt.Sprintf("sources[%d].%s", i, issue.Field),
				Code:     issue.Code,
				Message:  issue.Message,
				Severity: issue.Severity,
			})
		}
	}

	for i, finding := range e.Findings {
		schemaCheckText(
			&report,
			fmt.Sprintf("findings[%d]", i),
			finding,
			SchemaMaxMetadataBytes,
			true,
			false,
		)
	}

	raw, err := json.Marshal(e)
	if err != nil {
		report.addError(
			"evidence",
			"not_serializable",
			"Research evidence cannot be serialized as JSON.",
		)
	} else if len(raw) > SchemaMaxEvidenceBytes {
		report.addError(
			"evidence",
			"evidence_too_large",
			"Research evidence exceeds the permitted serialized size.",
		)
	}

	return report
}

// Validate checks a tool specification while allowing incomplete optional
// metadata during early-stage proposal construction.
func (s ToolSpec) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "name", s.Name, SchemaMaxNameBytes, true, true)
	if s.Name != "" && !schemaValidResourceName(s.Name) {
		report.addError(
			"name",
			"invalid_resource_name",
			"Tool name must contain only lowercase ASCII letters, numbers, hyphens, and underscores.",
		)
	}

	schemaCheckText(&report, "title", s.Title, SchemaMaxTitleBytes, true, true)
	schemaCheckText(&report, "demand", s.Demand, SchemaMaxDemandBytes, true, false)
	schemaCheckText(&report, "purpose", s.Purpose, SchemaMaxPurposeBytes, true, false)
	schemaCheckText(&report, "category", s.Category, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "industry", s.Industry, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "model_note", s.ModelNote, SchemaMaxModelNoteBytes, false, false)
	schemaCheckText(&report, "country_name", s.CountryName, SchemaMaxTitleBytes, false, true)
	schemaCheckText(&report, "frequency_hz", s.FrequencyHz, 80, false, true)

	if strings.TrimSpace(s.Category) == "" {
		report.addWarning("category", "missing_category", "Tool category has not been assigned.")
	}
	if strings.TrimSpace(s.Industry) == "" {
		report.addWarning("industry", "missing_industry", "Tool industry has not been assigned.")
	}

	schemaCheckCountry(&report, s.Country)
	schemaCheckLanguage(&report, s.Language)
	schemaCheckCurrency(&report, s.Currency)

	if s.NominalACVoltage < 0 {
		report.addError(
			"nominal_ac_voltage_v",
			"negative_voltage",
			"Nominal AC voltage cannot be negative.",
		)
	}

	schemaCheckStringList(&report, "capabilities", s.Capabilities, true)
	schemaCheckStringList(&report, "inputs", s.Inputs, false)
	schemaCheckStringList(&report, "outputs", s.Outputs, false)
	schemaCheckStringList(&report, "safeguards", s.Safeguards, true)
	schemaCheckStringList(&report, "supplier_directory", s.SupplierDirectory, false)
	schemaCheckStringList(&report, "local_adaptations", s.LocalAdaptations, false)
	schemaCheckStringList(&report, "legal_framework_awareness", s.LegalFrameworks, false)

	if len(s.BOM) > 0 {
		raw, err := json.Marshal(s.BOM)
		if err != nil {
			report.addError("bom", "invalid_bom", "The bill of materials cannot be serialized as JSON.")
		} else if len(raw) > SchemaMaxBOMBytes {
			report.addError("bom", "bom_too_large", "The bill of materials exceeds the permitted size.")
		}
	}

	if s.NeedsHardwareGuide && len(s.Safeguards) == 0 {
		report.addWarning(
			"safeguards",
			"hardware_safeguards_missing",
			"A hardware-related proposal should document its safety and review requirements.",
		)
	}

	if s.ModelAssisted && strings.TrimSpace(s.ModelNote) == "" {
		report.addWarning(
			"model_note",
			"model_assistance_unexplained",
			"Model assistance is marked active but its contribution is not described.",
		)
	}

	return report
}

// Validate checks the basic shape of a saved invention record.
func (i Invention) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "id", i.ID, 200, true, true)
	schemaCheckText(&report, "name", i.Name, SchemaMaxNameBytes, true, true)
	schemaCheckText(&report, "title", i.Title, SchemaMaxTitleBytes, true, true)
	schemaCheckText(&report, "status", i.Status, 100, true, true)
	schemaCheckText(&report, "directory", i.Directory, 2000, false, true)
	schemaCheckText(&report, "library", i.Library, 2000, false, true)
	schemaCheckText(&report, "model", i.Model, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "category", i.Category, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "industry", i.Industry, SchemaMaxMetadataBytes, false, true)
	schemaCheckText(&report, "summary", i.Summary, SchemaMaxPurposeBytes, false, false)
	schemaCheckText(&report, "capability_plan_path", i.CapabilityPlanPath, 2000, false, true)

	if i.Name != "" && !schemaValidResourceName(i.Name) {
		report.addError(
			"name",
			"invalid_resource_name",
			"Invention name is not a valid resource identifier.",
		)
	}

	schemaCheckCountry(&report, i.Country)
	schemaCheckLanguage(&report, i.Language)
	schemaCheckCurrency(&report, i.Currency)
	schemaCheckStringList(&report, "files", i.Files, false)
	schemaCheckStringList(&report, "supplier_directory", i.SupplierDirectory, false)

	if i.CreatedAt.IsZero() {
		report.addWarning(
			"created_at",
			"missing_timestamp",
			"The invention record has no creation timestamp.",
		)
	}

	if len(i.BOM) > 0 {
		raw, err := json.Marshal(i.BOM)
		if err != nil {
			report.addError("bom", "invalid_bom", "The invention BOM cannot be serialized as JSON.")
		} else if len(raw) > SchemaMaxBOMBytes {
			report.addError("bom", "bom_too_large", "The invention BOM exceeds the permitted size.")
		}
	}

	return report
}

// Validate checks the basic structure of an event before it is published.
func (e Event) Validate() SchemaValidationReport {
	report := newSchemaValidationReport()

	schemaCheckText(&report, "id", e.ID, 200, false, true)
	schemaCheckText(&report, "type", e.Type, 100, true, true)
	schemaCheckText(&report, "message", e.Message, SchemaMaxEventMessageBytes, true, false)
	schemaCheckText(&report, "invention", e.Invention, SchemaMaxNameBytes, false, true)
	schemaCheckText(&report, "status", e.Status, 100, false, true)

	if e.Type != "" && !schemaValidEventType(e.Type) {
		report.addError(
			"type",
			"invalid_event_type",
			"Event type contains unsupported characters.",
		)
	}

	if e.At.IsZero() {
		report.addWarning(
			"at",
			"missing_timestamp",
			"The event has no timestamp.",
		)
	}

	return report
}

// Error returns an error containing validation errors, or nil if the report
// has no error-severity issues. Warnings are intentionally non-fatal.
func (r SchemaValidationReport) Error() error {
	messages := make([]string, 0)

	for _, issue := range r.Issues {
		if issue.Severity != "error" {
			continue
		}
		messages = append(messages, issue.Field+": "+issue.Message)
	}

	if len(messages) == 0 {
		return nil
	}

	return errors.New(strings.Join(messages, "; "))
}

// HasWarnings reports whether the validation report contains warnings.
func (r SchemaValidationReport) HasWarnings() bool {
	for _, issue := range r.Issues {
		if issue.Severity == "warning" {
			return true
		}
	}
	return false
}

func newSchemaValidationReport() SchemaValidationReport {
	return SchemaValidationReport{
		SchemaVersion: CoreSchemaVersion,
		Valid:         true,
		Issues:        []SchemaValidationIssue{},
	}
}

func (r *SchemaValidationReport) addError(field, code, message string) {
	r.addIssue(SchemaValidationIssue{
		Field:    field,
		Code:     code,
		Message:  message,
		Severity: "error",
	})
}

func (r *SchemaValidationReport) addWarning(field, code, message string) {
	r.addIssue(SchemaValidationIssue{
		Field:    field,
		Code:     code,
		Message:  message,
		Severity: "warning",
	})
}

func (r *SchemaValidationReport) addIssue(issue SchemaValidationIssue) {
	r.Issues = append(r.Issues, issue)
	if issue.Severity == "error" {
		r.Valid = false
	}
}

func schemaCheckText(
	report *SchemaValidationReport,
	field string,
	value string,
	maxBytes int,
	required bool,
	singleLine bool,
) {
	if !utf8.ValidString(value) {
		report.addError(field, "invalid_utf8", "Value is not valid UTF-8.")
		return
	}

	if required && strings.TrimSpace(value) == "" {
		report.addError(field, "required", "A non-empty value is required.")
		return
	}

	if len(value) > maxBytes {
		report.addError(field, "too_long", "Value exceeds the permitted size.")
		return
	}

	for _, r := range value {
		if !unicode.IsControl(r) {
			continue
		}

		if !singleLine && (r == '\n' || r == '\r' || r == '\t') {
			continue
		}

		report.addError(field, "invalid_control_character", "Value contains unsupported control characters.")
		return
	}
}

func schemaCheckStringList(
	report *SchemaValidationReport,
	field string,
	values []string,
	unique bool,
) {
	if len(values) > SchemaMaxListItems {
		report.addError(field, "too_many_items", "List exceeds the permitted item count.")
		return
	}

	seen := make(map[string]struct{}, len(values))

	for i, value := range values {
		itemField := fmt.Sprintf("%s[%d]", field, i)

		schemaCheckText(
			report,
			itemField,
			value,
			SchemaMaxMetadataBytes,
			true,
			true,
		)

		if !unique {
			continue
		}

		key := strings.ToLower(strings.TrimSpace(value))
		if key == "" {
			continue
		}

		if _, exists := seen[key]; exists {
			report.addWarning(itemField, "duplicate_item", "List contains a duplicate value.")
			continue
		}

		seen[key] = struct{}{}
	}
}

func schemaCheckCountry(report *SchemaValidationReport, country string) {
	if strings.TrimSpace(country) == "" {
		return
	}

	if len(country) != 2 && len(country) != 3 {
		report.addError(
			"country",
			"invalid_country_code",
			"Country code must contain two or three ASCII letters.",
		)
		return
	}

	for _, r := range country {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') {
			report.addError(
				"country",
				"invalid_country_code",
				"Country code must contain ASCII letters only.",
			)
			return
		}
	}
}

func schemaCheckLanguage(report *SchemaValidationReport, language string) {
	if strings.TrimSpace(language) == "" {
		return
	}

	if len(language) > 35 {
		report.addError("language", "invalid_language", "Language identifier exceeds the permitted size.")
		return
	}

	for i, r := range language {
		valid := r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			(i > 0 && r == '-')

		if !valid {
			report.addError(
				"language",
				"invalid_language",
				"Language identifier must use ASCII letters, digits, and valid hyphen-separated subtags.",
			)
			return
		}
	}

	if strings.HasPrefix(language, "-") || strings.HasSuffix(language, "-") ||
		strings.Contains(language, "--") {
		report.addError("language", "invalid_language", "Language subtags are malformed.")
	}
}

func schemaCheckCurrency(report *SchemaValidationReport, currency string) {
	if strings.TrimSpace(currency) == "" {
		return
	}

	if len(currency) != 3 {
		report.addError(
			"currency",
			"invalid_currency",
			"Currency code must contain three ASCII letters.",
		)
		return
	}

	for _, r := range currency {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') {
			report.addError(
				"currency",
				"invalid_currency",
				"Currency code must contain ASCII letters only.",
			)
			return
		}
	}
}

func schemaCheckURL(report *SchemaValidationReport, field, raw string) {
	if strings.TrimSpace(raw) == "" {
		report.addError(field, "required", "A non-empty URL is required.")
		return
	}

	if len(raw) > SchemaMaxSourceURLBytes {
		report.addError(field, "url_too_long", "URL exceeds the permitted size.")
		return
	}

	u, err := url.ParseRequestURI(raw)
	if err != nil || u.Host == "" ||
		(u.Scheme != "https" && u.Scheme != "http") ||
		u.User != nil {
		report.addError(
			field,
			"invalid_url",
			"URL must be a valid HTTP or HTTPS URL without embedded credentials.",
		)
	}
}

func schemaValidResourceName(name string) bool {
	if name == "" || len(name) > SchemaMaxNameBytes || name == "." || name == ".." {
		return false
	}

	for _, r := range name {
		if !(r >= 'a' && r <= 'z' ||
			r >= '0' && r <= '9' ||
			r == '_' ||
			r == '-') {
			return false
		}
	}

	return true
}

func schemaValidEventType(value string) bool {
	for _, r := range value {
		if !(r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			r == '_' ||
			r == '-' ||
			r == '.') {
			return false
		}
	}
	return value != ""
}
