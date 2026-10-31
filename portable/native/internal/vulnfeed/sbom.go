package vulnfeed

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

const MaxSBOMDepth = 32

type SBOMImportResult struct {
	Manifest Manifest
	Skipped int
	Warnings []string
}

type cyclonedxBOM struct {
	BOMFormat string `json:"bomFormat"`
	SpecVersion string `json:"specVersion"`
	Metadata struct {
		Timestamp string `json:"timestamp"`
		Tools json.RawMessage `json:"tools"`
	} `json:"metadata"`
	Components []cyclonedxComponent `json:"components"`
}

type cyclonedxComponent struct {
	Type string `json:"type"`
	Group string `json:"group"`
	Name string `json:"name"`
	Version string `json:"version"`
	PURL string `json:"purl"`
	Components []cyclonedxComponent `json:"components"`
}

type spdxDocument struct {
	SPDXVersion string `json:"spdxVersion"`
	Name string `json:"name"`
	CreationInfo struct {
		Created string `json:"created"`
		Creators []string `json:"creators"`
	} `json:"creationInfo"`
	Packages []spdxPackage `json:"packages"`
}

type spdxPackage struct {
	Name string `json:"name"`
	VersionInfo string `json:"versionInfo"`
	ExternalRefs []struct {
		ReferenceCategory string `json:"referenceCategory"`
		ReferenceType string `json:"referenceType"`
		ReferenceLocator string `json:"referenceLocator"`
	} `json:"externalRefs"`
}

// NormalizePURL removes an optional @version suffix from the final package
// coordinate while preserving qualifiers and subpath. It does not attempt to
// reinterpret or canonicalize package namespaces.
func NormalizePURL(raw string) (string, error) {
	value := strings.TrimSpace(raw)
	if !strings.HasPrefix(value, "pkg:") || len(value) > 1024 {
		return "", errors.New("a valid-looking Package URL is required")
	}
	if strings.ContainsAny(value, "\r\n\x00") {
		return "", errors.New("Package URL contains control characters")
	}
	base := value
	fragment := ""
	if index := strings.IndexByte(base, '#'); index >= 0 {
		fragment = base[index:]
		base = base[:index]
	}
	query := ""
	if index := strings.IndexByte(base, '?'); index >= 0 {
		query = base[index:]
		base = base[:index]
	}
	lastSlash := strings.LastIndexByte(base, '/')
	lastAt := strings.LastIndexByte(base, '@')
	if lastAt > lastSlash {
		base = base[:lastAt]
	}
	if len(base) <= len("pkg:") {
		return "", errors.New("Package URL has no package coordinate")
	}
	normalized := base + query + fragment
	if len(normalized) > 512 {
		return "", errors.New("normalized Package URL exceeds 512 bytes")
	}
	return normalized, nil
}

func ecosystemFromPURL(value string) string {
	if !strings.HasPrefix(value, "pkg:") {
		return ""
	}
	rest := strings.TrimPrefix(value, "pkg:")
	if index := strings.IndexAny(rest, "/?#"); index >= 0 {
		return rest[:index]
	}
	return rest
}

func parseTimestamp(value string) (time.Time, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, errors.New("SBOM creation timestamp is required")
	}
	result, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid SBOM creation timestamp: %w", err)
	}
	return result.UTC(), nil
}

// ParseCycloneDXJSON imports common CycloneDX JSON BOM component records.
// It accepts specification versions 1.4 through 1.7; unknown component fields
// are ignored, and components without purl or version are counted as skipped.
func ParseCycloneDXJSON(data []byte) (SBOMImportResult, error) {
	if len(data) == 0 || len(data) > MaxManifestBytes {
		return SBOMImportResult{}, errors.New("CycloneDX JSON must be between 1 byte and 10 MiB")
	}
	var bom cyclonedxBOM
	if err := json.Unmarshal(data, &bom); err != nil {
		return SBOMImportResult{}, fmt.Errorf("decode CycloneDX JSON: %w", err)
	}
	if bom.BOMFormat != "CycloneDX" {
		return SBOMImportResult{}, errors.New("bomFormat must be CycloneDX")
	}
	switch bom.SpecVersion {
	case "1.4", "1.5", "1.6", "1.7":
	default:
		return SBOMImportResult{}, fmt.Errorf("unsupported CycloneDX specVersion %q (supported 1.4-1.7)", bom.SpecVersion)
	}
	generatedAt, err := parseTimestamp(bom.Metadata.Timestamp)
	if err != nil {
		return SBOMImportResult{}, err
	}
	source := "CycloneDX " + bom.SpecVersion
	if len(bom.Metadata.Tools) > 0 && string(bom.Metadata.Tools) != "null" {
		type legacyTool struct {
			Vendor string `json:"vendor"`
			Name string `json:"name"`
			Version string `json:"version"`
		}
		type toolComponent struct {
			Name string `json:"name"`
			Version string `json:"version"`
		}
		type toolSet struct {
			Components []toolComponent `json:"components"`
		}
		tools := []legacyTool{}
		var structured toolSet
		if len(bom.Metadata.Tools) > 0 && bom.Metadata.Tools[0] == '[' {
			if err := json.Unmarshal(bom.Metadata.Tools, &tools); err != nil {
				return SBOMImportResult{}, fmt.Errorf("decode CycloneDX legacy tools: %w", err)
			}
		} else if len(bom.Metadata.Tools) > 0 && bom.Metadata.Tools[0] == '{' {
			if err := json.Unmarshal(bom.Metadata.Tools, &structured); err != nil {
				return SBOMImportResult{}, fmt.Errorf("decode CycloneDX tools object: %w", err)
			}
			for _, component := range structured.Components {
				tools = append(tools, legacyTool{Name: component.Name, Version: component.Version})
			}
		} else {
			return SBOMImportResult{}, errors.New("CycloneDX metadata.tools must be an object or legacy array")
		}
		if len(tools) > 0 {
			tool := tools[0]
			parts := []string{}
			if strings.TrimSpace(tool.Vendor) != "" { parts = append(parts, strings.TrimSpace(tool.Vendor)) }
			if strings.TrimSpace(tool.Name) != "" { parts = append(parts, strings.TrimSpace(tool.Name)) }
			if strings.TrimSpace(tool.Version) != "" { parts = append(parts, strings.TrimSpace(tool.Version)) }
			if len(parts) > 0 { source = strings.Join(parts, " ") + " (CycloneDX " + bom.SpecVersion + ")" }
		}
	}
	result := SBOMImportResult{
		Manifest: Manifest{SchemaVersion: ManifestSchema, GeneratedAt: generatedAt, Source: source, Packages: []Package{}},
		Warnings: []string{},
	}
	seen := map[string]struct{}{}
	var visit func([]cyclonedxComponent, int) error
	visit = func(components []cyclonedxComponent, depth int) error {
		if depth > MaxSBOMDepth {
			return errors.New("CycloneDX component nesting exceeds 32 levels")
		}
		for _, component := range components {
			if strings.TrimSpace(component.PURL) == "" || strings.TrimSpace(component.Version) == "" {
				result.Skipped++
				continue
			}
			purl, normalizeErr := NormalizePURL(component.PURL)
			if normalizeErr != nil {
				result.Skipped++
				result.Warnings = append(result.Warnings, "Skipped component with invalid purl: "+limitWarning(component.Name))
				continue
			}
			name := strings.TrimSpace(component.Name)
			if name == "" { name = strings.TrimSpace(component.Group) }
			ecosystem := ecosystemFromPURL(purl)
			if name == "" || ecosystem == "" || len(component.Version) > 128 {
				result.Skipped++
				continue
			}
			key := purl + "|" + component.Version
			if _, ok := seen[key]; !ok {
				seen[key] = struct{}{}
				result.Manifest.Packages = append(result.Manifest.Packages, Package{
					Ecosystem: ecosystem, Name: name, Version: component.Version, PackageURL: purl,
				})
			}
			if err := visit(component.Components, depth+1); err != nil { return err }
		}
		return nil
	}
	if err := visit(bom.Components, 0); err != nil {
		return SBOMImportResult{}, err
	}
	if len(result.Manifest.Packages) == 0 {
		return SBOMImportResult{}, errors.New("CycloneDX BOM contained no components with both purl and version")
	}
	return result, nil
}

// ParseSPDXJSON imports SPDX 2.3 JSON package records with a PACKAGE-MANAGER
// external reference of type purl. It does not infer a PURL from package names.
func ParseSPDXJSON(data []byte) (SBOMImportResult, error) {
	if len(data) == 0 || len(data) > MaxManifestBytes {
		return SBOMImportResult{}, errors.New("SPDX JSON must be between 1 byte and 10 MiB")
	}
	var doc spdxDocument
	if err := json.Unmarshal(data, &doc); err != nil {
		return SBOMImportResult{}, fmt.Errorf("decode SPDX JSON: %w", err)
	}
	if doc.SPDXVersion != "SPDX-2.3" {
		return SBOMImportResult{}, fmt.Errorf("unsupported SPDX version %q (expected SPDX-2.3)", doc.SPDXVersion)
	}
	generatedAt, err := parseTimestamp(doc.CreationInfo.Created)
	if err != nil { return SBOMImportResult{}, err }
	source := "SPDX-2.3"
	if strings.TrimSpace(doc.Name) != "" { source += " " + strings.TrimSpace(doc.Name) }
	if len(doc.CreationInfo.Creators) > 0 { source += " (" + strings.Join(doc.CreationInfo.Creators, "; ") + ")" }
	result := SBOMImportResult{
		Manifest: Manifest{SchemaVersion: ManifestSchema, GeneratedAt: generatedAt, Source: source, Packages: []Package{}},
		Warnings: []string{},
	}
	seen := map[string]struct{}{}
	for _, item := range doc.Packages {
		var purlRaw string
		for _, ref := range item.ExternalRefs {
			if strings.EqualFold(ref.ReferenceCategory, "PACKAGE-MANAGER") && strings.EqualFold(ref.ReferenceType, "purl") {
				purlRaw = strings.TrimSpace(ref.ReferenceLocator)
				break
			}
		}
		if purlRaw == "" || item.VersionInfo == "" || strings.EqualFold(item.VersionInfo, "NOASSERTION") || strings.EqualFold(item.VersionInfo, "NONE") {
			result.Skipped++
			continue
		}
		purl, normalizeErr := NormalizePURL(purlRaw)
		if normalizeErr != nil {
			result.Skipped++
			result.Warnings = append(result.Warnings, "Skipped SPDX package with invalid purl: "+limitWarning(item.Name))
			continue
		}
		name := strings.TrimSpace(item.Name)
		ecosystem := ecosystemFromPURL(purl)
		if name == "" || ecosystem == "" || len(item.VersionInfo) > 128 {
			result.Skipped++
			continue
		}
		key := purl + "|" + item.VersionInfo
		if _, ok := seen[key]; ok { continue }
		seen[key] = struct{}{}
		result.Manifest.Packages = append(result.Manifest.Packages, Package{
			Ecosystem: ecosystem, Name: name, Version: item.VersionInfo, PackageURL: purl,
		})
	}
	if len(result.Manifest.Packages) == 0 {
		return SBOMImportResult{}, errors.New("SPDX document contained no packages with PACKAGE-MANAGER purl references and exact versions")
	}
	return result, nil
}

func limitWarning(value string) string {
	value = strings.TrimSpace(value)
	if len(value) > 80 { return value[:80] }
	return value
}
