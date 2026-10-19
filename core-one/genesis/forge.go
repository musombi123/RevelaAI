package genesis

import (
	"encoding/json"
	"errors"
	"fmt"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	worldguardian "revela-worldwide.local/libs/guardian"
)

const (
	maxForgeDependencyCandidates = 3
	maxForgeLibraryMetadataBytes = 512 * 1024
	maxForgeDriverBytes          = 1 << 20
	maxForgeGeneratedActionBytes = 120
	maxForgeInputEntries         = 100
	maxForgeInputKeyBytes        = 200
	maxForgeInputValueBytes      = 4000
)

type libraryMetadata struct {
	Name         string   `json:"name"`
	Category     string   `json:"category"`
	Industry     string   `json:"industry"`
	Capabilities []string `json:"capabilities"`
	Dependencies []string `json:"dependencies"`
}

// deriveSpec deterministically classifies an invention demand and converts it
// into a bounded, reviewable ToolSpec. Classification is heuristic and must not
// be treated as proof of safety, intended use, compliance, or implementation.
func deriveSpec(demand string) ToolSpec {
	original := strings.TrimSpace(demand)
	label := original

	lower := strings.ToLower(label)

	prefixes := []string{
		"create a new tool:",
		"create a tool:",
		"create tool:",
		"build a tool:",
		"build tool:",
		"invent a tool:",
		"invent tool:",
		"make a tool:",
		"make tool:",
		"create a new ",
		"create an ",
		"create a ",
		"create ",
		"build a new ",
		"build an ",
		"build a ",
		"build ",
		"invent a ",
		"invent ",
		"make a ",
		"make ",
		"design a ",
		"design ",
		"develop a ",
		"develop ",
		"construct a ",
		"construct ",
		"generate a ",
		"generate ",
	}

	for _, prefix := range prefixes {
		if strings.HasPrefix(lower, prefix) {
			label = strings.TrimSpace(label[len(prefix):])
			break
		}
	}

	// A first line is a useful deterministic label boundary for prompts that
	// contain a longer description after the title.
	if i := strings.IndexAny(label, "\r\n"); i >= 0 {
		label = label[:i]
	}

	// Keep sentence extraction conservative: decimals and filename-like
	// segments should not cause arbitrary mid-label truncation.
	label = strings.TrimSpace(label)
	label = forgeLimitText(label, 120)

	if label == "" {
		label = forgeLimitText(original, 80)
	}
	if label == "" {
		label = "New tool"
	}

	normalizedDemand := normalizeForgePhrase(original)
	normalizedLabel := normalizeForgePhrase(label)

	hardwareTerms := []string{
		"cctv",
		"camera",
		"sensor",
		"motor",
		"mill",
		"pump",
		"robot",
		"hardware",
		"device",
		"machine",
		"actuator",
		"relay",
		"microcontroller",
		"iot",
		"wearable",
		"valve",
		"controller",
		"circuit",
		"industrial equipment",
		"electronics",
		"embedded",
		"plc",
		"drone",
		"battery",
		"solar panel",
	}

	softwareTerms := []string{
		"software",
		"website",
		"web app",
		"mobile app",
		"api",
		"dashboard",
		"platform",
		"database",
		"automation",
		"workflow",
		"ai",
		"model",
		"service",
		"application",
	}

	hardware := forgeContainsPhrase(normalizedDemand, hardwareTerms...) ||
		forgeContainsPhrase(normalizedLabel, hardwareTerms...)

	software := forgeContainsPhrase(normalizedDemand, softwareTerms...) ||
		forgeContainsPhrase(normalizedLabel, softwareTerms...)

	category := "software"
	switch {
	case hardware && software:
		category = "hybrid"
	case hardware:
		category = "hardware"
	}

	name := slugName(label)

	// Hardware-aware suffixing remains deterministic without allowing the
	// suffix to push the identifier past the resource-name limit.
	if hardware && category == "hardware" && !strings.HasSuffix(name, "_smart") {
		stemLimit := 51
		if len(name) > stemLimit {
			name = strings.Trim(name[:stemLimit], "_")
		}
		name += "_smart"
	}

	if len(name) > 58 {
		name = strings.Trim(name[:58], "_")
	}
	if name == "" {
		name = "new_tool"
	}
	if !validResourceName(name) {
		name = slugName(name)
	}
	if !validResourceName(name) {
		name = "new_tool"
	}

	industry := classifyForgeIndustry(normalizedDemand + " " + normalizedLabel)

	purpose := fmt.Sprintf(
		"A reviewable %s tool scaffold derived from the demand: %s.",
		category,
		label,
	)

	capabilities := []string{
		"validate structured input",
		"produce a deterministic plan",
		"record traceable evidence",
		"expose a documented API contract",
		"support human review before activation",
	}

	if hardware {
		capabilities = append(
			capabilities,
			"describe a safe hardware integration boundary",
			"require explicit consent before hardware-related plans",
		)
	}

	inputs := []string{
		"action",
		"structured_inputs",
		"consent",
	}

	outputs := []string{
		"status",
		"plan_summary",
		"evidence_references",
		"review_requirements",
	}

	safeguards := []string{
		"no execution during invention",
		"human merge and deployment approval required",
		"least-privilege integration",
		"audit trail and artifact hashes",
		"privacy and consent by design",
		"validate untrusted input before processing",
		"never embed credentials or secrets in generated artifacts",
		"fail explicitly when required dependencies are unavailable",
	}

	if hardware {
		safeguards = append(
			safeguards,
			"no physical actuation during proposal generation",
			"verify exact component ratings and manufacturer datasheets",
			"qualified hardware review required before physical connection",
		)
	}

	if forgeContainsPhrase(
		normalizedDemand,
		"payment",
		"transaction",
		"billing",
		"checkout",
		"wallet",
	) {
		safeguards = append(
			safeguards,
			"financial transactions remain disabled until provider and reconciliation tests pass",
		)
	}

	if forgeContainsPhrase(
		normalizedDemand,
		"camera",
		"cctv",
		"patient",
		"student",
		"personal data",
		"location tracking",
	) {
		safeguards = append(
			safeguards,
			"authorized data collection and retention review required",
			"minimize personal data and restrict access to authorized roles",
		)
	}

	if forgeContainsPhrase(
		normalizedDemand,
		"remote",
		"multi-user",
		"multi tenant",
		"multi-tenant",
		"api client",
	) {
		safeguards = append(
			safeguards,
			"server-side authentication and authorization required for protected operations",
			"remote transport security and request throttling require verification",
		)
	}

	return ToolSpec{
		Name:               name,
		Title:              label,
		Demand:             original,
		Purpose:            purpose,
		Category:           category,
		Industry:           industry,
		Capabilities:       uniqueStrings(capabilities),
		Inputs:              uniqueStrings(inputs),
		Outputs:             uniqueStrings(outputs),
		Safeguards:          uniqueStrings(safeguards),
		NeedsHardwareGuide: hardware,
	}
}

func classifyForgeIndustry(text string) string {
	switch {
	case forgeContainsPhrase(
		text,
		"agriculture",
		"farm",
		"soil",
		"crop",
		"irrigation",
		"harvest",
		"livestock",
		"greenhouse",
	):
		return "agriculture"

	case forgeContainsPhrase(
		text,
		"school",
		"student",
		"learner",
		"education",
		"teacher",
		"learning",
		"classroom",
	):
		return "education"

	case forgeContainsPhrase(
		text,
		"payment",
		"business",
		"commerce",
		"marketplace",
		"shop",
		"merchant",
		"billing",
		"invoice",
		"transaction",
	):
		return "commerce"

	case forgeContainsPhrase(
		text,
		"health",
		"clinic",
		"medical",
		"patient",
		"hospital",
		"diagnosis",
	):
		return "health"

	case forgeContainsPhrase(
		text,
		"logistics",
		"delivery",
		"fleet",
		"shipping",
		"warehouse",
		"transport",
	):
		return "logistics"

	case forgeContainsPhrase(
		text,
		"solar",
		"energy",
		"power grid",
		"battery storage",
		"electricity",
		"renewable energy",
	):
		return "energy"

	case forgeContainsPhrase(
		text,
		"factory",
		"industrial",
		"motor",
		"pump",
		"machine",
		"device",
		"sensor",
		"circuit",
		"robot",
	):
		return "infrastructure"

	case forgeContainsPhrase(
		text,
		"public service",
		"government",
		"citizen service",
		"public administration",
	):
		return "public_service"

	case forgeContainsPhrase(
		text,
		"code",
		"developer",
		"api",
		"software",
		"data",
		"ai",
		"model",
		"neural",
		"website",
		"web app",
		"mobile app",
	):
		return "digital"
	}

	return "general"
}

func containsAny(value string, words ...string) bool {
	for _, word := range words {
		if strings.Contains(value, word) {
			return true
		}
	}
	return false
}

func normalizeForgePhrase(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))

	var out strings.Builder
	previousSpace := true

	for _, r := range value {
		switch {
		case r >= 'a' && r <= 'z':
			out.WriteRune(r)
			previousSpace = false
		case r >= '0' && r <= '9':
			out.WriteRune(r)
			previousSpace = false
		default:
			if !previousSpace {
				out.WriteByte(' ')
				previousSpace = true
			}
		}
	}

	return strings.TrimSpace(out.String())
}

func forgeContainsPhrase(text string, phrases ...string) bool {
	text = " " + normalizeForgePhrase(text) + " "

	for _, phrase := range phrases {
		phrase = normalizeForgePhrase(phrase)
		if phrase == "" {
			continue
		}
		if strings.Contains(text, " "+phrase+" ") {
			return true
		}
	}

	return false
}

func forgeLimitText(value string, maxRunes int) string {
	value = strings.TrimSpace(value)
	if maxRunes <= 0 {
		return ""
	}

	runes := []rune(value)
	if len(runes) > maxRunes {
		return string(runes[:maxRunes])
	}

	return value
}

// forge builds an isolated invention package and publishes its invention,
// reusable-library package, and model blueprint only after staging succeeds.
// All generated artifacts remain reviewable proposals.
func (e *Engine) forge(
	spec ToolSpec,
	evidence ResearchEvidence,
	capabilityPlan CapabilityPlan,
) (Invention, error) {
	if e == nil {
		return Invention{}, errors.New("genesis forge: engine is required")
	}
	if strings.TrimSpace(e.CoreRoot) == "" {
		return Invention{}, errors.New("genesis forge: core root is required")
	}
	if !validResourceName(spec.Name) {
		return Invention{}, errors.New("genesis forge: invalid invention name")
	}
	if strings.TrimSpace(spec.Demand) == "" {
		return Invention{}, errors.New("genesis forge: invention demand is required")
	}

	coreRoot, err := filepath.Abs(e.CoreRoot)
	if err != nil {
		return Invention{}, fmt.Errorf("resolve core root: %w", err)
	}

	invRoot := filepath.Join(coreRoot, "inventions")
	libRoot := filepath.Join(coreRoot, "libraries", "created")
	modelRoot := filepath.Join(coreRoot, "models")

	for _, dir := range []string{invRoot, libRoot, modelRoot} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return Invention{}, fmt.Errorf("prepare output directory: %w", err)
		}
	}

	invFinal := filepath.Join(invRoot, spec.Name)
	libName := spec.Name + "_lib"
	libFinal := filepath.Join(libRoot, libName)
	modelFinal := filepath.Join(modelRoot, spec.Name+".yaml")

	for _, path := range []string{invFinal, libFinal, modelFinal} {
		if _, err := os.Lstat(path); err == nil {
			return Invention{}, fmt.Errorf("%w: %s", ErrAlreadyExists, path)
		} else if !os.IsNotExist(err) {
			return Invention{}, fmt.Errorf("inspect existing output %s: %w", path, err)
		}
	}

	decision := worldguardian.CheckText(spec.Demand)
	if !decision.Allowed {
		return Invention{}, fmt.Errorf(
			"%w: Guardian rejected invention demand",
			ErrBlocked,
		)
	}

	id := newID("inv")
	created := time.Now().UTC()

	invStage, err := os.MkdirTemp(invRoot, ".staging-")
	if err != nil {
		return Invention{}, fmt.Errorf("create invention staging directory: %w", err)
	}
	defer os.RemoveAll(invStage)

	libStage, err := os.MkdirTemp(libRoot, ".staging-")
	if err != nil {
		return Invention{}, fmt.Errorf("create library staging directory: %w", err)
	}
	defer os.RemoveAll(libStage)

	modelStage, err := os.CreateTemp(modelRoot, ".staging-*.yaml")
	if err != nil {
		return Invention{}, fmt.Errorf("create model staging file: %w", err)
	}
	modelStagePath := modelStage.Name()
	defer os.Remove(modelStagePath)

	if err := modelStage.Close(); err != nil {
		return Invention{}, fmt.Errorf("close model staging file: %w", err)
	}

	expansionPlan := makeExpansionPlan(spec, coreRoot)

	files := []string{
		"code.go",
		"library.go",
		"openapi.yaml",
		"README.md",
		"hardware_guide.md",
		"test.go",
		"evidence.json",
		"capability_plan.json",
		"expansion_plan.json",
		"implementation_plan.json",
		"acceptance_matrix.json",
		"dependency_review.json",
		"security_review.md",
		"worldwide_context.json",
		"AWAIT_MERGE.md",
		"sdk/go/client.go",
		"sdk/python/client.py",
		"sdk/js/client.js",
	}

	contents := map[string]string{
		"code.go":          generatedCode(spec),
		"library.go":       generatedLibrary(spec),
		"openapi.yaml":     generatedOpenAPI(spec),
		"README.md":        generatedREADME(spec, evidence) + generatedCapabilityPlanNote(capabilityPlan),
		"hardware_guide.md": generatedHardwareGuide(spec),
		"test.go":           generatedTest(spec),

		"evidence.json": string(mustJSON(map[string]any{
			"schema_version": "genesis.invention-evidence.v2",
			"invention_id":   id,
			"specification":  spec,
			"research":       evidence,
			"created_at":     created,
			"status":         "await_merge",
			"execution":      "not_executed",
		})),

		"capability_plan.json": string(mustJSON(capabilityPlan)),
		"expansion_plan.json":  string(mustJSON(expansionPlan)),
		"implementation_plan.json": string(mustJSON(
			generatedImplementationPlan(spec, capabilityPlan, created),
		)),
		"acceptance_matrix.json": string(mustJSON(
			generatedAcceptanceMatrix(capabilityPlan),
		)),
		"dependency_review.json": string(mustJSON(
			generatedDependencyReview(capabilityPlan),
		)),
		"security_review.md": generatedSecurityReview(spec, capabilityPlan),
		"worldwide_context.json": string(mustJSON(
			generatedWorldwideContext(spec),
		)),
		"AWAIT_MERGE.md": generatedMergeChecklist(spec),

		"sdk/go/client.go":     generatedGoSDK(spec),
		"sdk/python/client.py": generatedPythonSDK(spec),
		"sdk/js/client.js":     generatedJavaScriptSDK(spec),
	}

	// Sorted writes make staging behavior and failure messages reproducible.
	contentNames := make([]string, 0, len(contents))
	for name := range contents {
		contentNames = append(contentNames, name)
	}
	sort.Strings(contentNames)

	for _, name := range contentNames {
		content := contents[name]
		path := filepath.Join(invStage, filepath.FromSlash(name))

		if err := atomicWrite(path, []byte(content), 0o644); err != nil {
			return Invention{}, fmt.Errorf("write staged artifact %s: %w", name, err)
		}
	}

	if err := e.writeGeneratedLibrary(libStage, spec); err != nil {
		return Invention{}, fmt.Errorf("write generated library: %w", err)
	}

	if err := atomicWrite(
		modelStagePath,
		[]byte(generatedModel(spec)),
		0o644,
	); err != nil {
		return Invention{}, fmt.Errorf("write generated model blueprint: %w", err)
	}

	if err := writeIntegrityManifest(invStage); err != nil {
		return Invention{}, fmt.Errorf("write artifact integrity manifest: %w", err)
	}

	// Each target is published without deliberately overwriting existing output.
	// Rollback removes previously published components if a later publication
	// fails. The invention contents themselves become visible by directory rename.
	inventionPublished := false
	libraryPublished := false
	modelPublished := false

	defer func() {
		if inventionPublished {
			_ = os.RemoveAll(invFinal)
		}
		if libraryPublished {
			_ = os.RemoveAll(libFinal)
		}
		if modelPublished {
			_ = os.Remove(modelFinal)
		}
	}()

	if err := ensureForgeTargetAbsent(invFinal); err != nil {
		return Invention{}, err
	}
	if err := os.Rename(invStage, invFinal); err != nil {
		return Invention{}, fmt.Errorf("publish invention package: %w", err)
	}
	inventionPublished = true

	if err := ensureForgeTargetAbsent(libFinal); err != nil {
		return Invention{}, err
	}
	if err := os.Rename(libStage, libFinal); err != nil {
		return Invention{}, fmt.Errorf("publish reusable library: %w", err)
	}
	libraryPublished = true

	if err := ensureForgeTargetAbsent(modelFinal); err != nil {
		return Invention{}, err
	}

	// A hard link publishes the completed model blueprint without replacing a
	// file created by another process after the original target check.
	if err := os.Link(modelStagePath, modelFinal); err != nil {
		return Invention{}, fmt.Errorf("publish model blueprint without overwrite: %w", err)
	}
	modelPublished = true

	if err := os.Remove(modelStagePath); err != nil {
		e.publish(Event{
			Type:    "forge_cleanup_warning",
			At:      time.Now().UTC(),
			Message: "The model blueprint was published, but its temporary staging entry could not be removed.",
			Status:  "cleanup_warning",
		})
	}

	// The three core artifacts are now published. Supplemental indexes are
	// best-effort and report failures through events instead of hiding them.
	inventionPublished = false
	libraryPublished = false
	modelPublished = false

	if spec.Industry != "" && spec.Industry != "general" {
		if err := e.recordIndustry(spec); err != nil {
			e.publish(Event{
				Type:    "industry_record_warning",
				At:      time.Now().UTC(),
				Message: limitText(err.Error(), 240),
				Status:  "review_required",
			})
		}
	}

	expansionDir := filepath.Join(coreRoot, "expand", "plans")
	expansionPath := filepath.Join(expansionDir, spec.Name+".json")

	if shouldUseGen2(coreRoot) {
		expansionDir = filepath.Join(coreRoot, "gen2", "staging")
		expansionPath = filepath.Join(expansionDir, spec.Name+".json")
	}

	if err := os.MkdirAll(expansionDir, 0o700); err != nil {
		e.publish(Event{
			Type:    "expansion_index_warning",
			At:      time.Now().UTC(),
			Message: limitText(err.Error(), 240),
			Status:  "review_required",
		})
	} else if err := writeJSON(expansionPath, expansionPlan); err != nil {
		e.publish(Event{
			Type:    "expansion_index_warning",
			At:      time.Now().UTC(),
			Message: limitText(err.Error(), 240),
			Status:  "review_required",
		})
	}

	allFiles := append([]string{}, files...)
	allFiles = append(allFiles, "artifact_hashes.json")
	sort.Strings(allFiles)

	return Invention{
		ID:                  id,
		Name:                spec.Name,
		Title:               spec.Title,
		Status:              "await_merge",
		CreatedAt:           created,
		Directory:           filepath.ToSlash(filepath.Join("core-one", "inventions", spec.Name)),
		Library:             filepath.ToSlash(filepath.Join("core-one", "libraries", "created", libName)),
		Model:               filepath.ToSlash(filepath.Join("core-one", "models", spec.Name+".yaml")),
		Category:            spec.Category,
		Industry:            spec.Industry,
		Country:             spec.Country,
		CountryName:         spec.CountryName,
		Language:             spec.Language,
		Currency:             spec.Currency,
		SupplierDirectory:    append([]string(nil), spec.SupplierDirectory...),
		BOM:                  copyExpansionMap(spec.BOM),
		Files:                allFiles,
		Evidence:             evidence,
		Summary:              "Generated as a staged proposal. No source was executed, no external device was actuated, and no changes were merged.",
		CapabilityPlanPath:   filepath.ToSlash(filepath.Join("core-one", "inventions", spec.Name, "capability_plan.json")),
		CapabilityCoverage:   capabilityPlan.Coverage,
	}, nil
}

func ensureForgeTargetAbsent(path string) error {
	_, err := os.Lstat(path)
	if err == nil {
		return fmt.Errorf("%w: %s", ErrAlreadyExists, path)
	}
	if !os.IsNotExist(err) {
		return fmt.Errorf("inspect target %s: %w", path, err)
	}
	return nil
}

// writeGeneratedLibrary creates a deterministic, proposal-only Go library.
// Reusable dependencies are metadata-ranked and source-checked before they are
// imported into the generated package.
func (e *Engine) writeGeneratedLibrary(dir string, spec ToolSpec) error {
	if e == nil {
		return errors.New("genesis: engine is required")
	}
	if !validResourceName(spec.Name) {
		return errors.New("genesis: invalid tool name for generated library")
	}

	pkg := slugName(spec.Name + "_lib")
	dependencies, err := e.findLibraryDependenciesChecked(
		spec,
		maxForgeDependencyCandidates,
	)
	if err != nil {
		return err
	}

	var driver strings.Builder

	fmt.Fprintf(
		&driver,
		"// Package %s is a model-free, deterministic proposal contract generated by Revela Genesis.\n",
		pkg,
	)
	fmt.Fprintf(&driver, "package %s\n\n", pkg)
	driver.WriteString("import (\n\t\"errors\"\n\t\"fmt\"\n\t\"strings\"\n")

	for i, dependency := range dependencies {
		fmt.Fprintf(
			&driver,
			"\tlib%d %q\n",
			i,
			"revela-genesis.local/core-one/libraries/created/"+dependency.Name,
		)
	}

	driver.WriteString(")\n\n")
	fmt.Fprintf(&driver, "const ToolName = %q\n", spec.Name)
	fmt.Fprintf(&driver, "const ToolVersion = %q\n\n", "0.1.0-proposal")

	driver.WriteString(`// Input contains caller-supplied, untrusted proposal data.
type Input struct {
	Action  string            ` + "`json:\"action\"`" + `
	Values  map[string]string ` + "`json:\"values,omitempty\"`" + `
	Consent bool              ` + "`json:\"consent\"`" + `
}

// Plan is a proposal description, not an execution receipt.
type Plan struct {
	Accepted bool     ` + "`json:\"accepted\"`" + `
	Name     string   ` + "`json:\"name\"`" + `
	Action   string   ` + "`json:\"action\"`" + `
	Notices  []string ` + "`json:\"notices\"`" + `
}

// ComposedLibraryNames returns the libraries imported for proposal composition.
func ComposedLibraryNames() []string {
	return []string{`)

	for i := range dependencies {
		if i > 0 {
			driver.WriteString(", ")
		}
		fmt.Fprintf(&driver, "lib%d.ToolName", i)
	}

	driver.WriteString("}\n}\n\n")

	fmt.Fprintf(
		&driver,
		"// Build validates a bounded request and produces a proposal-only result for %s.\n",
		spec.Title,
	)
	driver.WriteString(`func Build(input Input) (Plan, error) {
	action := strings.TrimSpace(input.Action)
	if action == "" {
		return Plan{}, errors.New("action is required")
	}
	if len([]rune(action)) > `)
	fmt.Fprintf(&driver, "%d", maxForgeGeneratedActionBytes)
	driver.WriteString(` {
		return Plan{}, errors.New("action exceeds the configured length limit")
	}
	for _, r := range action {
		if r < 0x20 && r != '\t' {
			return Plan{}, errors.New("action contains unsupported control characters")
		}
	}

	if len(input.Values) > `)
	fmt.Fprintf(&driver, "%d", maxForgeInputEntries)
	driver.WriteString(` {
		return Plan{}, errors.New("too many input values")
	}

	for key, value := range input.Values {
		if strings.TrimSpace(key) == "" || len([]rune(key)) > `)
	fmt.Fprintf(&driver, "%d", maxForgeInputKeyBytes)
	driver.WriteString(` {
			return Plan{}, errors.New("input key is empty or too long")
		}
		if len([]rune(value)) > `)
	fmt.Fprintf(&driver, "%d", maxForgeInputValueBytes)
	driver.WriteString(` {
			return Plan{}, fmt.Errorf("input value for %q exceeds the configured limit", key)
		}
		for _, r := range key {
			if r < 0x20 {
				return Plan{}, errors.New("input key contains unsupported control characters")
			}
		}
	}

`)

	if spec.NeedsHardwareGuide {
		driver.WriteString(`	if !input.Consent {
		return Plan{}, errors.New("explicit consent is required before preparing a hardware-related plan")
	}
`)
	}

	driver.WriteString(`	return Plan{
		Accepted: true,
		Name:     ToolName,
		Action:   action,
		Notices: []string{
			"proposal only: adapter execution is not implemented",
			"no network requests or physical actuation were performed",
			"human review is required before activation",
		},
	}, nil
}
`)

	if err := atomicWrite(filepath.Join(dir, "driver.go"), []byte(driver.String()), 0o644); err != nil {
		return fmt.Errorf("write generated library driver: %w", err)
	}

	test := fmt.Sprintf(`package %s

import "testing"

func TestBuildRequiresAction(t *testing.T) {
	if _, err := Build(Input{}); err == nil {
		t.Fatal("empty action must fail")
	}
}

func TestBuildReturnsProposalOnly(t *testing.T) {
	plan, err := Build(Input{Action: "inspect", Consent: true})
	if err != nil {
		t.Fatal(err)
	}
	if !plan.Accepted || plan.Name != ToolName {
		t.Fatalf("unexpected plan: %%+v", plan)
	}
	if len(plan.Notices) == 0 {
		t.Fatal("proposal-only notices must be present")
	}
	if ComposedLibraryNames() == nil {
		t.Fatal("composition metadata must be a non-nil list")
	}
}

func TestBuildRejectsOversizedAction(t *testing.T) {
	longAction := make([]rune, %d)
	for i := range longAction {
		longAction[i] = 'x'
	}
	if _, err := Build(Input{Action: string(longAction), Consent: true}); err == nil {
		t.Fatal("oversized action must fail")
	}
}
`, pkg, maxForgeGeneratedActionBytes+1)

	if err := atomicWrite(filepath.Join(dir, "driver_test.go"), []byte(test), 0o644); err != nil {
		return fmt.Errorf("write generated library tests: %w", err)
	}

	meta := libraryMetadata{
		Name:         spec.Name + "_lib",
		Category:     spec.Category,
		Industry:     spec.Industry,
		Capabilities: append([]string{}, spec.Capabilities...),
		Dependencies: []string{},
	}

	for _, dependency := range dependencies {
		meta.Dependencies = append(meta.Dependencies, dependency.Name)
	}

	sort.Strings(meta.Dependencies)
	meta.Dependencies = uniqueStrings(meta.Dependencies)

	if err := writeJSON(filepath.Join(dir, "library.json"), meta); err != nil {
		return fmt.Errorf("write generated library metadata: %w", err)
	}

	readme := fmt.Sprintf(
		"# %s\n\n"+
			"Generated library contract for `%s`.\n\n"+
			"This package validates bounded structured input and creates proposal-only results. It does not execute external commands, make network requests, or actuate hardware.\n\n"+
			"## Capability metadata\n\n%s\n\n"+
			"## Composed dependencies\n\n%s\n\n"+
			"## Verification status\n\n"+
			"- Implementation status: generated_proposal\n"+
			"- Tests: generated, not yet executed by this generator\n"+
			"- Dependency status: candidates require review\n"+
			"- Production approval: false\n"+
			"- Merge approval: required\n",
		spec.Title,
		spec.Name,
		formatForgeBulletList(spec.Capabilities, "No capability metadata supplied."),
		formatForgeBulletList(meta.Dependencies, "No reusable dependencies selected."),
	)

	if err := atomicWrite(filepath.Join(dir, "README.md"), []byte(readme), 0o644); err != nil {
		return fmt.Errorf("write generated library README: %w", err)
	}

	return nil
}

// findLibraryDependencies retains the previous helper signature for callers
// that only need a best-effort dependency list.
func (e *Engine) findLibraryDependencies(
	spec ToolSpec,
	maxItems int,
) []libraryMetadata {
	dependencies, err := e.findLibraryDependenciesChecked(spec, maxItems)
	if err != nil {
		return nil
	}
	return dependencies
}

// findLibraryDependenciesChecked uses the same ranking policy as the
// capability planner, but imports only libraries with safe metadata and a
// parseable generated driver whose package name matches the expected name.
func (e *Engine) findLibraryDependenciesChecked(
	spec ToolSpec,
	maxItems int,
) ([]libraryMetadata, error) {
	if maxItems <= 0 {
		return []libraryMetadata{}, nil
	}
	if maxItems > maxForgeDependencyCandidates {
		maxItems = maxForgeDependencyCandidates
	}

	root := filepath.Join(e.CoreRoot, "libraries", "created")
	libraries, err := loadCapabilityLibraries(root)
	if err != nil {
		return nil, fmt.Errorf("load candidate library metadata: %w", err)
	}

	verifiedForComposition := make([]libraryMetadata, 0, len(libraries))

	for _, meta := range libraries {
		if meta.Name == spec.Name+"_lib" {
			continue
		}
		if !validForgeLibraryName(meta.Name) {
			continue
		}

		ok, err := forgeLibraryPackageUsable(root, meta)
		if err != nil {
			return nil, err
		}
		if !ok {
			continue
		}

		verifiedForComposition = append(verifiedForComposition, meta)
	}

	ranked := rankReusableLibraries(spec, verifiedForComposition, maxItems)
	if len(ranked) == 0 {
		return []libraryMetadata{}, nil
	}

	byName := make(map[string]libraryMetadata, len(verifiedForComposition))
	for _, meta := range verifiedForComposition {
		byName[meta.Name] = meta
	}

	out := make([]libraryMetadata, 0, len(ranked))
	seen := make(map[string]bool)

	for _, candidate := range ranked {
		meta, ok := byName[candidate.Name]
		if !ok || seen[meta.Name] {
			continue
		}
		seen[meta.Name] = true
		out = append(out, meta)
	}

	return out, nil
}

func forgeLibraryPackageUsable(
	root string,
	meta libraryMetadata,
) (bool, error) {
	dir := filepath.Join(root, meta.Name)

	dirInfo, err := os.Lstat(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}

	if !dirInfo.IsDir() || dirInfo.Mode()&os.ModeSymlink != 0 {
		return false, nil
	}

	driverPath := filepath.Join(dir, "driver.go")
	info, err := os.Lstat(driverPath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}

	if !info.Mode().IsRegular() ||
		info.Mode()&os.ModeSymlink != 0 ||
		info.Size() > maxForgeDriverBytes {
		return false, nil
	}

	source, err := os.ReadFile(driverPath)
	if err != nil {
		return false, err
	}

	file, err := parser.ParseFile(
		token.NewFileSet(),
		driverPath,
		source,
		parser.PackageClauseOnly,
	)
	if err != nil {
		// A package that cannot even be parsed must not be composed into
		// another generated package.
		return false, nil
	}

	expectedPackage := slugName(meta.Name)
	if file.Name == nil || file.Name.Name != expectedPackage {
		return false, nil
	}

	metadataPath := filepath.Join(dir, "library.json")
	metadataInfo, err := os.Lstat(metadataPath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}

	if !metadataInfo.Mode().IsRegular() ||
		metadataInfo.Mode()&os.ModeSymlink != 0 ||
		metadataInfo.Size() > maxForgeLibraryMetadataBytes {
		return false, nil
	}

	raw, err := os.ReadFile(metadataPath)
	if err != nil {
		return false, err
	}

	var onDisk libraryMetadata
	if err := json.Unmarshal(raw, &onDisk); err != nil {
		return false, nil
	}

	if onDisk.Name != meta.Name {
		return false, nil
	}

	decision := worldguardian.CheckText(
		strings.Join(
			append(
				[]string{onDisk.Name, onDisk.Category, onDisk.Industry},
				append(onDisk.Capabilities, onDisk.Dependencies...)...,
			),
			" ",
		),
	)
	if !decision.Allowed {
		return false, fmt.Errorf(
			"%w: candidate library %q was rejected by Guardian (%s)",
			ErrBlocked,
			onDisk.Name,
			decision.Code,
		)
	}

	return true, nil
}

func validForgeLibraryName(name string) bool {
	if name == "" ||
		len(name) > 100 ||
		name == "." ||
		name == ".." ||
		filepath.Base(name) != name ||
		strings.ContainsAny(name, `/\`) {
		return false
	}

	for _, r := range name {
		if (r >= 'a' && r <= 'z') ||
			(r >= '0' && r <= '9') ||
			r == '_' ||
			r == '-' {
			continue
		}
		return false
	}

	return true
}

func generatedCapabilityPlanNote(plan CapabilityPlan) string {
	return fmt.Sprintf(
		"\n\n## Capability graph and requirement plan\n\n"+
			"A deterministic capability plan is stored in `capability_plan.json`. "+
			"It records %d requirements, %d native contract matches, %d reusable-library candidates, "+
			"and %d unresolved capabilities. Native coverage is %.1f%%; this is a planning metric, "+
			"not a measure of production readiness. Review every acceptance check and unresolved risk before implementation or merge.\n",
		plan.Coverage.Required,
		plan.Coverage.NativeContracts,
		plan.Coverage.LibraryCandidates,
		plan.Coverage.Unresolved,
		plan.Coverage.NativeCoverage,
	)
}

func generatedImplementationPlan(
	spec ToolSpec,
	plan CapabilityPlan,
	created time.Time,
) map[string]any {
	requirements := make([]map[string]any, 0, len(plan.Requirements))

	for _, req := range plan.Requirements {
		requirements = append(requirements, map[string]any{
			"id":                    req.ID,
			"capability":            req.Capability,
			"description":           req.Description,
			"priority":              req.Priority,
			"status":                req.Status,
			"verification_gate":     req.VerificationGate,
			"acceptance_criteria":   append([]string{}, req.AcceptanceCriteria...),
			"evidence_refs":         append([]string{}, req.EvidenceRefs...),
			"implementation_needed": req.Status == "unresolved",
		})
	}

	return map[string]any{
		"schema_version":  "genesis.implementation-plan.v1",
		"generated_at":    created,
		"invention":       spec.Name,
		"title":           spec.Title,
		"industry":        spec.Industry,
		"category":        spec.Category,
		"purpose":         spec.Purpose,
		"plan_status":     plan.Status,
		"execution_policy": "proposal_only",
		"requirements":    requirements,
		"missing_capabilities": append(
			[]string{},
			plan.MissingCapabilities...,
		),
		"acceptance_checks": append([]string{}, plan.AcceptanceChecks...),
		"unresolved_risks":  append([]string{}, plan.UnresolvedRisks...),
		"human_approval_required": true,
		"tests_executed_by_generator": false,
		"production_approved": false,
	}
}

func generatedAcceptanceMatrix(plan CapabilityPlan) map[string]any {
	items := make([]map[string]any, 0)

	for _, req := range plan.Requirements {
		for i, criterion := range req.AcceptanceCriteria {
			items = append(items, map[string]any{
				"id":             fmt.Sprintf("%s-check-%02d", req.ID, i+1),
				"requirement_id": req.ID,
				"capability":     req.Capability,
				"criterion":      criterion,
				"status":         "pending",
				"verified":       false,
				"verification_gate": req.VerificationGate,
			})
		}
	}

	for i, check := range plan.AcceptanceChecks {
		items = append(items, map[string]any{
			"id":         fmt.Sprintf("global-check-%03d", i+1),
			"criterion":  check,
			"status":     "pending",
			"verified":   false,
			"scope":      "global",
		})
	}

	return map[string]any{
		"schema_version": "genesis.acceptance-matrix.v1",
		"status":         "pending",
		"checks":         items,
		"summary": map[string]any{
			"total":          len(items),
			"passed":         0,
			"failed":         0,
			"pending":        len(items),
			"tests_executed": false,
		},
		"notice": "All checks begin as pending. The generation process does not report tests as passing unless an independent test runner records verified results.",
	}
}

func generatedDependencyReview(plan CapabilityPlan) map[string]any {
	candidates := make([]map[string]any, 0, len(plan.ReusableCandidates))

	for _, candidate := range plan.ReusableCandidates {
		candidates = append(candidates, map[string]any{
			"name":                  candidate.Name,
			"industry":              candidate.Industry,
			"category":              candidate.Category,
			"score":                 candidate.Score,
			"capabilities":           append([]string{}, candidate.Capabilities...),
			"matched_capabilities":   append([]string{}, candidate.MatchedCapabilities...),
			"dependencies":           append([]string{}, candidate.Dependencies...),
			"source_path":            candidate.SourcePath,
			"status":                 "candidate_unverified",
			"license_review":         "pending",
			"security_review":        "pending",
			"api_compatibility":      "pending",
			"tests_review":           "pending",
			"production_approval":    false,
			"verification_required":  true,
			"reason":                 candidate.Reason,
		})
	}

	return map[string]any{
		"schema_version": "genesis.dependency-review.v1",
		"status":         "pending",
		"candidates":     candidates,
		"checks": []string{
			"Verify the candidate source and package API.",
			"Review the license and redistribution constraints.",
			"Review dependency versions and security advisories.",
			"Confirm test coverage and reproducible behavior.",
			"Confirm maintenance status and compatibility with the target module.",
			"Check for cycles, duplicate dependency names, and unexpected file or network behavior.",
			"Require explicit approval before production adoption.",
		},
		"verified_dependencies": 0,
		"notice": "Metadata matches are discovery hints. This review file does not claim that a dependency is safe, licensed appropriately, or production ready.",
	}
}

func generatedSecurityReview(
	spec ToolSpec,
	plan CapabilityPlan,
) string {
	var b strings.Builder

	b.WriteString("# Security and Safety Review\n\n")
	fmt.Fprintf(&b, "Invention: `%s`\n\n", spec.Name)
	fmt.Fprintf(&b, "Category: `%s`\n\n", spec.Category)
	fmt.Fprintf(&b, "Industry: `%s`\n\n", spec.Industry)

	b.WriteString("## Review status\n\n")
	b.WriteString("- Status: `pending_review`\n")
	b.WriteString("- Automated security assessment completed: `false`\n")
	b.WriteString("- Production approval: `false`\n")
	b.WriteString("- Automatic execution: `prohibited`\n\n")

	b.WriteString("## Threat-model checklist\n\n")
	for _, item := range []string{
		"Identify trust boundaries, protected assets, and expected attackers.",
		"Validate all external inputs, payload sizes, and unexpected states.",
		"Confirm authentication and authorization rules for protected operations.",
		"Confirm secrets are supplied through approved server-side configuration rather than source files or client bundles.",
		"Review sensitive-data collection, data minimization, access, retention, and deletion.",
		"Review dependency provenance, licensing, versions, and security advisories.",
		"Test authorization failures, malformed inputs, rate limits, and failure recovery.",
		"Confirm logs and evidence records do not disclose credentials or unnecessary personal information.",
		"Confirm generated code cannot invoke real operations merely by being generated or reviewed.",
		"Define rollback and incident handling before staged activation.",
	} {
		fmt.Fprintf(&b, "- [ ] %s\n", item)
	}

	if spec.NeedsHardwareGuide {
		b.WriteString("\n## Hardware-specific checks\n\n")
		for _, item := range []string{
			"Verify exact manufacturer part numbers and datasheets.",
			"Verify voltage, current, insulation, grounding, connector assignments, and protection.",
			"Review fail-safe state, independent interlocks, and emergency shutdown where applicable.",
			"Use simulation or a safe test fixture before physical connection.",
			"Obtain qualified review for hazardous loads and mains-powered equipment.",
		} {
			fmt.Fprintf(&b, "- [ ] %s\n", item)
		}
	}

	if containsAny(
		strings.ToLower(spec.Demand),
		"payment", "transaction", "billing", "checkout", "wallet",
	) {
		b.WriteString("\n## Financial workflow checks\n\n")
		for _, item := range []string{
			"Verify idempotency and duplicate-request behavior.",
			"Test reconciliation, reversals, and failure states using simulated transactions.",
			"Keep live payment operations disabled until provider and applicable compliance reviews pass.",
		} {
			fmt.Fprintf(&b, "- [ ] %s\n", item)
		}
	}

	if containsAny(
		strings.ToLower(spec.Demand),
		"camera", "cctv", "patient", "student", "personal data", "location tracking",
	) {
		b.WriteString("\n## Privacy checks\n\n")
		for _, item := range []string{
			"Document purpose, authorization, notice, and applicable legal basis.",
			"Define minimization, access restrictions, retention, and deletion.",
			"Use synthetic data for development and automated tests where possible.",
		} {
			fmt.Fprintf(&b, "- [ ] %s\n", item)
		}
	}

	b.WriteString("\n## Unresolved capability risks\n\n")
	if len(plan.UnresolvedRisks) == 0 {
		b.WriteString("- No unresolved risks were recorded by the capability planner; independent security review is still required.\n")
	} else {
		for _, risk := range plan.UnresolvedRisks {
			fmt.Fprintf(&b, "- %s\n", risk)
		}
	}

	b.WriteString("\n## Safeguards declared by the specification\n\n")
	if len(spec.Safeguards) == 0 {
		b.WriteString("- No specification safeguards were supplied; define them during review.\n")
	} else {
		for _, safeguard := range uniqueStrings(spec.Safeguards) {
			fmt.Fprintf(&b, "- %s\n", safeguard)
		}
	}

	b.WriteString("\nThis checklist is a review aid, not a penetration-test report, security certification, safety case, or legal opinion. Complete each applicable item and attach evidence before approval.\n")

	return b.String()
}

func generatedWorldwideContext(spec ToolSpec) map[string]any {
	return map[string]any{
		"schema_version": "genesis.worldwide-context.v1",
		"country":        spec.Country,
		"country_name":   spec.CountryName,
		"language":       spec.Language,
		"currency":       spec.Currency,
		"supplier_directory": append(
			[]string{},
			spec.SupplierDirectory...,
		),
		"nominal_ac_voltage_v": spec.NominalACVoltage,
		"frequency_hz":         spec.FrequencyHz,
		"local_adaptations": append(
			[]string{},
			spec.LocalAdaptations...,
		),
		"legal_framework_awareness": append(
			[]string{},
			spec.LegalFrameworks...,
		),
		"bill_of_materials": copyExpansionMap(spec.BOM),
		"live_prices_verified": false,
		"live_stock_verified":  false,
		"legal_compliance_verified": false,
		"electrical_site_verified": false,
		"notice": "Country profile entries are adaptation references. They do not verify live supplier prices or stock, actual site electrical conditions, certification, or legal compliance.",
	}
}

func formatForgeBulletList(values []string, emptyText string) string {
	values = uniqueStrings(values)
	if len(values) == 0 {
		return "- " + emptyText
	}

	var b strings.Builder
	for _, value := range values {
		fmt.Fprintf(&b, "- %s\n", strings.ReplaceAll(value, "\n", " "))
	}
	return strings.TrimSpace(b.String())
}

func (e *Engine) findLibraryDependencies(
	spec ToolSpec,
	maxItems int,
) []libraryMetadata {
	dependencies, err := e.findLibraryDependenciesChecked(spec, maxItems)
	if err != nil {
		return nil
	}
	return dependencies
}

func (e *Engine) findLibraryDependenciesChecked(
	spec ToolSpec,
	maxItems int,
) ([]libraryMetadata, error) {
	if e == nil {
		return nil, errors.New("genesis: engine is required")
	}
	if maxItems <= 0 {
		return []libraryMetadata{}, nil
	}
	if maxItems > maxForgeDependencyCandidates {
		maxItems = maxForgeDependencyCandidates
	}

	root := filepath.Join(e.CoreRoot, "libraries", "created")
	catalogue, err := loadCapabilityLibraries(root)
	if err != nil {
		return nil, fmt.Errorf("load reusable library candidates: %w", err)
	}

	verified := make([]libraryMetadata, 0, len(catalogue))

	for _, meta := range catalogue {
		if meta.Name == spec.Name+"_lib" ||
			!validForgeLibraryName(meta.Name) {
			continue
		}

		usable, err := forgeLibraryPackageUsable(root, meta)
		if err != nil {
			return nil, err
		}
		if !usable {
			continue
		}

		verified = append(verified, meta)
	}

	ranked := rankReusableLibraries(spec, verified, maxItems)

	byName := make(map[string]libraryMetadata, len(verified))
	for _, meta := range verified {
		byName[meta.Name] = meta
	}

	out := make([]libraryMetadata, 0, len(ranked))
	seen := make(map[string]bool)

	for _, candidate := range ranked {
		meta, ok := byName[candidate.Name]
		if !ok || seen[meta.Name] {
			continue
		}
		seen[meta.Name] = true
		out = append(out, meta)
	}

	return out, nil
}

func forgeLibraryPackageUsable(
	root string,
	meta libraryMetadata,
) (bool, error) {
	dir := filepath.Join(root, meta.Name)

	dirInfo, err := os.Lstat(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	if !dirInfo.IsDir() || dirInfo.Mode()&os.ModeSymlink != 0 {
		return false, nil
	}

	driverPath := filepath.Join(dir, "driver.go")
	info, err := os.Lstat(driverPath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	if !info.Mode().IsRegular() ||
		info.Mode()&os.ModeSymlink != 0 ||
		info.Size() > maxForgeDriverBytes {
		return false, nil
	}

	source, err := os.ReadFile(driverPath)
	if err != nil {
		return false, err
	}

	file, err := parser.ParseFile(
		token.NewFileSet(),
		driverPath,
		source,
		parser.PackageClauseOnly,
	)
	if err != nil {
		return false, nil
	}

	if file.Name == nil || file.Name.Name != slugName(meta.Name) {
		return false, nil
	}

	metadataPath := filepath.Join(dir, "library.json")
	metaInfo, err := os.Lstat(metadataPath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	if !metaInfo.Mode().IsRegular() ||
		metaInfo.Mode()&os.ModeSymlink != 0 ||
		metaInfo.Size() > maxForgeLibraryMetadataBytes {
		return false, nil
	}

	raw, err := os.ReadFile(metadataPath)
	if err != nil {
		return false, err
	}

	var onDisk libraryMetadata
	if err := json.Unmarshal(raw, &onDisk); err != nil {
		return false, nil
	}
	if onDisk.Name != meta.Name {
		return false, nil
	}

	content := strings.Join(
		append(
			[]string{onDisk.Name, onDisk.Category, onDisk.Industry},
			append(onDisk.Capabilities, onDisk.Dependencies...)...,
		),
		" ",
	)

	decision := worldguardian.CheckText(content)
	if !decision.Allowed {
		return false, fmt.Errorf(
			"%w: candidate library %q was rejected by Guardian (%s)",
			ErrBlocked,
			onDisk.Name,
			decision.Code,
		)
	}

	return true, nil
}

func validForgeLibraryName(name string) bool {
	if name == "" ||
		len(name) > 100 ||
		name == "." ||
		name == ".." ||
		filepath.Base(name) != name ||
		strings.ContainsAny(name, `/\`) {
		return false
	}

	for _, r := range name {
		if (r >= 'a' && r <= 'z') ||
			(r >= '0' && r <= '9') ||
			r == '_' ||
			r == '-' {
			continue
		}
		return false
	}

	return true
}

func generatedCapabilityPlanNote(plan CapabilityPlan) string {
	return fmt.Sprintf(
		"\n\n## Capability graph and requirement plan\n\n"+
			"A deterministic capability plan is stored in `capability_plan.json`. "+
			"It records %d requirements, %d native contract matches, %d reusable-library candidates, "+
			"and %d unresolved capabilities. Native coverage is %.1f%%; this is a planning metric, "+
			"not a measure of production readiness. Review every acceptance check and unresolved risk before implementation or merge.\n",
		plan.Coverage.Required,
		plan.Coverage.NativeContracts,
		plan.Coverage.LibraryCandidates,
		plan.Coverage.Unresolved,
		plan.Coverage.NativeCoverage,
	)
}
