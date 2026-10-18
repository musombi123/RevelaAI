package genesis

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type libraryMetadata struct {
	Name         string   `json:"name"`
	Category     string   `json:"category"`
	Industry     string   `json:"industry"`
	Capabilities []string `json:"capabilities"`
	Dependencies []string `json:"dependencies"`
}

func deriveSpec(demand string) ToolSpec {
	label := strings.TrimSpace(demand)
	lower := strings.ToLower(label)
	for _, prefix := range []string{"create tool:", "create a tool:", "create a new tool:", "build tool:", "build a tool:", "invent tool:", "invent a tool:", "make tool:", "make a tool:"} {
		if strings.HasPrefix(lower, prefix) {
			label = strings.TrimSpace(label[len(prefix):])
			lower = strings.ToLower(label)
			break
		}
	}
	for _, prefix := range []string{"create a new ", "create an ", "create a ", "create ", "build a new ", "build an ", "build a ", "build ", "invent a ", "invent ", "make a ", "make "} {
		if strings.HasPrefix(lower, prefix) {
			label = strings.TrimSpace(label[len(prefix):])
			lower = strings.ToLower(label)
			break
		}
	}
	if i := strings.IndexAny(label, "\r\n"); i >= 0 {
		label = label[:i]
	}
	if i := strings.Index(label, "."); i >= 0 {
		label = label[:i]
	}
	label = limitText(label, 120)
	if label == "" {
		label = limitText(demand, 80)
	}
	name := slugName(label)
	hardware := containsAny(lower, "cctv", "camera", "sensor", "motor", "mill", "pump", "robot", "hardware", "device", "machine", "actuator", "relay", "microcontroller", "iot", "wearable", "valve", "controller", "circuit", "industrial equipment")
	if hardware && !strings.HasSuffix(name, "_smart") {
		name += "_smart"
	}
	if len(name) > 58 {
		name = strings.Trim(name[:58], "_")
	}
	category := "software"
	if hardware {
		category = "hardware"
	}
	if containsAny(lower, "software and hardware", "hardware and software", "device api", "device integration") {
		category = "hybrid"
	}
	industry := "general"
	switch {
	case containsAny(lower, "farm", "soil", "crop", "agriculture", "mill", "irrigation", "harvest"):
		industry = "agriculture"
	case containsAny(lower, "school", "student", "education", "teacher", "learning"):
		industry = "education"
	case containsAny(lower, "payment", "business", "commerce", "marketplace", "shop", "merchant"):
		industry = "commerce"
	case containsAny(lower, "health", "clinic", "medical", "patient", "hospital"):
		industry = "health"
	case containsAny(lower, "camera", "cctv", "sensor", "factory", "industrial", "motor", "pump", "machine", "device"):
		industry = "infrastructure"
	case containsAny(lower, "code", "developer", "api", "software", "data", "ai", "model", "neural"):
		industry = "digital"
	}
	purpose := fmt.Sprintf("A reviewable %s tool scaffold derived from the demand: %s.", category, label)
	capabilities := []string{"validate structured input", "produce a deterministic plan", "record traceable evidence", "expose a documented API contract", "support human review before activation"}
	if hardware {
		capabilities = append(capabilities, "describe a safe hardware integration boundary", "require explicit consent before hardware-related plans")
	}
	return ToolSpec{Name: name, Title: label, Demand: demand, Purpose: purpose, Category: category, Industry: industry,
		Capabilities: capabilities, Inputs: []string{"action", "structured_inputs", "consent"},
		Outputs:    []string{"status", "plan_summary", "evidence_references", "review_requirements"},
		Safeguards: []string{"no execution during invention", "human merge and deployment approval required", "least-privilege integration", "audit trail and artifact hashes", "privacy and consent by design"}, NeedsHardwareGuide: hardware}
}

func containsAny(value string, words ...string) bool {
	for _, w := range words {
		if strings.Contains(value, w) {
			return true
		}
	}
	return false
}

func (e *Engine) forge(spec ToolSpec, evidence ResearchEvidence, capabilityPlan CapabilityPlan) (Invention, error) {
	invRoot := filepath.Join(e.CoreRoot, "inventions")
	libRoot := filepath.Join(e.CoreRoot, "libraries", "created")
	modelRoot := filepath.Join(e.CoreRoot, "models")
	invFinal := filepath.Join(invRoot, spec.Name)
	libName := spec.Name + "_lib"
	libFinal := filepath.Join(libRoot, libName)
	modelFinal := filepath.Join(modelRoot, spec.Name+".yaml")
	for _, p := range []string{invFinal, libFinal, modelFinal} {
		if _, err := os.Lstat(p); err == nil {
			return Invention{}, fmt.Errorf("%w: %s", ErrAlreadyExists, p)
		} else if !os.IsNotExist(err) {
			return Invention{}, err
		}
	}
	id := newID("inv")
	invStage, err := os.MkdirTemp(invRoot, ".staging-")
	if err != nil {
		return Invention{}, err
	}
	defer os.RemoveAll(invStage)
	libStage, err := os.MkdirTemp(libRoot, ".staging-")
	if err != nil {
		return Invention{}, err
	}
	defer os.RemoveAll(libStage)
	modelStage, err := os.CreateTemp(modelRoot, ".staging-*.yaml")
	if err != nil {
		return Invention{}, err
	}
	modelStagePath := modelStage.Name()
	defer os.Remove(modelStagePath)
	if err := modelStage.Close(); err != nil {
		return Invention{}, err
	}
	created := time.Now().UTC()
	files := []string{"code.go", "library.go", "openapi.yaml", "README.md", "hardware_guide.md", "test.go", "evidence.json", "capability_plan.json", "expansion_plan.json", "AWAIT_MERGE.md", "sdk/go/client.go", "sdk/python/client.py", "sdk/js/client.js"}
	contents := map[string]string{
		"code.go": generatedCode(spec), "library.go": generatedLibrary(spec), "openapi.yaml": generatedOpenAPI(spec),
		"README.md": generatedREADME(spec, evidence) + generatedCapabilityPlanNote(capabilityPlan), "hardware_guide.md": generatedHardwareGuide(spec), "test.go": generatedTest(spec),
		"evidence.json":       string(mustJSON(map[string]any{"invention_id": id, "specification": spec, "research": evidence, "created_at": created, "status": "await_merge"})),
		"capability_plan.json": string(mustJSON(capabilityPlan)),
		"expansion_plan.json": string(mustJSON(makeExpansionPlan(spec, e.CoreRoot))), "AWAIT_MERGE.md": generatedMergeChecklist(spec),
		"sdk/go/client.go": generatedGoSDK(spec), "sdk/python/client.py": generatedPythonSDK(spec), "sdk/js/client.js": generatedJavaScriptSDK(spec),
	}
	for name, content := range contents {
		if err := atomicWrite(filepath.Join(invStage, name), []byte(content), 0o644); err != nil {
			return Invention{}, err
		}
	}
	if err := e.writeGeneratedLibrary(libStage, spec); err != nil {
		return Invention{}, err
	}
	if err := atomicWrite(modelStagePath, []byte(generatedModel(spec)), 0o644); err != nil {
		return Invention{}, err
	}
	if err := writeIntegrityManifest(invStage); err != nil {
		return Invention{}, err
	}
	if err := os.Rename(invStage, invFinal); err != nil {
		return Invention{}, err
	}
	rollbackInv := true
	defer func() {
		if rollbackInv {
			_ = os.RemoveAll(invFinal)
		}
	}()
	if err := os.Rename(libStage, libFinal); err != nil {
		return Invention{}, err
	}
	rollbackLib := true
	defer func() {
		if rollbackLib {
			_ = os.RemoveAll(libFinal)
		}
	}()
	if err := os.Rename(modelStagePath, modelFinal); err != nil {
		return Invention{}, err
	}
	rollbackInv = false
	rollbackLib = false
	if spec.Industry != "general" {
		_ = e.recordIndustry(spec)
	}
	if shouldUseGen2(e.CoreRoot) {
		_ = writeJSON(filepath.Join(e.CoreRoot, "gen2", "staging", spec.Name+".json"), makeExpansionPlan(spec, e.CoreRoot))
	} else {
		_ = writeJSON(filepath.Join(e.CoreRoot, "expand", "plans", spec.Name+".json"), makeExpansionPlan(spec, e.CoreRoot))
	}
	allFiles := append([]string{}, files...)
	allFiles = append(allFiles, "artifact_hashes.json")
	return Invention{ID: id, Name: spec.Name, Title: spec.Title, Status: "await_merge", CreatedAt: created,
		Directory: filepath.ToSlash(filepath.Join("core-one", "inventions", spec.Name)),
		Library:   filepath.ToSlash(filepath.Join("core-one", "libraries", "created", libName)),
		Model:     filepath.ToSlash(filepath.Join("core-one", "models", spec.Name+".yaml")), Category: spec.Category, Industry: spec.Industry,
		Files: allFiles, Evidence: evidence, Summary: "Generated as a staged proposal. No source was executed, no external device was actuated, and no changes were merged.",
		CapabilityPlanPath: filepath.ToSlash(filepath.Join("core-one", "inventions", spec.Name, "capability_plan.json")), CapabilityCoverage: capabilityPlan.Coverage}, nil
}

func (e *Engine) writeGeneratedLibrary(dir string, spec ToolSpec) error {
	pkg := slugName(spec.Name + "_lib")
	dependencies := e.findLibraryDependencies(spec, 3)
	var driver strings.Builder
	fmt.Fprintf(&driver, "// Package %s is a model-free deterministic contract library generated by Revela Genesis.\npackage %s\n\nimport (\n\t\"errors\"\n", pkg, pkg)
	for i, dependency := range dependencies {
		fmt.Fprintf(&driver, "\tlib%d %q\n", i, "revela-genesis.local/core-one/libraries/created/"+dependency.Name)
	}
	fmt.Fprintf(&driver, ")\n\nconst ToolName = %q\n\ntype Input struct { Action string; Values map[string]string; Consent bool }\ntype Plan struct { Accepted bool; Name string; Action string; Notices []string }\n\nfunc ComposedLibraryNames() []string { return []string{", spec.Name)
	for i := range dependencies {
		if i > 0 {
			driver.WriteString(",")
		}
		fmt.Fprintf(&driver, "lib%d.ToolName", i)
	}
	driver.WriteString("} }\n\n")
	fmt.Fprintf(&driver, "func Build(input Input) (Plan,error) {\n\tif input.Action == \"\" { return Plan{}, errors.New(\"action is required\") }\n\tif %t && !input.Consent { return Plan{}, errors.New(\"explicit user consent is required for a hardware-related plan\") }\n\treturn Plan{Accepted:true, Name:ToolName, Action:input.Action, Notices:[]string{\"proposal only: adapter execution is not implemented\", \"human review is required before activation\"}},nil\n}\n", spec.NeedsHardwareGuide)
	if err := atomicWrite(filepath.Join(dir, "driver.go"), []byte(driver.String()), 0o644); err != nil {
		return err
	}
	test := fmt.Sprintf(`package %s

import "testing"

func TestBuildRequiresAction(t *testing.T) {
	if _,err:=Build(Input{}); err==nil { t.Fatal("empty action must fail") }
}
func TestBuildReturnsProposalOnly(t *testing.T) {
	plan,err:=Build(Input{Action:"inspect",Consent:true})
	if err!=nil { t.Fatal(err) }
	if !plan.Accepted || plan.Name!=ToolName { t.Fatalf("unexpected plan: %%+v",plan) }
	if ComposedLibraryNames()==nil { t.Fatal("composition metadata must be a non-nil list") }
}
`, pkg)
	if err := atomicWrite(filepath.Join(dir, "driver_test.go"), []byte(test), 0o644); err != nil {
		return err
	}
	meta := libraryMetadata{Name: spec.Name + "_lib", Category: spec.Category, Industry: spec.Industry, Capabilities: append([]string{}, spec.Capabilities...), Dependencies: []string{}}
	for _, dep := range dependencies {
		meta.Dependencies = append(meta.Dependencies, dep.Name)
	}
	if err := writeJSON(filepath.Join(dir, "library.json"), meta); err != nil {
		return err
	}
	readme := fmt.Sprintf("# %s\n\nGenerated library contract for %s. It validates structured inputs and creates proposal-only plans.\n\nComposed dependencies: %s\n\nThe library does not access hardware, the network, or host files. Awaiting human review and merge.\n", spec.Title, spec.Name, strings.Join(meta.Dependencies, ", "))
	return atomicWrite(filepath.Join(dir, "README.md"), []byte(readme), 0o644)
}

func (e *Engine) findLibraryDependencies(spec ToolSpec, maxItems int) []libraryMetadata {
	root := filepath.Join(e.CoreRoot, "libraries", "created")
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil
	}
	type candidate struct {
		meta  libraryMetadata
		score int
	}
	var candidates []candidate
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".staging-") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(root, entry.Name(), "library.json"))
		if err != nil {
			continue
		}
		var meta libraryMetadata
		if json.Unmarshal(raw, &meta) != nil || meta.Name == spec.Name+"_lib" {
			continue
		}
		score := scoreLibrary(spec, meta)
		if score > 0 {
			candidates = append(candidates, candidate{meta: meta, score: score})
		}
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].score == candidates[j].score {
			return candidates[i].meta.Name < candidates[j].meta.Name
		}
		return candidates[i].score > candidates[j].score
	})
	if len(candidates) > maxItems {
		candidates = candidates[:maxItems]
	}
	out := make([]libraryMetadata, 0, len(candidates))
	for _, c := range candidates {
		out = append(out, c.meta)
	}
	return out
}


func generatedCapabilityPlanNote(plan CapabilityPlan) string {
	return fmt.Sprintf("\n\n## Capability graph and requirement plan\n\nA deterministic capability plan is stored in `capability_plan.json`. It records %d requirements, %d native contract matches, %d reusable-library candidates, and %d unresolved capabilities. Native coverage is %.1f%%; this is a planning metric, not a measure of production readiness. Review every acceptance check and unresolved risk before implementation or merge.\n",
		plan.Coverage.Required, plan.Coverage.NativeContracts, plan.Coverage.LibraryCandidates, plan.Coverage.Unresolved, plan.Coverage.NativeCoverage)
}
