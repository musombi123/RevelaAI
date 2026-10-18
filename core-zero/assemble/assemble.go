// Package assemble creates reviewable, offline artifacts from a versioned curated-template registry.
package assemble

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
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
	ID                     string `json:"id"`
	Family                 string `json:"family"`
	LogicVoltageMV         int    `json:"logic_voltage_mv"`
	TypicalInputVoltageMV  int    `json:"typical_input_voltage_mv"`
	PinMapStatus           string `json:"pin_map_status"`
	Notes                  string `json:"notes"`
	HardwareVerified       bool   `json:"hardware_verified"`
}

type ElectricalRequirements struct {
	SupplyMinMV                  int    `json:"supply_min_mv,omitempty"`
	SupplyMaxMV                  int    `json:"supply_max_mv,omitempty"`
	LogicMinMV                   int    `json:"logic_min_mv,omitempty"`
	LogicMaxMV                   int    `json:"logic_max_mv,omitempty"`
	DatasheetReference           string `json:"datasheet_reference,omitempty"`
	ManufacturerDatasheetReviewed bool   `json:"manufacturer_datasheet_reviewed"`
}

type Template struct {
	ID                    string                 `json:"id"`
	Target                string                 `json:"target"`
	Version               string                 `json:"version"`
	Title                 string                 `json:"title"`
	Description           string                 `json:"description"`
	BoardProfileID        string                 `json:"board_profile_id"`
	Electrical            ElectricalRequirements `json:"electrical_requirements"`
	WiringPartID          string                 `json:"wiring_part_id"`
	Parts                 []Part                 `json:"parts"`
	Connections           []Connection           `json:"connections"`
	SafetyNotes           []string               `json:"safety_notes"`
	ReviewOnly            bool                   `json:"review_only"`
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
	Target                  string       `json:"target"`
	TemplateID              string       `json:"template_id,omitempty"`
	TemplateVersion         string       `json:"template_version,omitempty"`
	BoardProfileID          string       `json:"board_profile_id,omitempty"`
	Status                  string       `json:"status"`
	Artifacts               []string     `json:"artifacts"`
	Parts                   []Part       `json:"parts"`
	Connections             []Connection `json:"connections"`
	Validation              Validation   `json:"validation"`
	Cost                    string       `json:"cost"`
	HumanReviewRequired     bool         `json:"human_review_required"`
	SafetyNotes             []string     `json:"safety_notes"`
}

var (
	idPattern      = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)
	versionPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
	colorPattern   = regexp.MustCompile(`^#[0-9a-fA-F]{6}$`)
)

var boardProfiles = []BoardProfile{
	{
		ID: "esp32-s3-generic",
		Family: "ESP32-S3 development-board family",
		LogicVoltageMV: 3300,
		TypicalInputVoltageMV: 5000,
		PinMapStatus: "exact_board_revision_required",
		Notes: "Generic family reference only. Input paths, regulators, pin availability and connector layouts vary by board; use the exact board manufacturer's documentation.",
		HardwareVerified: false,
	},
	{
		ID: "rp2040-pico-generic",
		Family: "RP2040 / Pico-style development-board family",
		LogicVoltageMV: 3300,
		TypicalInputVoltageMV: 5000,
		PinMapStatus: "exact_board_revision_required",
		Notes: "Generic family reference only. Confirm the specific board revision, input path, regulator, GPIO assignment and manufacturer documentation before connecting hardware.",
		HardwareVerified: false,
	},
}

var registry = []Template{
	{
		ID: "esp32-sensor", Target: "esp32-sensor", Version: "1.0.0",
		Title: "ESP32-S3 + BME280 I2C sensor (review draft)",
		Description: "A generic offline example parts list and illustrative I2C wiring diagram. Exact board pin assignments and electrical compatibility are not verified.",
		BoardProfileID: "esp32-s3-generic",
		WiringPartID: "jumper-wire",
		Parts: []Part{
			{ID: "esp32-board", Name: "ESP32-S3 development board", Quantity: 1, Category: "controller", Notes: "Confirm exact board, USB connector, regulator and selected pin map."},
			{ID: "bme280-breakout", Name: "BME280 I2C sensor breakout", Quantity: 1, Category: "sensor", Notes: "Confirm voltage compatibility and breakout-board pin labels."},
			{ID: "jumper-wire", Name: "3.3V-compatible jumper wires", Quantity: 4, Category: "wiring", Notes: "Illustrative connection count only; choose wire type and insulation for the selected setup."},
			{ID: "prototype-board", Name: "Breadboard or suitable prototyping board", Quantity: 1, Category: "mechanical", Notes: "Check mechanical and electrical suitability."},
			{ID: "usb-cable", Name: "USB data cable for selected board", Quantity: 1, Category: "power-data", Notes: "Cable and connector vary by board revision."},
		},
		Connections: []Connection{
			{FromPartID: "esp32-board", FromPin: "3V3", ToPartID: "bme280-breakout", ToPin: "VIN / 3V3", Signal: "POWER (check voltage)", WireColor: "#e53935", Notes: "Use only if the exact breakout supports the board's 3.3V supply."},
			{FromPartID: "esp32-board", FromPin: "GND", ToPartID: "bme280-breakout", ToPin: "GND", Signal: "GROUND", WireColor: "#424242", Notes: "Confirm ground labels on the exact boards."},
			{FromPartID: "esp32-board", FromPin: "GPIO 8 (example SDA)", ToPartID: "bme280-breakout", ToPin: "SDA / SDI", Signal: "I2C SDA (example)", WireColor: "#1565c0", Notes: "GPIO assignment is illustrative; verify board pin map and software configuration."},
			{FromPartID: "esp32-board", FromPin: "GPIO 9 (example SCL)", ToPartID: "bme280-breakout", ToPin: "SCL / SCK", Signal: "I2C SCL (example)", WireColor: "#2e7d32", Notes: "GPIO assignment is illustrative; verify board pin map and software configuration."},
		},
		SafetyNotes: []string{
			"No physical operation was performed and no hardware compatibility is certified.",
			"Verify every pin, supply voltage, pull-up arrangement and breakout datasheet before wiring.",
			"Part counts and wiring are an illustrative draft, not a supplier-verified bill of materials.",
		},
		ReviewOnly: true,
	},
}

// ListTemplates returns bounded public metadata for each registered template.
func ListTemplates() []TemplateSummary {
	out := make([]TemplateSummary, 0, len(registry))
	for _, t := range registry {
		validation := ValidateTemplate(t)
		out = append(out, TemplateSummary{
			ID: t.ID, Target: t.Target, Version: t.Version, Title: t.Title,
			BoardProfileID: t.BoardProfileID,
			PartCount: len(t.Parts), ConnectionCount: len(t.Connections),
			ValidationStatus: validation.Status,
			ElectricalReviewRequired: validation.ElectricalReviewRequired,
			HumanReviewRequired: true,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Target == out[j].Target {
			return out[i].Version < out[j].Version
		}
		return out[i].Target < out[j].Target
	})
	return out
}

// ListBoardProfiles returns safe reference profiles. They are not manufacturer-certified pin maps.
func ListBoardProfiles() []BoardProfile {
	out := append([]BoardProfile{}, boardProfiles...)
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
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

// ValidateTemplate checks identifiers, part references, quantities, wiring endpoints,
// and the consistency between the wiring plan and the BOM's wire quantity.
func ValidateTemplate(t Template) Validation {
	checks := make([]ValidationCheck, 0, 9)
	add := func(name, status, detail string) {
		checks = append(checks, ValidationCheck{Name: name, Status: status, Detail: detail})
	}
	valid := true
	electricalReviewRequired := true
	fail := func(name, detail string) {
		valid = false
		add(name, "failed", detail)
	}
	if idPattern.MatchString(t.ID) && idPattern.MatchString(t.Target) && versionPattern.MatchString(t.Version) && strings.TrimSpace(t.Title) != "" {
		add("template_identity", "passed", "Template ID, target, version, and title are present and well-formed.")
	} else {
		fail("template_identity", "Template ID/target must be slugs, version must be strict major.minor.patch, and title must be present.")
	}
	if t.ReviewOnly {
		add("review_only_policy", "passed", "Template is explicitly marked review-only.")
	} else {
		fail("review_only_policy", "Template must be marked review-only.")
	}

	profile, profileFound := resolveBoardProfile(t.BoardProfileID)
	if !idPattern.MatchString(t.BoardProfileID) || !profileFound {
		fail("board_profile", "Template must refer to a registered board profile. Profiles are family-level references, not verified pin maps.")
	} else {
		add("board_profile", "passed", fmt.Sprintf("Registered profile %s declares nominal logic voltage %d mV; exact board revision and pin map remain unverified.", profile.ID, profile.LogicVoltageMV))
	}

	e := t.Electrical
	if e.SupplyMinMV == 0 && e.SupplyMaxMV == 0 && e.LogicMinMV == 0 && e.LogicMaxMV == 0 && strings.TrimSpace(e.DatasheetReference) == "" && !e.ManufacturerDatasheetReviewed {
		add("electrical_compatibility", "review_required", "Exact breakout supply/logic limits and manufacturer datasheet evidence are not declared. Verify the chosen breakout, I2C pull-ups, level shifting and pin map before wiring.")
	} else if e.SupplyMinMV <= 0 || e.SupplyMaxMV < e.SupplyMinMV || e.LogicMinMV <= 0 || e.LogicMaxMV < e.LogicMinMV {
		fail("electrical_compatibility", "Declared supply and logic voltage ranges must be positive and ordered min-to-max.")
	} else if !profileFound || profile.LogicVoltageMV < e.SupplyMinMV || profile.LogicVoltageMV > e.SupplyMaxMV || profile.LogicVoltageMV < e.LogicMinMV || profile.LogicVoltageMV > e.LogicMaxMV {
		fail("electrical_compatibility", "The board's nominal logic/supply level falls outside the declared sensor limits; do not generate this template as a compatible design.")
	} else if !e.ManufacturerDatasheetReviewed || strings.TrimSpace(e.DatasheetReference) == "" {
		add("electrical_compatibility", "review_required", "Declared ranges overlap the board profile, but manufacturer datasheet review and a source reference are missing.")
	} else {
		add("electrical_compatibility", "passed", "Declared voltage ranges overlap the board profile and a datasheet reference is recorded. This is a metadata check, not hardware certification.")
		electricalReviewRequired = false
	}

	parts := make(map[string]Part, len(t.Parts))
	partOK := true
	for _, p := range t.Parts {
		if !idPattern.MatchString(p.ID) || strings.TrimSpace(p.Name) == "" || strings.TrimSpace(p.Category) == "" || strings.TrimSpace(p.Notes) == "" || p.Quantity < 1 || p.Quantity > 1000 {
			partOK = false
			break
		}
		if _, exists := parts[p.ID]; exists {
			partOK = false
			break
		}
		parts[p.ID] = p
	}
	if partOK && len(parts) == len(t.Parts) && len(parts) > 0 {
		add("parts", "passed", fmt.Sprintf("%d uniquely identified BOM items have valid quantities and notes.", len(parts)))
	} else {
		fail("parts", "BOM must contain uniquely identified parts with a name, category, notes, and quantity from 1 to 1000.")
	}

	wirePart, wireExists := parts[t.WiringPartID]
	if t.WiringPartID != "" && wireExists && wirePart.Category == "wiring" && wirePart.Quantity >= len(t.Connections) && len(t.Connections) > 0 {
		add("bom_wiring_consistency", "passed", fmt.Sprintf("%d declared connections fit within the BOM quantity of %d wiring parts.", len(t.Connections), wirePart.Quantity))
	} else {
		fail("bom_wiring_consistency", "The wiring part must exist with category wiring, and its quantity must cover every declared connection.")
	}

	endpoints := map[string]bool{}
	connectionOK := len(t.Connections) > 0
	firstFrom, firstTo := "", ""
	for i, c := range t.Connections {
		if _, ok := parts[c.FromPartID]; !ok || c.FromPartID == c.ToPartID {
			connectionOK = false
			break
		}
		if _, ok := parts[c.ToPartID]; !ok || strings.TrimSpace(c.FromPin) == "" || strings.TrimSpace(c.ToPin) == "" || strings.TrimSpace(c.Signal) == "" || strings.TrimSpace(c.Notes) == "" || !colorPattern.MatchString(c.WireColor) {
			connectionOK = false
			break
		}
		fromKey := c.FromPartID + ":" + strings.ToLower(strings.TrimSpace(c.FromPin))
		toKey := c.ToPartID + ":" + strings.ToLower(strings.TrimSpace(c.ToPin))
		if endpoints[fromKey] || endpoints[toKey] || fromKey == toKey {
			connectionOK = false
			break
		}
		endpoints[fromKey], endpoints[toKey] = true, true
		if i == 0 {
			firstFrom, firstTo = c.FromPartID, c.ToPartID
		} else if c.FromPartID != firstFrom || c.ToPartID != firstTo {
			// The current SVG renderer is a two-component wiring overview.
			connectionOK = false
			break
		}
	}
	if connectionOK {
		add("connections", "passed", fmt.Sprintf("%d connections reference registered parts with unique endpoints and valid wire colors.", len(t.Connections)))
	} else {
		fail("connections", "Connections must reference two registered, distinct parts, use unique pin endpoints, include signal/notes, and use #RRGGBB wire colors.")
	}

	if len(t.SafetyNotes) > 0 {
		add("safety_notes", "passed", "Human verification notes are included.")
	} else {
		fail("safety_notes", "At least one explicit safety/review note is required.")
	}
	status := "valid_curated_template"
	if !valid {
		status = "invalid_template"
	}
	return Validation{Status: status, Valid: valid, ElectricalReviewRequired: electricalReviewRequired, Checks: checks}
}

// Generate preserves the earlier API and uses the registered target's current version.
func Generate(target, outDir string) (Result, error) {
	return GenerateVersion(target, "", outDir)
}

// GenerateVersion only accepts an exact registered target/version pair and writes review artifacts.
// Empty version selects the newest registered version for that target.
func GenerateVersion(target, version, outDir string) (Result, error) {
	name := strings.ToLower(strings.TrimSpace(target))
	ver := strings.TrimSpace(version)
	template, ok := resolveTemplate(name, ver)
	if !ok {
		return Result{Target: name, TemplateVersion: ver, Status: "needs_curated_template", HumanReviewRequired: true}, errors.New("no matching curated template target/version is registered; no design was fabricated")
	}
	validation := ValidateTemplate(template)
	if !validation.Valid {
		return Result{Target: name, TemplateID: template.ID, TemplateVersion: template.Version, Status: "template_validation_failed", Validation: validation, HumanReviewRequired: true}, errors.New("registered template failed validation; no artifacts were generated")
	}
	if strings.TrimSpace(outDir) == "" {
		return Result{}, errors.New("output directory is required")
	}
	if err := os.MkdirAll(outDir, 0700); err != nil {
		return Result{}, err
	}
	partsJSON, err := json.MarshalIndent(template, "", "  ")
	if err != nil {
		return Result{}, err
	}
	manifest := map[string]any{
		"schema_version": "usect-zero.assembly-manifest.v1",
		"template_id": template.ID,
		"template_version": template.Version,
		"target": template.Target,
		"board_profile_id": template.BoardProfileID,
		"electrical_review_required": validation.ElectricalReviewRequired,
		"status": "review_draft_not_hardware_verified",
		"validation": validation,
		"template": json.RawMessage(partsJSON),
		"cost": "unverified; local supplier quote required",
		"hardware_verified": false,
		"generated_executable_code": false,
	}
	manifestJSON, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return Result{}, err
	}
	files := map[string][]byte{
		"bom.txt": []byte(renderBOM(template)),
		"wiring.svg": []byte(renderWiringSVG(template)),
		"mount_plate.stl": []byte(boxSTL(60, 40, 3)),
		"flash.sh": []byte(renderFlashStub()),
		"README.md": []byte(renderReadme(template)),
		"template.json": append(manifestJSON, '\n'),
	}
	names := make([]string, 0, len(files))
	created := make([]string, 0, len(files))
	for _, name := range []string{"bom.txt", "wiring.svg", "mount_plate.stl", "flash.sh", "README.md", "template.json"} {
		path := filepath.Join(outDir, name)
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			for _, createdPath := range created {
				_ = os.Remove(createdPath)
			}
			return Result{}, fmt.Errorf("could not create artifact %s without overwriting an existing file: %w", name, err)
		}
		_, writeErr := f.Write(files[name])
		closeErr := f.Close()
		if writeErr != nil || closeErr != nil {
			for _, createdPath := range created {
				_ = os.Remove(createdPath)
			}
			_ = os.Remove(path)
			if writeErr != nil {
				return Result{}, writeErr
			}
			return Result{}, closeErr
		}
		created = append(created, path)
		names = append(names, filepath.ToSlash(path))
	}
	safety := append([]string{}, template.SafetyNotes...)
	safety = append(safety,
		"No physical operation was performed; generated files are review drafts only.",
		"Pricing is unverified; obtain current local supplier quotations before purchase.",
		"The STL is a simple solid 60 x 40 x 3 mm plate without mounting holes. Validate fit and printability.",
		"The flash script is a non-executing instruction stub; it does not call a flashing utility.",
	)
	return Result{
		Target: name, TemplateID: template.ID, TemplateVersion: template.Version,
		BoardProfileID: template.BoardProfileID,
		Status: "artifacts_generated_pending_review", Artifacts: names,
		Parts: append([]Part{}, template.Parts...), Connections: append([]Connection{}, template.Connections...),
		Validation: validation, Cost: "unverified; local supplier quote required",
		HumanReviewRequired: true, SafetyNotes: safety,
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
				return *t, true
			}
			continue
		}
		if chosen == nil || compareVersion(t.Version, chosen.Version) > 0 {
			chosen = t
		}
	}
	if chosen == nil {
		return Template{}, false
	}
	return *chosen, true
}

func compareVersion(a, b string) int {
	var am, an, ap, bm, bn, bp int
	_, _ = fmt.Sscanf(a, "%d.%d.%d", &am, &an, &ap)
	_, _ = fmt.Sscanf(b, "%d.%d.%d", &bm, &bn, &bp)
	aa, bb := []int{am, an, ap}, []int{bm, bn, bp}
	for i := range aa {
		if aa[i] < bb[i] { return -1 }
		if aa[i] > bb[i] { return 1 }
	}
	return 0
}

func renderBOM(t Template) string {
	var b strings.Builder
	fmt.Fprintf(&b, "USECT-ZERO Assembly BOM\nTemplate: %s v%s\nTarget: %s\nStatus: REVIEW DRAFT — HARDWARE NOT VERIFIED\nPricing: UNVERIFIED — obtain local supplier quotations before purchase.\n\n", t.ID, t.Version, t.Target)
	for _, p := range t.Parts {
		fmt.Fprintf(&b, "- %dx %s [%s] — %s\n", p.Quantity, p.Name, p.Category, p.Notes)
	}
	b.WriteString("\nConnections are an illustrative draft; review wiring.svg and template.json against the exact manufacturer datasheets.\n")
	return b.String()
}

func renderWiringSVG(t Template) string {
	connected := map[string]bool{}
	for _, c := range t.Connections {
		connected[c.FromPartID] = true
		connected[c.ToPartID] = true
	}
	var from, to Part
	for _, p := range t.Parts {
		if connected[p.ID] {
			if from.ID == "" { from = p } else if to.ID == "" { to = p }
		}
	}
	const rowGap = 42
	height := 150 + rowGap*len(t.Connections) + 90
	var b strings.Builder
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="%d" viewBox="0 0 900 %d">`, height, height)
	b.WriteString(`<rect width="900" height="100%" fill="#ffffff"/>`)
	fmt.Fprintf(&b, `<text x="24" y="36" font-family="sans-serif" font-size="22" font-weight="bold">%s</text>`, html.EscapeString(t.Title))
	fmt.Fprintf(&b, `<text x="24" y="61" font-family="sans-serif" font-size="13" fill="#555">Template %s v%s — review draft, not hardware-verified</text>`, html.EscapeString(t.ID), html.EscapeString(t.Version))
	fmt.Fprintf(&b, `<rect x="35" y="85" width="350" height="%d" rx="12" fill="#e8f5e9" stroke="#287d4b" stroke-width="2"/>`, rowGap*len(t.Connections)+30)
	fmt.Fprintf(&b, `<text x="210" y="112" text-anchor="middle" font-family="sans-serif" font-size="17" font-weight="bold">%s</text>`, html.EscapeString(from.Name))
	fmt.Fprintf(&b, `<rect x="540" y="85" width="325" height="%d" rx="12" fill="#e3f2fd" stroke="#1565c0" stroke-width="2"/>`, rowGap*len(t.Connections)+30)
	fmt.Fprintf(&b, `<text x="702" y="112" text-anchor="middle" font-family="sans-serif" font-size="17" font-weight="bold">%s</text>`, html.EscapeString(to.Name))
	for i, c := range t.Connections {
		y := 143 + rowGap*i
		fmt.Fprintf(&b, `<text x="55" y="%d" font-family="monospace" font-size="13">%s</text>`, y, html.EscapeString(c.FromPin))
		fmt.Fprintf(&b, `<path d="M 340 %d L 510 %d L 540 %d" stroke="%s" stroke-width="3" fill="none"/>`, y-4, y-4, y-4, c.WireColor)
		fmt.Fprintf(&b, `<text x="560" y="%d" font-family="monospace" font-size="13">%s</text>`, y, html.EscapeString(c.ToPin))
		fmt.Fprintf(&b, `<text x="450" y="%d" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#333">%s</text>`, y-9, html.EscapeString(c.Signal))
	}
	fmt.Fprintf(&b, `<text x="24" y="%d" font-family="sans-serif" font-size="13" fill="#8a1c1c">DRAFT ONLY: verify exact board, voltage levels, pin labels and datasheets before wiring.</text>`, height-22)
	b.WriteString("</svg>")
	return b.String()
}

func renderFlashStub() string {
	return `#!/bin/sh
set -eu
cat <<'NOTE'
USECT-ZERO flash stub — NOT AN EXECUTOR
1. Confirm exact board model and USB/serial port.
2. Review the source, wiring, voltage levels and vendor instructions.
3. Select and verify a tested firmware image and matching board profile.
4. Only then run your approved local flashing tool manually.
This file intentionally does not call a flashing command.
NOTE
`
}

func renderReadme(t Template) string {
	return fmt.Sprintf("# %s artifact bundle\n\nTemplate version: %s\nStatus: review draft, not validated hardware instructions.\nGenerated offline from the USECT-ZERO curated registry.\n\n- bom.txt: parts list; pricing is unverified.\n- wiring.svg: illustrative connections generated from the same connection data in template.json.\n- mount_plate.stl: simple solid 60 x 40 x 3 mm plate without holes; validate fit and printability.\n- flash.sh: explanatory stub; it does not flash hardware.\n- template.json: versioned template, validation report, and provenance metadata.\n\nNo hardware was connected, no firmware was executed and no component price is asserted.\n", t.Target, t.Version)
}

func boxSTL(x, y, z int) string {
	v := [8][3]int{{0, 0, 0}, {x, 0, 0}, {x, y, 0}, {0, y, 0}, {0, 0, z}, {x, 0, z}, {x, y, z}, {0, y, z}}
	tris := [][3]int{{0, 2, 1}, {0, 3, 2}, {4, 5, 6}, {4, 6, 7}, {0, 1, 5}, {0, 5, 4}, {1, 2, 6}, {1, 6, 5}, {2, 3, 7}, {2, 7, 6}, {3, 0, 4}, {3, 4, 7}}
	s := "solid usect_zero_mount_plate_mm\n"
	for _, t := range tris {
		a, b, c := v[t[0]], v[t[1]], v[t[2]]
		u := [3]float64{float64(b[0] - a[0]), float64(b[1] - a[1]), float64(b[2] - a[2])}
		w := [3]float64{float64(c[0] - a[0]), float64(c[1] - a[1]), float64(c[2] - a[2])}
		n := [3]float64{u[1]*w[2] - u[2]*w[1], u[2]*w[0] - u[0]*w[2], u[0]*w[1] - u[1]*w[0]}
		length := math.Sqrt(n[0]*n[0] + n[1]*n[1] + n[2]*n[2])
		if length > 0 {
			n[0], n[1], n[2] = n[0]/length, n[1]/length, n[2]/length
		}
		s += fmt.Sprintf(" facet normal %.1f %.1f %.1f\n  outer loop\n", n[0], n[1], n[2])
		for _, idx := range t {
			p := v[idx]
			s += fmt.Sprintf("   vertex %d %d %d\n", p[0], p[1], p[2])
		}
		s += "  endloop\n endfacet\n"
	}
	return s + "endsolid usect_zero_mount_plate_mm\n"
}
