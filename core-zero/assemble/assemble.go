// Package assemble creates reviewable, offline artifacts from a versioned
// curated-template registry.
//
// This package does not connect to hardware, access a network, flash
// firmware, execute generated scripts, or certify a physical design.
package assemble

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	manifestSchemaVersion = "usect-zero.assembly-manifest.v1"

	maxTargetBytes      = 64
	maxVersionBytes     = 64
	maxTitleBytes       = 200
	maxDescriptionBytes = 4096
	maxSafetyNotes      = 100
	maxParts            = 200
	maxConnections      = 256
	maxPartNameBytes    = 256
	maxPartCategory     = 96
	maxPartNotesBytes   = 2048
	maxPinLabelBytes    = 128
	maxSignalBytes      = 128
	maxConnectionNotes  = 2048
	maxDatasourceBytes  = 2048
	maxArtifactBytes    = 4 << 20 // 4 MiB per generated artifact.
	maxTotalArtifactBytes = 12 << 20
)

type Part struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Quantity int    `json:"quantity"`
	Category string `json:"category"`
	Notes    string `json:"notes"`
}

type Connection struct {
	FromPartID string `json:"from_part_id"`
	FromPin    string `json:"from_pin"`
	ToPartID   string `json:"to_part_id"`
	ToPin      string `json:"to_pin"`
	Signal     string `json:"signal"`
	WireColor  string `json:"wire_color"`
	Notes      string `json:"notes"`
}

type BoardProfile struct {
	ID                    string `json:"id"`
	Family                string `json:"family"`
	LogicVoltageMV        int    `json:"logic_voltage_mv"`
	TypicalInputVoltageMV int    `json:"typical_input_voltage_mv"`
	PinMapStatus          string `json:"pin_map_status"`
	Notes                 string `json:"notes"`
	HardwareVerified      bool   `json:"hardware_verified"`
}

type ElectricalRequirements struct {
	SupplyMinMV                  int    `json:"supply_min_mv,omitempty"`
	SupplyMaxMV                  int    `json:"supply_max_mv,omitempty"`
	LogicMinMV                   int    `json:"logic_min_mv,omitempty"`
	LogicMaxMV                   int    `json:"logic_max_mv,omitempty"`
	DatasheetReference           string `json:"datasheet_reference,omitempty"`
	ManufacturerDatasheetReviewed bool  `json:"manufacturer_datasheet_reviewed"`
}

type Template struct {
	ID             string                 `json:"id"`
	Target         string                 `json:"target"`
	Version        string                 `json:"version"`
	Title          string                 `json:"title"`
	Description    string                 `json:"description"`
	BoardProfileID string                 `json:"board_profile_id"`
	Electrical     ElectricalRequirements `json:"electrical_requirements"`
	WiringPartID   string                 `json:"wiring_part_id"`
	Parts          []Part                 `json:"parts"`
	Connections    []Connection           `json:"connections"`
	SafetyNotes    []string               `json:"safety_notes"`
	ReviewOnly     bool                   `json:"review_only"`
}

type ValidationCheck struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Detail string `json:"detail"`
}

type Validation struct {
	Status                   string            `json:"status"`
	Valid                    bool              `json:"valid"`
	ElectricalReviewRequired bool              `json:"electrical_review_required"`
	Checks                   []ValidationCheck `json:"checks"`
}

type TemplateSummary struct {
	ID                      string `json:"id"`
	Target                  string `json:"target"`
	Version                 string `json:"version"`
	Title                   string `json:"title"`
	BoardProfileID          string `json:"board_profile_id"`
	PartCount               int    `json:"part_count"`
	ConnectionCount         int    `json:"connection_count"`
	ValidationStatus        string `json:"validation_status"`
	ElectricalReviewRequired bool  `json:"electrical_review_required"`
	HumanReviewRequired     bool   `json:"human_review_required"`
}

type Result struct {
	Target              string       `json:"target"`
	TemplateID          string       `json:"template_id,omitempty"`
	TemplateVersion     string       `json:"template_version,omitempty"`
	BoardProfileID      string       `json:"board_profile_id,omitempty"`
	Status              string       `json:"status"`
	Artifacts           []string     `json:"artifacts"`
	Parts               []Part       `json:"parts"`
	Connections         []Connection `json:"connections"`
	Validation          Validation   `json:"validation"`
	Cost                string       `json:"cost"`
	HumanReviewRequired bool         `json:"human_review_required"`
	SafetyNotes         []string     `json:"safety_notes"`
}

var (
	idPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)

	versionPattern = regexp.MustCompile(
		`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`,
	)

	colorPattern = regexp.MustCompile(`^#[0-9a-fA-F]{6}$`)
)

// The profiles are family-level references, not certified specifications.
// Pin maps and electrical compatibility must be checked against the exact
// board revision and the manufacturer's documentation.
var boardProfiles = []BoardProfile{
	{
		ID:                    "esp32-s3-generic",
		Family:                "ESP32-S3 development-board family",
		LogicVoltageMV:        3300,
		TypicalInputVoltageMV: 5000,
		PinMapStatus:          "exact_board_revision_required",
		Notes: "Generic family reference only. Input paths, regulators, " +
			"pin availability and connector layouts vary by board; use " +
			"the exact board manufacturer's documentation.",
		HardwareVerified: false,
	},
	{
		ID:                    "rp2040-pico-generic",
		Family:                "RP2040 / Pico-style development-board family",
		LogicVoltageMV:        3300,
		TypicalInputVoltageMV: 5000,
		PinMapStatus:          "exact_board_revision_required",
		Notes: "Generic family reference only. Confirm the specific board " +
			"revision, input path, regulator, GPIO assignment and " +
			"manufacturer documentation before connecting hardware.",
		HardwareVerified: false,
	},
}

var registry = []Template{
	{
		ID:      "esp32-sensor",
		Target:  "esp32-sensor",
		Version: "1.0.0",
		Title:   "ESP32-S3 + BME280 I2C sensor (review draft)",
		Description: "A generic offline example parts list and illustrative " +
			"I2C wiring diagram. Exact board pin assignments and electrical " +
			"compatibility are not verified.",
		BoardProfileID: "esp32-s3-generic",
		WiringPartID:   "jumper-wire",
		Parts: []Part{
			{
				ID:       "esp32-board",
				Name:     "ESP32-S3 development board",
				Quantity: 1,
				Category: "controller",
				Notes:    "Confirm exact board, USB connector, regulator and selected pin map.",
			},
			{
				ID:       "bme280-breakout",
				Name:     "BME280 I2C sensor breakout",
				Quantity: 1,
				Category: "sensor",
				Notes:    "Confirm voltage compatibility and breakout-board pin labels.",
			},
			{
				ID:       "jumper-wire",
				Name:     "3.3V-compatible jumper wires",
				Quantity: 4,
				Category: "wiring",
				Notes:    "Illustrative connection count only; choose wire type and insulation for the selected setup.",
			},
			{
				ID:       "prototype-board",
				Name:     "Breadboard or suitable prototyping board",
				Quantity: 1,
				Category: "mechanical",
				Notes:    "Check mechanical and electrical suitability.",
			},
			{
				ID:       "usb-cable",
				Name:     "USB data cable for selected board",
				Quantity: 1,
				Category: "power-data",
				Notes:    "Cable and connector vary by board revision.",
			},
		},
		Connections: []Connection{
			{
				FromPartID: "esp32-board",
				FromPin:    "3V3",
				ToPartID:   "bme280-breakout",
				ToPin:      "VIN / 3V3",
				Signal:     "POWER (check voltage)",
				WireColor:  "#e53935",
				Notes:      "Use only if the exact breakout supports the board's 3.3V supply.",
			},
			{
				FromPartID: "esp32-board",
				FromPin:    "GND",
				ToPartID:   "bme280-breakout",
				ToPin:      "GND",
				Signal:     "GROUND",
				WireColor:  "#424242",
				Notes:      "Confirm ground labels on the exact boards.",
			},
			{
				FromPartID: "esp32-board",
				FromPin:    "GPIO 8 (example SDA)",
				ToPartID:   "bme280-breakout",
				ToPin:      "SDA / SDI",
				Signal:     "I2C SDA (example)",
				WireColor:  "#1565c0",
				Notes:      "GPIO assignment is illustrative; verify board pin map and software configuration.",
			},
			{
				FromPartID: "esp32-board",
				FromPin:    "GPIO 9 (example SCL)",
				ToPartID:   "bme280-breakout",
				ToPin:      "SCL / SCK",
				Signal:     "I2C SCL (example)",
				WireColor:  "#2e7d32",
				Notes:      "GPIO assignment is illustrative; verify board pin map and software configuration.",
			},
		},
		SafetyNotes: []string{
			"No physical operation was performed and no hardware compatibility is certified.",
			"Verify every pin, supply voltage, pull-up arrangement and breakout datasheet before wiring.",
			"Part counts and wiring are an illustrative draft, not a supplier-verified bill of materials.",
		},
		ReviewOnly: true,
	},
}

// ListTemplates returns public metadata for the curated template registry.
func ListTemplates() []TemplateSummary {
	out := make([]TemplateSummary, 0, len(registry))

	for _, t := range registry {
		validation := ValidateTemplate(t)

		out = append(out, TemplateSummary{
			ID:                      t.ID,
			Target:                  t.Target,
			Version:                 t.Version,
			Title:                   t.Title,
			BoardProfileID:          t.BoardProfileID,
			PartCount:               len(t.Parts),
			ConnectionCount:         len(t.Connections),
			ValidationStatus:        validation.Status,
			ElectricalReviewRequired: validation.ElectricalReviewRequired,
			HumanReviewRequired:     true,
		})
	}

	sort.Slice(out, func(i, j int) bool {
		if out[i].Target == out[j].Target {
			return compareVersion(out[i].Version, out[j].Version) < 0
		}
		return out[i].Target < out[j].Target
	})

	return out
}

// ListBoardProfiles returns family-level reference profiles.
// The returned slice cannot be used to mutate the package registry.
func ListBoardProfiles() []BoardProfile {
	out := append([]BoardProfile{}, boardProfiles...)

	sort.Slice(out, func(i, j int) bool {
		return out[i].ID < out[j].ID
	})

	return out
}

func resolveBoardProfile(id string) (BoardProfile, bool) {
	for _, profile := range boardProfiles {
		if profile.ID == id {
			return profile, true
		}
	}

	return BoardProfile{}, false
}

// ValidateTemplate performs structural and policy checks on a template.
//
// A valid result means the template passed these checks. It does not certify
// an electrical design or establish that a physical board is compatible.
func ValidateTemplate(t Template) Validation {
	checks := make([]ValidationCheck, 0, 12)
	valid := true

	// Every curated template remains subject to human review.
	electricalReviewRequired := true

	add := func(name, status, detail string) {
		checks = append(checks, ValidationCheck{
			Name:   name,
			Status: status,
			Detail: detail,
		})
	}

	fail := func(name, detail string) {
		valid = false
		add(name, "failed", detail)
	}

	// 1. Template identity and bounded descriptive metadata.
	identityOK :=
		idPattern.MatchString(t.ID) &&
			idPattern.MatchString(t.Target) &&
			len(t.Version) <= maxVersionBytes &&
			versionPattern.MatchString(t.Version) &&
			validText(t.Title, maxTitleBytes) &&
			validText(t.Description, maxDescriptionBytes) &&
			idPattern.MatchString(t.BoardProfileID)

	if identityOK {
		add(
			"template_identity",
			"passed",
			"Template identifiers, version and descriptive metadata are well-formed.",
		)
	} else {
		fail(
			"template_identity",
			"Template ID, target and board profile must be valid slugs; version must be strict major.minor.patch; title and description must be valid and bounded.",
		)
	}

	// 2. Explicit non-execution policy.
	if t.ReviewOnly {
		add(
			"review_only_policy",
			"passed",
			"Template is explicitly marked review-only.",
		)
	} else {
		fail(
			"review_only_policy",
			"Template must be marked review-only.",
		)
	}

	// 3. Board profile resolution. A known generic profile is not a verified
	// board pin map and does not clear the electrical-review requirement.
	profile, profileFound := resolveBoardProfile(t.BoardProfileID)

	if !idPattern.MatchString(t.BoardProfileID) || !profileFound {
		fail(
			"board_profile",
			"Template must reference a registered board profile. Family profiles are not verified pin maps.",
		)
	} else {
		add(
			"board_profile",
			"review_required",
			fmt.Sprintf(
				"Registered family profile %s declares nominal logic voltage %d mV and typical input voltage %d mV. Exact board revision and pin map remain unverified.",
				profile.ID,
				profile.LogicVoltageMV,
				profile.TypicalInputVoltageMV,
			),
		)
	}

	// 4. Electrical requirements.
	e := t.Electrical

	noElectricalMetadata :=
		e.SupplyMinMV == 0 &&
			e.SupplyMaxMV == 0 &&
			e.LogicMinMV == 0 &&
			e.LogicMaxMV == 0 &&
			strings.TrimSpace(e.DatasheetReference) == "" &&
			!e.ManufacturerDatasheetReviewed

	if noElectricalMetadata {
		add(
			"electrical_compatibility",
			"review_required",
			"Exact supply and logic limits are not declared. Verify the chosen breakout, pull-ups, level shifting, pin map and manufacturer datasheet before wiring.",
		)
	} else {
		rangesValid :=
			e.SupplyMinMV > 0 &&
				e.SupplyMaxMV >= e.SupplyMinMV &&
				e.LogicMinMV > 0 &&
				e.LogicMaxMV >= e.LogicMinMV

		if !rangesValid {
			fail(
				"electrical_compatibility",
				"If electrical ranges are declared, both supply and logic limits must be present, positive and ordered minimum-to-maximum.",
			)
		} else if !profileFound {
			add(
				"electrical_compatibility",
				"review_required",
				"Voltage metadata is present, but the referenced board profile is unavailable; compatibility cannot be assessed.",
			)
		} else if profile.LogicVoltageMV < e.SupplyMinMV ||
			profile.LogicVoltageMV > e.SupplyMaxMV ||
			profile.LogicVoltageMV < e.LogicMinMV ||
			profile.LogicVoltageMV > e.LogicMaxMV {

			fail(
				"electrical_compatibility",
				"The family profile's nominal logic voltage falls outside a declared sensor supply or logic range. Do not treat this template as a compatible design.",
			)
		} else {
			referenceValid := validText(
				e.DatasheetReference,
				maxDatasourceBytes,
			)

			if !referenceValid || !e.ManufacturerDatasheetReviewed {
				add(
					"electrical_compatibility",
					"review_required",
					"Declared voltage ranges overlap the family profile, but a valid datasheet reference and manufacturer datasheet review are required.",
				)
			} else if !profile.HardwareVerified ||
				profile.PinMapStatus != "verified" {

				add(
					"electrical_compatibility",
					"review_required",
					"Voltage metadata and a datasheet-review declaration are present, but the family profile does not have a verified board revision and pin map. Electrical review remains mandatory.",
				)
			} else {
				// This branch is only available for a future profile explicitly
				// marked hardware-verified with a verified pin map.
				electricalReviewRequired = false

				add(
					"electrical_compatibility",
					"passed",
					"Declared voltage ranges and review metadata passed the profile checks. This is still not independent certification of the physical circuit.",
				)
			}
		}
	}

	// 5. Bill of materials.
	parts := make(map[string]Part)

	partOK := len(t.Parts) > 0 && len(t.Parts) <= maxParts

	if partOK {
		parts = make(map[string]Part, len(t.Parts))

		for _, p := range t.Parts {
			if !idPattern.MatchString(p.ID) ||
				!validText(p.Name, maxPartNameBytes) ||
				!validText(p.Category, maxPartCategory) ||
				!validText(p.Notes, maxPartNotesBytes) ||
				p.Quantity < 1 ||
				p.Quantity > 1000 {

				partOK = false
				break
			}

			if _, exists := parts[p.ID]; exists {
				partOK = false
				break
			}

			parts[p.ID] = p
		}
	}

	if partOK && len(parts) == len(t.Parts) {
		add(
			"parts",
			"passed",
			fmt.Sprintf(
				"%d uniquely identified BOM items have valid quantities and bounded descriptive fields.",
				len(parts),
			),
		)
	} else {
		fail(
			"parts",
			fmt.Sprintf(
				"BOM must contain 1–%d uniquely identified parts, with valid names, categories, notes and quantities from 1 to 1000.",
				maxParts,
			),
		)
	}

	// 6. Wiring material and connection count.
	wirePart, wireExists := parts[t.WiringPartID]

	if idPattern.MatchString(t.WiringPartID) &&
		wireExists &&
		wirePart.Category == "wiring" &&
		len(t.Connections) > 0 &&
		len(t.Connections) <= maxConnections &&
		wirePart.Quantity >= len(t.Connections) {

		add(
			"bom_wiring_consistency",
			"passed",
			fmt.Sprintf(
				"%d declared connections fit within the BOM quantity of %d wiring parts.",
				len(t.Connections),
				wirePart.Quantity,
			),
		)
	} else {
		fail(
			"bom_wiring_consistency",
			fmt.Sprintf(
				"The wiring part must exist with category wiring, the template must declare 1–%d connections, and wiring quantity must cover the declared connection count.",
				maxConnections,
			),
		)
	}

	// 7. Connections and pin mapping.
	//
	// The same physical endpoint may be reused by connections carrying the
	// same named signal, which supports shared ground and bus lines. Reusing
	// an endpoint for a conflicting signal is rejected.
	endpointSignals := make(map[string]string)

	connectionOK :=
		len(t.Connections) > 0 &&
			len(t.Connections) <= maxConnections &&
			partOK

	if connectionOK {
		for _, c := range t.Connections {
			if _, ok := parts[c.FromPartID]; !ok ||
				_, duplicate := parts[c.ToPartID]; !duplicate ||
				c.FromPartID == c.ToPartID {

				connectionOK = false
				break
			}

			if !validText(c.FromPin, maxPinLabelBytes) ||
				!validText(c.ToPin, maxPinLabelBytes) ||
				!validText(c.Signal, maxSignalBytes) ||
				!validText(c.Notes, maxConnectionNotes) ||
				!colorPattern.MatchString(c.WireColor) {

				connectionOK = false
				break
			}

			signalKey := strings.ToLower(strings.TrimSpace(c.Signal))
			fromKey := endpointKey(c.FromPartID, c.FromPin)
			toKey := endpointKey(c.ToPartID, c.ToPin)

			if fromKey == toKey {
				connectionOK = false
				break
			}

			if existing, exists := endpointSignals[fromKey]; exists &&
				existing != signalKey {

				connectionOK = false
				break
			}

			if existing, exists := endpointSignals[toKey]; exists &&
				existing != signalKey {

				connectionOK = false
				break
			}

			endpointSignals[fromKey] = signalKey
			endpointSignals[toKey] = signalKey
		}
	}

	if connectionOK {
		add(
			"connections",
			"passed",
			fmt.Sprintf(
				"%d connections reference registered, distinct parts; endpoint signal assignments and wire colors are structurally valid.",
				len(t.Connections),
			),
		)
	} else {
		fail(
			"connections",
			fmt.Sprintf(
				"Connections must contain 1–%d valid entries, reference registered distinct parts, have bounded pin/signal/notes fields, use #RRGGBB colors, and avoid assigning conflicting signals to the same endpoint.",
				maxConnections,
			),
		)
	}

	// 8. Explicit safety and review notes.
	safetyOK := len(t.SafetyNotes) > 0 &&
		len(t.SafetyNotes) <= maxSafetyNotes

	if safetyOK {
		for _, note := range t.SafetyNotes {
			if !validText(note, maxPartNotesBytes) {
				safetyOK = false
				break
			}
		}
	}

	if safetyOK {
		add(
			"safety_notes",
			"passed",
			"Bounded human-verification notes are included.",
		)
	} else {
		fail(
			"safety_notes",
			fmt.Sprintf(
				"Template must contain 1–%d non-empty, bounded safety notes.",
				maxSafetyNotes,
			),
		)
	}

	status := "valid_curated_template"
	if !valid {
		status = "invalid_template"
	}

	return Validation{
		Status:                   status,
		Valid:                    valid,
		ElectricalReviewRequired: electricalReviewRequired,
		Checks:                   checks,
	}
}

// Generate preserves the existing API and chooses the newest registered
// semantic version for the requested target.
func Generate(target, outDir string) (Result, error) {
	return GenerateVersion(target, "", outDir)
}

// GenerateVersion only accepts an exact registered target/version pair.
// An empty version selects the newest registered version.
//
// All artifacts are review drafts. Generated scripts are not executed,
// physical hardware is not accessed, and existing files are never overwritten.
func GenerateVersion(target, version, outDir string) (Result, error) {
	name := strings.ToLower(strings.TrimSpace(target))
	ver := strings.TrimSpace(version)

	if len(name) > maxTargetBytes || !idPattern.MatchString(name) {
		return Result{
			Target:              name,
			Status:              "invalid_target",
			HumanReviewRequired: true,
		}, errors.New("target must be a valid bounded lowercase slug")
	}

	if ver != "" &&
		(len(ver) > maxVersionBytes || !versionPattern.MatchString(ver)) {

		return Result{
			Target:              name,
			TemplateVersion:     ver,
			Status:              "invalid_template_version",
			HumanReviewRequired: true,
		}, errors.New("version must use strict major.minor.patch notation")
	}

	template, ok := resolveTemplate(name, ver)
	if !ok {
		return Result{
				Target:              name,
				TemplateVersion:     ver,
				Status:              "needs_curated_template",
				HumanReviewRequired: true,
			},
			errors.New(
				"no matching curated template target/version is registered; no design was fabricated",
			)
	}

	validation := ValidateTemplate(template)

	if !validation.Valid {
		return Result{
				Target:              name,
				TemplateID:          template.ID,
				TemplateVersion:     template.Version,
				BoardProfileID:      template.BoardProfileID,
				Status:              "template_validation_failed",
				Validation:          validation,
				HumanReviewRequired: true,
			},
			errors.New(
				"registered template failed validation; no artifacts were generated",
			)
	}

	outputDir, err := prepareOutputDirectory(outDir)
	if err != nil {
		return Result{}, err
	}

	templateJSON, err := json.MarshalIndent(template, "", "  ")
	if err != nil {
		return Result{}, fmt.Errorf("serialize curated template: %w", err)
	}

	templateDigest := sha256Hex(templateJSON)

	// Assemble source artifacts first. The manifest contains their checksums,
	// providing deterministic integrity metadata without a self-referential
	// checksum of the manifest itself.
	files := map[string][]byte{
		"bom.txt": []byte(renderBOM(template)),
		"wiring.svg": []byte(
			renderWiringSVG(template),
		),
		"mount_plate.stl": []byte(
			boxSTL(60, 40, 3),
		),
		"flash.sh": []byte(
			renderFlashStub(),
		),
		"README.md": []byte(
			renderReadme(template),
		),
	}

	artifactNames := []string{
		"bom.txt",
		"wiring.svg",
		"mount_plate.stl",
		"flash.sh",
		"README.md",
		"template.json",
	}

	checksums := make(map[string]string, len(files))
	totalBytes := len(templateJSON)

	for _, artifactName := range artifactNames {
		if artifactName == "template.json" {
			continue
		}

		content, exists := files[artifactName]
		if !exists {
			return Result{}, fmt.Errorf(
				"internal error: artifact %q is missing",
				artifactName,
			)
		}

		if len(content) == 0 || len(content) > maxArtifactBytes {
			return Result{}, fmt.Errorf(
				"artifact %q is empty or exceeds the %d-byte limit",
				artifactName,
				maxArtifactBytes,
			)
		}

		totalBytes += len(content)
		checksums[artifactName] = sha256Hex(content)
	}

	if totalBytes > maxTotalArtifactBytes {
		return Result{}, errors.New(
			"assembly artifact bundle exceeds the total size limit",
		)
	}

	manifest := struct {
		SchemaVersion             string            `json:"schema_version"`
		TemplateID                string            `json:"template_id"`
		TemplateVersion           string            `json:"template_version"`
		Target                    string            `json:"target"`
		BoardProfileID            string            `json:"board_profile_id"`
		ElectricalReviewRequired  bool              `json:"electrical_review_required"`
		Status                    string            `json:"status"`
		Validation                Validation        `json:"validation"`
		Cost                      string            `json:"cost"`
		HardwareVerified          bool              `json:"hardware_verified"`
		GeneratedExecutableCode   bool              `json:"generated_executable_code"`
		TemplateSHA256            string            `json:"template_sha256"`
		ArtifactChecksumsSHA256   map[string]string `json:"artifact_checksums_sha256"`
		Template                  json.RawMessage   `json:"template"`
	}{
		SchemaVersion:            manifestSchemaVersion,
		TemplateID:               template.ID,
		TemplateVersion:          template.Version,
		Target:                   template.Target,
		BoardProfileID:           template.BoardProfileID,
		ElectricalReviewRequired: validation.ElectricalReviewRequired,
		Status:                   "review_draft_not_hardware_verified",
		Validation:               validation,
		Cost:                     "unverified; local supplier quote required",
		HardwareVerified:         false,
		GeneratedExecutableCode:  false,
		TemplateSHA256:           templateDigest,
		ArtifactChecksumsSHA256:  checksums,
		Template:                 json.RawMessage(templateJSON),
	}

	manifestJSON, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return Result{}, fmt.Errorf("serialize assembly manifest: %w", err)
	}

	manifestJSON = append(manifestJSON, '\n')
	if len(manifestJSON) > maxArtifactBytes {
		return Result{}, errors.New(
			"assembly manifest exceeds the artifact size limit",
		)
	}

	files["template.json"] = manifestJSON

	for _, artifactName := range artifactNames {
		content := files[artifactName]
		if len(content) == 0 || len(content) > maxArtifactBytes {
			return Result{}, fmt.Errorf(
				"artifact %q has an invalid size",
				artifactName,
			)
		}
	}

	createdPaths, err := writeArtifactBundle(
		outputDir,
		files,
		artifactNames,
	)
	if err != nil {
		return Result{}, err
	}

	safetyNotes := append([]string{}, template.SafetyNotes...)
	safetyNotes = append(
		safetyNotes,
		"No physical operation was performed; generated files are review drafts only.",
		"Pricing is unverified; obtain current local supplier quotations before purchase.",
		"The STL is a simple solid 60 x 40 x 3 mm plate without mounting holes. Validate fit and printability.",
		"The flash script is a non-executing instruction stub; it does not call a flashing utility.",
		"template.json records SHA-256 digests for the other generated artifacts; the manifest does not hash itself.",
	)

	// Return defensive copies so callers cannot mutate the selected
	// template's internal slice storage.
	parts := append([]Part{}, template.Parts...)
	connections := append([]Connection{}, template.Connections...)

	return Result{
		Target:              name,
		TemplateID:          template.ID,
		TemplateVersion:     template.Version,
		BoardProfileID:      template.BoardProfileID,
		Status:              "artifacts_generated_pending_review",
		Artifacts:           createdPaths,
		Parts:               parts,
		Connections:         connections,
		Validation:          validation,
		Cost:                "unverified; local supplier quote required",
		HumanReviewRequired: true,
		SafetyNotes:         safetyNotes,
	}, nil
}

func resolveTemplate(target, version string) (Template, bool) {
	var chosen *Template

	for i := range registry {
		t := &registry[i]

		if t.Target != target {
			continue
		}

		if version != "" {
			if t.Version == version {
				return cloneTemplate(*t), true
			}
			continue
		}

		if chosen == nil ||
			compareVersion(t.Version, chosen.Version) > 0 {

			chosen = t
		}
	}

	if chosen == nil {
		return Template{}, false
	}

	return cloneTemplate(*chosen), true
}

func cloneTemplate(t Template) Template {
	out := t
	out.Parts = append([]Part{}, t.Parts...)
	out.Connections = append([]Connection{}, t.Connections...)
	out.SafetyNotes = append([]string{}, t.SafetyNotes...)
	return out
}

// compareVersion performs numeric semantic-version ordering without parsing
// components into machine-sized integers. This avoids overflow for unusually
// large components in otherwise well-formed version strings.
func compareVersion(a, b string) int {
	if !versionPattern.MatchString(a) ||
		!versionPattern.MatchString(b) {

		return strings.Compare(a, b)
	}

	aa := strings.Split(a, ".")
	bb := strings.Split(b, ".")

	for i := 0; i < 3; i++ {
		x := aa[i]
		y := bb[i]

		if len(x) < len(y) {
			return -1
		}
		if len(x) > len(y) {
			return 1
		}

		if x < y {
			return -1
		}
		if x > y {
			return 1
		}
	}

	return 0
}

func renderBOM(t Template) string {
	var b strings.Builder

	fmt.Fprintf(
		&b,
		"USECT-ZERO Assembly BOM\nTemplate: %s v%s\nTarget: %s\nStatus: REVIEW DRAFT — HARDWARE NOT VERIFIED\nPricing: UNVERIFIED — obtain local supplier quotations before purchase.\n\n",
		t.ID,
		t.Version,
		t.Target,
	)

	for _, p := range t.Parts {
		fmt.Fprintf(
			&b,
			"- %dx %s [%s] — %s\n",
			p.Quantity,
			p.Name,
			p.Category,
			p.Notes,
		)
	}

	b.WriteString(
		"\nConnections are illustrative. Review wiring.svg and template.json against the exact manufacturer's datasheets before use.\n",
	)

	return b.String()
}

// renderWiringSVG renders every connection from the selected template.
// It does not assume that all connections use the same two parts.
func renderWiringSVG(t Template) string {
	const (
		width      = 1200
		rowGap     = 62
		firstRowY  = 137
		headerY    = 104
		bottomGap  = 48
	)

	height := firstRowY + rowGap*len(t.Connections) + bottomGap

	partsByID := make(map[string]Part, len(t.Parts))
	for _, p := range t.Parts {
		partsByID[p.ID] = p
	}

	var b strings.Builder

	fmt.Fprintf(
		&b,
		`<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-labelledby="svg-title svg-description">`,
		width,
		height,
		width,
		height,
	)

	b.WriteString(`<title id="svg-title">`)
	b.WriteString(html.EscapeString(t.Title))
	b.WriteString(`</title>`)

	b.WriteString(
		`<desc id="svg-description">Illustrative wiring plan. Exact board, voltage levels and pin assignments require human verification.</desc>`,
	)

	b.WriteString(
		`<rect width="100%" height="100%" fill="#ffffff"/>`,
	)

	fmt.Fprintf(
		&b,
		`<text x="28" y="38" font-family="sans-serif" font-size="23" font-weight="bold" fill="#17251f">%s</text>`,
		html.EscapeString(t.Title),
	)

	fmt.Fprintf(
		&b,
		`<text x="28" y="65" font-family="sans-serif" font-size="13" fill="#52635a">Template %s v%s — review draft, not hardware-verified</text>`,
		html.EscapeString(t.ID),
		html.EscapeString(t.Version),
	)

	b.WriteString(
		`<text x="32" y="` + fmt.Sprint(headerY) + `" font-family="sans-serif" font-size="12" font-weight="bold" fill="#52635a">SOURCE PART / PIN</text>`,
	)

	b.WriteString(
		`<text x="600" y="` + fmt.Sprint(headerY) + `" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="bold" fill="#52635a">SIGNAL</text>`,
	)

	b.WriteString(
		`<text x="755" y="` + fmt.Sprint(headerY) + `" font-family="sans-serif" font-size="12" font-weight="bold" fill="#52635a">DESTINATION PART / PIN</text>`,
	)

	for i, c := range t.Connections {
		y := firstRowY + i*rowGap

		from := partsByID[c.FromPartID]
		to := partsByID[c.ToPartID]

		fromLabel := truncateLabel(from.Name+" · "+c.FromPin, 54)
		toLabel := truncateLabel(to.Name+" · "+c.ToPin, 54)
		signalLabel := truncateLabel(c.Signal, 38)
		noteLabel := truncateLabel(c.Notes, 150)

		if i%2 == 0 {
			fmt.Fprintf(
				&b,
				`<rect x="18" y="%d" width="1164" height="%d" rx="7" fill="#f4f8f5"/>`,
				y-22,
				rowGap-2,
			)
		}

		fmt.Fprintf(
			&b,
			`<text x="32" y="%d" font-family="monospace" font-size="12" fill="#17251f">%s</text>`,
			y,
			html.EscapeString(fromLabel),
		)

		fmt.Fprintf(
			&b,
			`<text x="755" y="%d" font-family="monospace" font-size="12" fill="#17251f">%s</text>`,
			y,
			html.EscapeString(toLabel),
		)

		fmt.Fprintf(
			&b,
			`<path d="M 460 %d L 740 %d" stroke="%s" stroke-width="3" fill="none"/>`,
			y-4,
			y-4,
			c.WireColor,
		)

		fmt.Fprintf(
			&b,
			`<circle cx="460" cy="%d" r="4" fill="%s"/>`,
			y-4,
			c.WireColor,
		)

		fmt.Fprintf(
			&b,
			`<circle cx="740" cy="%d" r="4" fill="%s"/>`,
			y-4,
			c.WireColor,
		)

		fmt.Fprintf(
			&b,
			`<text x="600" y="%d" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#17251f">%s</text>`,
			y-11,
			html.EscapeString(signalLabel),
		)

		fmt.Fprintf(
			&b,
			`<text x="600" y="%d" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#52635a">%s</text>`,
			y+17,
			html.EscapeString(noteLabel),
		)
	}

	fmt.Fprintf(
		&b,
		`<text x="28" y="%d" font-family="sans-serif" font-size="12" fill="#8a1c1c">DRAFT ONLY: verify exact board, pin labels, voltage compatibility and manufacturer datasheets before wiring.</text>`,
		height-18,
	)

	b.WriteString("</svg>")
	return b.String()
}

func renderFlashStub() string {
	return `#!/bin/sh
set -eu

cat <<'NOTE'
USECT-ZERO flash stub — NOT AN EXECUTOR

1. Confirm the exact board model and USB/serial port.
2. Review the source, wiring, voltage levels and vendor instructions.
3. Select and verify the firmware image and matching board profile.
4. Obtain authorization for the exact operation and device.
5. Run the approved local flashing tool manually only after review.

This artifact intentionally does not call a flashing command.
NOTE
`
}

func renderReadme(t Template) string {
	return fmt.Sprintf(
		"# %s artifact bundle\n\n"+
			"Template version: %s\n"+
			"Status: review draft, not validated hardware instructions.\n"+
			"Generated offline from the USECT-ZERO curated registry.\n\n"+
			"- `bom.txt`: parts list; pricing is unverified.\n"+
			"- `wiring.svg`: illustrative connections generated from the template data.\n"+
			"- `mount_plate.stl`: simple solid 60 x 40 x 3 mm plate without mounting holes; validate fit and printability.\n"+
			"- `flash.sh`: explanatory stub; it does not flash hardware.\n"+
			"- `template.json`: versioned template, validation report, provenance metadata and SHA-256 artifact checksums.\n\n"+
			"No hardware was connected, no firmware was executed and no component price is asserted.\n"+
			"Verify the exact board revision, electrical limits and manufacturer documentation before physical assembly.\n",
		t.Target,
		t.Version,
	)
}

// boxSTL produces a simple ASCII STL cuboid with dimensions in the template's
// declared millimetre convention. STL itself does not encode physical units.
func boxSTL(x, y, z int) string {
	v := [8][3]int{
		{0, 0, 0},
		{x, 0, 0},
		{x, y, 0},
		{0, y, 0},
		{0, 0, z},
		{x, 0, z},
		{x, y, z},
		{0, y, z},
	}

	triangles := [][3]int{
		{0, 2, 1},
		{0, 3, 2},
		{4, 5, 6},
		{4, 6, 7},
		{0, 1, 5},
		{0, 5, 4},
		{1, 2, 6},
		{1, 6, 5},
		{2, 3, 7},
		{2, 7, 6},
		{3, 0, 4},
		{3, 4, 7},
	}

	var b strings.Builder
	b.WriteString("solid usect_zero_mount_plate_mm\n")

	for _, triangle := range triangles {
		a := v[triangle[0]]
		vertB := v[triangle[1]]
		vertC := v[triangle[2]]

		u := [3]float64{
			float64(vertB[0] - a[0]),
			float64(vertB[1] - a[1]),
			float64(vertB[2] - a[2]),
		}

		w := [3]float64{
			float64(vertC[0] - a[0]),
			float64(vertC[1] - a[1]),
			float64(vertC[2] - a[2]),
		}

		normal := [3]float64{
			u[1]*w[2] - u[2]*w[1],
			u[2]*w[0] - u[0]*w[2],
			u[0]*w[1] - u[1]*w[0],
		}

		length := math.Sqrt(
			normal[0]*normal[0] +
				normal[1]*normal[1] +
				normal[2]*normal[2],
		)

		if length > 0 {
			normal[0] /= length
			normal[1] /= length
			normal[2] /= length
		}

		fmt.Fprintf(
			&b,
			" facet normal %.6f %.6f %.6f\n  outer loop\n",
			normal[0],
			normal[1],
			normal[2],
		)

		for _, index := range triangle {
			p := v[index]

			fmt.Fprintf(
				&b,
				"   vertex %d %d %d\n",
				p[0],
				p[1],
				p[2],
			)
		}

		b.WriteString("  endloop\n endfacet\n")
	}

	b.WriteString("endsolid usect_zero_mount_plate_mm\n")
	return b.String()
}

func prepareOutputDirectory(outDir string) (string, error) {
	if strings.TrimSpace(outDir) == "" {
		return "", errors.New("output directory is required")
	}

	absolutePath, err := filepath.Abs(outDir)
	if err != nil {
		return "", fmt.Errorf("resolve output directory: %w", err)
	}

	absolutePath = filepath.Clean(absolutePath)

	if err := os.MkdirAll(absolutePath, 0700); err != nil {
		return "", fmt.Errorf("create output directory: %w", err)
	}

	info, err := os.Lstat(absolutePath)
	if err != nil {
		return "", fmt.Errorf("inspect output directory: %w", err)
	}

	if info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New(
			"output directory must not itself be a symbolic link",
		)
	}

	if !info.IsDir() {
		return "", errors.New("output path is not a directory")
	}

	return absolutePath, nil
}

func writeArtifactBundle(
	outDir string,
	files map[string][]byte,
	names []string,
) ([]string, error) {
	createdPaths := make([]string, 0, len(names))
	createdNames := make([]string, 0, len(names))

	for _, name := range names {
		// Only fixed, known artifact names are accepted here. Do not let a
		// template value become a filesystem path.
		if filepath.Base(name) != name ||
			name == "." ||
			name == ".." ||
			strings.ContainsAny(name, `/\`) {

			cleanupErr := removeCreatedArtifacts(createdPaths)

			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"invalid artifact name %q; cleanup also failed: %v",
					name,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf("invalid artifact name %q", name)
		}

		content, ok := files[name]
		if !ok {
			cleanupErr := removeCreatedArtifacts(createdPaths)

			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"artifact %q is missing; cleanup also failed: %v",
					name,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf("artifact %q is missing", name)
		}

		path := filepath.Join(outDir, name)

		// O_EXCL prevents overwriting an existing regular file or following
		// an existing final-component symlink.
		file, err := os.OpenFile(
			path,
			os.O_WRONLY|os.O_CREATE|os.O_EXCL,
			0600,
		)
		if err != nil {
			cleanupErr := removeCreatedArtifacts(createdPaths)

			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"create artifact %s without overwriting existing files: %w; cleanup also failed: %v",
					name,
					err,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf(
				"create artifact %s without overwriting existing files: %w",
				name,
				err,
			)
		}

		createdPaths = append(createdPaths, path)
		createdNames = append(createdNames, name)

		if err := writeAll(file, content); err != nil {
			_ = file.Close()

			cleanupErr := removeCreatedArtifacts(createdPaths)
			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"write artifact %s: %w; cleanup also failed: %v",
					name,
					err,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf("write artifact %s: %w", name, err)
		}

		if err := file.Sync(); err != nil {
			_ = file.Close()

			cleanupErr := removeCreatedArtifacts(createdPaths)
			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"sync artifact %s: %w; cleanup also failed: %v",
					name,
					err,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf("sync artifact %s: %w", name, err)
		}

		if err := file.Close(); err != nil {
			cleanupErr := removeCreatedArtifacts(createdPaths)
			if cleanupErr != nil {
				return nil, fmt.Errorf(
					"close artifact %s: %w; cleanup also failed: %v",
					name,
					err,
					cleanupErr,
				)
			}

			return nil, fmt.Errorf("close artifact %s: %w", name, err)
		}
	}

	_ = createdNames // Paths are the public artifact references returned below.

	result := make([]string, 0, len(createdPaths))
	for _, path := range createdPaths {
		result = append(result, filepath.ToSlash(path))
	}

	return result, nil
}

func writeAll(writer io.Writer, content []byte) error {
	for len(content) > 0 {
		n, err := writer.Write(content)
		if err != nil {
			return err
		}
		if n <= 0 {
			return io.ErrShortWrite
		}

		content = content[n:]
	}

	return nil
}

func removeCreatedArtifacts(paths []string) error {
	var failures []string

	for i := len(paths) - 1; i >= 0; i-- {
		if err := os.Remove(paths[i]); err != nil &&
			!os.IsNotExist(err) {

			failures = append(
				failures,
				fmt.Sprintf("%s: %v", paths[i], err),
			)
		}
	}

	if len(failures) > 0 {
		return errors.New(strings.Join(failures, "; "))
	}

	return nil
}

func sha256Hex(content []byte) string {
	sum := sha256.Sum256(content)
	return hex.EncodeToString(sum[:])
}

func endpointKey(partID, pin string) string {
	return partID + ":" + strings.ToLower(strings.TrimSpace(pin))
}

func validText(value string, maxBytes int) bool {
	if value == "" ||
		len(value) > maxBytes ||
		!utf8.ValidString(value) ||
		strings.TrimSpace(value) == "" {

		return false
	}

	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}

	return true
}

func truncateLabel(value string, maxRunes int) string {
	if maxRunes < 2 {
		return ""
	}

	runes := []rune(value)
	if len(runes) <= maxRunes {
		return value
	}

	return string(runes[:maxRunes-1]) + "…"
}
