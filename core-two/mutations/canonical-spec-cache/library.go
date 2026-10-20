package candidate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"
)

const CandidateID = "canonical-spec-cache"

const (
	CanonicalSchemaVersion = 1
	MaxCanonicalSpecBytes  = 2 << 20
	MaxBOMBytes            = 1 << 20
	MaxListItems           = 128
	MaxMapEntries          = 100
	MaxCacheEntries        = 1024

	maxNameBytes         = 64
	maxTitleBytes        = 200
	maxDemandBytes       = 4000
	maxPurposeBytes      = 2000
	maxMetadataBytes     = 500
	maxModelNoteBytes    = 1000
	maxFrequencyBytes    = 80
	maxBOMDepth          = 64
	maxBOMNodes          = 10000
)

var (
	ErrInvalidFingerprint = errors.New("invalid canonical fingerprint")
	ErrCacheFull          = errors.New("canonical specification cache is full")
	ErrCacheIntegrity     = errors.New("cached specification failed integrity verification")
	ErrFingerprintCollision = errors.New("fingerprint collision: canonical bytes differ")
)

// ToolSpec mirrors Core-One's genesis.ToolSpec JSON contract. Keep this
// candidate structurally aligned with Core-One, but do not import or execute
// Core-One generated source from this proposal-only package.
type ToolSpec struct {
	Name              string         `json:"name"`
	Title             string         `json:"title"`
	Demand            string         `json:"demand"`
	Purpose           string         `json:"purpose"`
	Category          string         `json:"category"`
	Industry          string         `json:"industry"`
	Capabilities      []string       `json:"capabilities"`
	Inputs            []string       `json:"inputs"`
	Outputs           []string       `json:"outputs"`
	Safeguards        []string       `json:"safeguards"`
	NeedsHardwareGuide bool          `json:"needs_hardware_guide"`
	Country           string         `json:"country,omitempty"`
	CountryName       string         `json:"country_name,omitempty"`
	Language          string         `json:"language,omitempty"`
	Currency          string         `json:"currency,omitempty"`
	SupplierDirectory []string       `json:"supplier_directory,omitempty"`
	NominalACVoltage  int            `json:"nominal_ac_voltage_v,omitempty"`
	FrequencyHz       string         `json:"frequency_hz,omitempty"`
	LocalAdaptations  []string       `json:"local_adaptations,omitempty"`
	LegalFrameworks   []string       `json:"legal_framework_awareness,omitempty"`
	BOM               map[string]any `json:"bom,omitempty"`
	ModelAssisted     bool           `json:"model_assisted"`
	ModelNote         string         `json:"model_note,omitempty"`
}

type canonicalEnvelope struct {
	SchemaVersion int      `json:"schema_version"`
	Spec          ToolSpec `json:"spec"`
}

// CanonicalMapJSON returns bounded deterministic JSON for the legacy
// map-based fingerprint API. Go's JSON encoder sorts string map keys.
func CanonicalMapJSON(v map[string]string) ([]byte, error) {
	if len(v) > MaxMapEntries {
		return nil, fmt.Errorf("map exceeds %d entries", MaxMapEntries)
	}

	normalized := make(map[string]string, len(v))
	for key, value := range v {
		if !utf8.ValidString(key) || !utf8.ValidString(value) {
			return nil, errors.New("map contains invalid UTF-8")
		}
		if strings.TrimSpace(key) == "" || len(key) > maxNameBytes*4 {
			return nil, errors.New("map key is empty or too long")
		}
		if len(value) > maxDemandBytes {
			return nil, errors.New("map value exceeds the permitted size")
		}
		if containsUnsupportedControl(key, false) || containsUnsupportedControl(value, true) {
			return nil, errors.New("map contains unsupported control characters")
		}
		normalized[key] = value
	}

	raw, err := json.Marshal(normalized)
	if err != nil {
		return nil, fmt.Errorf("marshal canonical map: %w", err)
	}
	if len(raw) > MaxCanonicalSpecBytes {
		return nil, errors.New("canonical map exceeds the permitted serialized size")
	}
	return raw, nil
}

// Fingerprint preserves the original API. Invalid or unbounded input returns
// an empty fingerprint; callers needing an explanation should use
// CanonicalMapJSON and handle its error.
func Fingerprint(v map[string]string) string {
	raw, err := CanonicalMapJSON(v)
	if err != nil {
		return ""
	}
	return fingerprintBytes(raw)
}

// ValidateToolSpec applies the deterministic size and shape limits used by
// Core-One's ToolSpec contract, with fail-closed checks for cache input.
func ValidateToolSpec(spec ToolSpec) error {
	if err := checkText("name", spec.Name, maxNameBytes, true, true); err != nil {
		return err
	}
	if !validResourceName(spec.Name) {
		return errors.New("name must contain lowercase ASCII letters, digits, hyphens, or underscores")
	}
	if err := checkText("title", spec.Title, maxTitleBytes, true, true); err != nil {
		return err
	}
	if err := checkText("demand", spec.Demand, maxDemandBytes, true, false); err != nil {
		return err
	}
	if err := checkText("purpose", spec.Purpose, maxPurposeBytes, true, false); err != nil {
		return err
	}
	if err := checkText("category", spec.Category, maxMetadataBytes, false, true); err != nil {
		return err
	}
	if err := checkText("industry", spec.Industry, maxMetadataBytes, false, true); err != nil {
		return err
	}
	if err := checkText("country_name", spec.CountryName, maxTitleBytes, false, true); err != nil {
		return err
	}
	if err := checkText("frequency_hz", spec.FrequencyHz, maxFrequencyBytes, false, true); err != nil {
		return err
	}
	if err := checkText("model_note", spec.ModelNote, maxModelNoteBytes, false, false); err != nil {
		return err
	}

	if spec.Country != "" && !validCountryCode(spec.Country) {
		return errors.New("country must contain two or three ASCII letters")
	}
	if spec.Language != "" && !validLanguage(spec.Language) {
		return errors.New("language must use valid ASCII language subtags")
	}
	if spec.Currency != "" && !validCurrency(spec.Currency) {
		return errors.New("currency must contain three ASCII letters")
	}
	if spec.NominalACVoltage < 0 {
		return errors.New("nominal AC voltage cannot be negative")
	}
	if spec.NeedsHardwareGuide && len(spec.Safeguards) == 0 {
		return errors.New("hardware-related tool specs require explicit safeguards")
	}
	if spec.ModelAssisted && strings.TrimSpace(spec.ModelNote) == "" {
		return errors.New("model-assisted tool specs require a model note")
	}

	for _, list := range []struct {
		name   string
		values []string
	}{
		{name: "capabilities", values: spec.Capabilities},
		{name: "inputs", values: spec.Inputs},
		{name: "outputs", values: spec.Outputs},
		{name: "safeguards", values: spec.Safeguards},
		{name: "supplier_directory", values: spec.SupplierDirectory},
		{name: "local_adaptations", values: spec.LocalAdaptations},
		{name: "legal_framework_awareness", values: spec.LegalFrameworks},
	} {
		if err := validateStringList(list.name, list.values); err != nil {
			return err
		}
	}

	if len(spec.BOM) > 0 {
		nodes := 0
		if err := validateJSONValue(reflect.ValueOf(spec.BOM), 0, &nodes); err != nil {
			return fmt.Errorf("invalid BOM: %w", err)
		}
		raw, err := json.Marshal(spec.BOM)
		if err != nil {
			return fmt.Errorf("BOM is not JSON serializable: %w", err)
		}
		if len(raw) > MaxBOMBytes {
			return errors.New("BOM exceeds the permitted serialized size")
		}
	}
	return nil
}

// CanonicalSpecJSON validates and serializes a Core-One-shaped ToolSpec.
// It uses a versioned envelope so a future schema change cannot silently share
// fingerprints with this schema. Nil list fields are normalized to empty
// arrays; the order of non-nil list items is preserved.
func CanonicalSpecJSON(spec ToolSpec) ([]byte, error) {
	if err := ValidateToolSpec(spec); err != nil {
		return nil, err
	}

	spec = normalizeNilLists(spec)
	raw, err := json.Marshal(canonicalEnvelope{
		SchemaVersion: CanonicalSchemaVersion,
		Spec:          spec,
	})
	if err != nil {
		return nil, fmt.Errorf("marshal canonical tool spec: %w", err)
	}
	if len(raw) > MaxCanonicalSpecBytes {
		return nil, errors.New("canonical tool spec exceeds the permitted serialized size")
	}
	return raw, nil
}

// FingerprintToolSpec fingerprints the complete validated tool specification,
// including safeguards, hardware/localization metadata, and BOM contents.
func FingerprintToolSpec(spec ToolSpec) (string, error) {
	raw, err := CanonicalSpecJSON(spec)
	if err != nil {
		return "", err
	}
	return fingerprintBytes(raw), nil
}

// SpecCache is a bounded, concurrency-safe in-memory cache of canonical
// tool specifications. It has no filesystem/network access, performs no
// source execution, and never activates or merges generated tools.
type SpecCache struct {
	mu      sync.RWMutex
	limit   int
	entries map[string][]byte
}

// NewSpecCache creates a cache with an explicit capacity to prevent unbounded
// memory growth. There is no eviction: once full, new unique entries fail.
func NewSpecCache(maxEntries int) (*SpecCache, error) {
	if maxEntries < 1 || maxEntries > MaxCacheEntries {
		return nil, fmt.Errorf("cache capacity must be between 1 and %d", MaxCacheEntries)
	}
	return &SpecCache{
		limit:   maxEntries,
		entries: make(map[string][]byte, maxEntries),
	}, nil
}

// Put stores a validated tool spec. inserted is false for an exact cache hit.
func (c *SpecCache) Put(spec ToolSpec) (fingerprint string, inserted bool, err error) {
	if c == nil {
		return "", false, errors.New("cache is nil")
	}
	raw, err := CanonicalSpecJSON(spec)
	if err != nil {
		return "", false, err
	}
	fingerprint = fingerprintBytes(raw)

	c.mu.Lock()
	defer c.mu.Unlock()

	if previous, ok := c.entries[fingerprint]; ok {
		if !equalBytes(previous, raw) {
			return "", false, ErrFingerprintCollision
		}
		return fingerprint, false, nil
	}
	if len(c.entries) >= c.limit {
		return "", false, ErrCacheFull
	}
	c.entries[fingerprint] = append([]byte(nil), raw...)
	return fingerprint, true, nil
}

// Lookup returns a copy of the cached canonical bytes after verifying that
// the requested key is a lowercase SHA-256 hex digest and matches the bytes.
func (c *SpecCache) Lookup(fingerprint string) ([]byte, bool, error) {
	if c == nil {
		return nil, false, errors.New("cache is nil")
	}
	if len(fingerprint) != sha256.Size*2 ||
		fingerprint != strings.ToLower(fingerprint) {
		return nil, false, ErrInvalidFingerprint
	}
	if _, err := hex.DecodeString(fingerprint); err != nil {
		return nil, false, ErrInvalidFingerprint
	}

	c.mu.RLock()
	raw, ok := c.entries[fingerprint]
	if ok {
		raw = append([]byte(nil), raw...)
	}
	c.mu.RUnlock()

	if !ok {
		return nil, false, nil
	}
	if fingerprintBytes(raw) != fingerprint {
		return nil, false, ErrCacheIntegrity
	}
	return raw, true, nil
}

// Len reports the current number of cached entries.
func (c *SpecCache) Len() int {
	if c == nil {
		return 0
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.entries)
}

// Validate runs deterministic, offline fixture checks for the candidate.
func Validate() error {
	left := map[string]string{"b": "2", "a": "1"}
	right := map[string]string{"a": "1", "b": "2"}
	if Fingerprint(left) == "" || Fingerprint(left) != Fingerprint(right) {
		return errors.New("unstable canonical map fingerprint")
	}

	spec := fixtureToolSpec()
	first, err := FingerprintToolSpec(spec)
	if err != nil {
		return fmt.Errorf("fingerprint fixture tool spec: %w", err)
	}
	second, err := FingerprintToolSpec(spec)
	if err != nil || first == "" || first != second {
		return errors.New("unstable canonical tool-spec fingerprint")
	}

	cache, err := NewSpecCache(2)
	if err != nil {
		return err
	}
	key, inserted, err := cache.Put(spec)
	if err != nil || !inserted || key != first {
		return errors.New("first cache insert failed")
	}
	key, inserted, err = cache.Put(spec)
	if err != nil || inserted || key != first {
		return errors.New("identical tool spec was not deduplicated")
	}
	if _, ok, err := cache.Lookup(first); err != nil || !ok {
		return errors.New("cached tool spec could not be verified")
	}
	return nil
}

func fixtureToolSpec() ToolSpec {
	return ToolSpec{
		Name:         "offline_file_vault",
		Title:        "Offline File Vault",
		Demand:       "Create tool: offline file vault",
		Purpose:      "A reviewable software tool scaffold for bounded local file operations.",
		Category:     "software",
		Industry:     "digital",
		Capabilities: []string{"validate structured input", "record traceable evidence"},
		Inputs:       []string{"action", "structured_inputs", "consent"},
		Outputs:      []string{"status", "plan_summary", "evidence_references"},
		Safeguards:   []string{"human review before activation", "least-privilege integration"},
		BOM: map[string]any{
			"status": "not_applicable",
			"items":  []any{},
		},
	}
}

func normalizeNilLists(spec ToolSpec) ToolSpec {
	if spec.Capabilities == nil {
		spec.Capabilities = []string{}
	} else {
		spec.Capabilities = append([]string{}, spec.Capabilities...)
	}
	if spec.Inputs == nil {
		spec.Inputs = []string{}
	} else {
		spec.Inputs = append([]string{}, spec.Inputs...)
	}
	if spec.Outputs == nil {
		spec.Outputs = []string{}
	} else {
		spec.Outputs = append([]string{}, spec.Outputs...)
	}
	if spec.Safeguards == nil {
		spec.Safeguards = []string{}
	} else {
		spec.Safeguards = append([]string{}, spec.Safeguards...)
	}
	if spec.SupplierDirectory == nil {
		spec.SupplierDirectory = []string{}
	} else {
		spec.SupplierDirectory = append([]string{}, spec.SupplierDirectory...)
	}
	if spec.LocalAdaptations == nil {
		spec.LocalAdaptations = []string{}
	} else {
		spec.LocalAdaptations = append([]string{}, spec.LocalAdaptations...)
	}
	if spec.LegalFrameworks == nil {
		spec.LegalFrameworks = []string{}
	} else {
		spec.LegalFrameworks = append([]string{}, spec.LegalFrameworks...)
	}
	return spec
}

func checkText(field, value string, maxBytes int, required, singleLine bool) error {
	if !utf8.ValidString(value) {
		return fmt.Errorf("%s is not valid UTF-8", field)
	}
	if required && strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s is required", field)
	}
	if len(value) > maxBytes {
		return fmt.Errorf("%s exceeds %d bytes", field, maxBytes)
	}
	if containsUnsupportedControl(value, !singleLine) {
		return fmt.Errorf("%s contains unsupported control characters", field)
	}
	return nil
}

func containsUnsupportedControl(value string, allowLineBreaks bool) bool {
	for _, r := range value {
		if !unicode.IsControl(r) {
			continue
		}
		if allowLineBreaks && (r == '\n' || r == '\r' || r == '\t') {
			continue
		}
		return true
	}
	return false
}

func validateStringList(field string, values []string) error {
	if len(values) > MaxListItems {
		return fmt.Errorf("%s exceeds %d items", field, MaxListItems)
	}
	for i, value := range values {
		if err := checkText(fmt.Sprintf("%s[%d]", field, i), value, maxMetadataBytes, true, true); err != nil {
			return err
		}
	}
	return nil
}

func validateJSONValue(value reflect.Value, depth int, nodes *int) error {
	if !value.IsValid() {
		return nil
	}
	if depth > maxBOMDepth {
		return errors.New("JSON nesting exceeds the permitted depth")
	}
	(*nodes)++
	if *nodes > maxBOMNodes {
		return errors.New("JSON value exceeds the permitted node count")
	}

	switch value.Kind() {
	case reflect.Interface, reflect.Pointer:
		if value.IsNil() {
			return nil
		}
		return validateJSONValue(value.Elem(), depth+1, nodes)
	case reflect.String:
		text := value.String()
		if !utf8.ValidString(text) {
			return errors.New("JSON value contains invalid UTF-8")
		}
		if len(text) > MaxBOMBytes {
			return errors.New("JSON string exceeds the permitted size")
		}
	case reflect.Bool,
		reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return nil
	case reflect.Float32, reflect.Float64:
		number := value.Float()
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return errors.New("JSON number must be finite")
		}
	case reflect.Map:
		if value.IsNil() {
			return nil
		}
		if value.Type().Key().Kind() != reflect.String {
			return errors.New("JSON objects must use string keys")
		}
		if value.Len() > maxBOMNodes {
			return errors.New("JSON object exceeds the permitted entry count")
		}
		iter := value.MapRange()
		for iter.Next() {
			key := iter.Key().String()
			if !utf8.ValidString(key) {
				return errors.New("JSON object key contains invalid UTF-8")
			}
			if len(key) > maxMetadataBytes {
				return errors.New("JSON object key exceeds the permitted size")
			}
			if err := validateJSONValue(iter.Value(), depth+1, nodes); err != nil {
				return err
			}
		}
	case reflect.Slice, reflect.Array:
		if value.Len() > maxBOMNodes {
			return errors.New("JSON array exceeds the permitted item count")
		}
		for i := 0; i < value.Len(); i++ {
			if err := validateJSONValue(value.Index(i), depth+1, nodes); err != nil {
				return err
			}
		}
	default:
		return fmt.Errorf("unsupported JSON value type %s", value.Type())
	}
	return nil
}

func validResourceName(name string) bool {
	if name == "" || len(name) > maxNameBytes {
		return false
	}
	for _, r := range name {
		if !(r >= 'a' && r <= 'z' ||
			r >= '0' && r <= '9' ||
			r == '_' || r == '-') {
			return false
		}
	}
	return true
}

func validCountryCode(country string) bool {
	if len(country) != 2 && len(country) != 3 {
		return false
	}
	for _, r := range country {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') {
			return false
		}
	}
	return true
}

func validLanguage(language string) bool {
	if len(language) > 35 || language == "" ||
		strings.HasPrefix(language, "-") ||
		strings.HasSuffix(language, "-") ||
		strings.Contains(language, "--") {
		return false
	}
	for i, r := range language {
		valid := r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			(i > 0 && r == '-')
		if !valid {
			return false
		}
	}
	return true
}

func validCurrency(currency string) bool {
	if len(currency) != 3 {
		return false
	}
	for _, r := range currency {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z') {
			return false
		}
	}
	return true
}

func fingerprintBytes(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func equalBytes(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
