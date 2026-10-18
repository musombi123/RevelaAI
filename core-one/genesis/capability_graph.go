package genesis

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// CapabilityPlan is a deterministic, model-optional map from demand requirements to the
// engine's native contract primitives and reusable-library candidates. A candidate is not
// considered production-ready merely because its metadata matches.
type CapabilityPlan struct {
	Version              string                   `json:"version"`
	Invention            string                   `json:"invention"`
	Demand               string                   `json:"demand"`
	GeneratedAt          time.Time                `json:"generated_at"`
	Status               string                   `json:"status"`
	Requirements         []PlannedRequirement      `json:"requirements"`
	Nodes                []CapabilityNode         `json:"nodes"`
	Edges                []CapabilityEdge         `json:"edges"`
	ReusableCandidates   []ReusableLibraryCandidate `json:"reusable_library_candidates"`
	MissingCapabilities  []string                 `json:"missing_capabilities"`
	Coverage              CapabilityCoverage       `json:"coverage"`
	AcceptanceChecks     []string                 `json:"acceptance_checks"`
	UnresolvedRisks      []string                 `json:"unresolved_risks"`
	ExecutionPolicy      string                   `json:"execution_policy"`
	HumanApprovalNeeded  bool                     `json:"human_approval_needed"`
	Notice               string                   `json:"notice"`
}

type PlannedRequirement struct {
	ID                   string   `json:"id"`
	Description          string   `json:"description"`
	Origin               string   `json:"origin"`
	Priority             string   `json:"priority"`
	Capability           string   `json:"capability"`
	Status               string   `json:"status"`
	SatisfiedBy          string   `json:"satisfied_by,omitempty"`
	AcceptanceCriteria   []string `json:"acceptance_criteria"`
}

type CapabilityNode struct {
	ID          string `json:"id"`
	Label       string `json:"label"`
	Kind        string `json:"kind"`
	Status      string `json:"status"`
	Source      string `json:"source"`
	Description string `json:"description"`
}

type CapabilityEdge struct {
	From   string `json:"from"`
	To     string `json:"to"`
	Rel    string `json:"relationship"`
	Reason string `json:"reason"`
}

type ReusableLibraryCandidate struct {
	Name         string   `json:"name"`
	Industry     string   `json:"industry"`
	Category     string   `json:"category"`
	Score        int      `json:"score"`
	Capabilities []string `json:"capabilities"`
	Reason       string   `json:"reason"`
	Status       string   `json:"status"`
}

type CapabilityCoverage struct {
	Required         int     `json:"required"`
	NativeContracts  int     `json:"native_contracts"`
	LibraryCandidates int     `json:"library_candidates"`
	Unresolved       int     `json:"unresolved"`
	NativeCoverage   float64 `json:"native_coverage_percent"`
}

type nativeCapability struct {
	id          string
	label       string
	description string
	terms       []string
}

// The catalogue describes platform-level primitives, not a list of pre-built end-user tools.
// "available_contract" means the engine has a scaffold/guardrail for this capability, not that
// a production adapter or a domain certification is already present.
var nativeCapabilityCatalogue = []nativeCapability{
	{id: "input_validation", label: "Structured input validation", description: "Bounds and validates structured demand/API input.", terms: []string{"structured input validation", "validate structured input", "validate input", "input validation"}},
	{id: "deterministic_planning", label: "Deterministic proposal planning", description: "Derives a deterministic tool specification and proposal-only plan.", terms: []string{"deterministic plan", "deterministic planning", "produce a plan", "planning"}},
	{id: "evidence_provenance", label: "Research provenance", description: "Records source URLs, retrieval status, research findings and an evidence bundle.", terms: []string{"traceable evidence", "evidence provenance", "research provenance", "record evidence"}},
	{id: "api_contract", label: "Documented API contract", description: "Generates an OpenAPI contract and proposal SDKs.", terms: []string{"documented api", "api contract", "openapi", "sdk"}},
	{id: "human_merge_gate", label: "Human approval gate", description: "Stages artifacts for owner review; no automatic merge or activation.", terms: []string{"human review", "human approval", "merge approval", "review before activation"}},
	{id: "artifact_integrity", label: "Artifact integrity metadata", description: "Creates a SHA-256 manifest and optional HMAC integrity evidence.", terms: []string{"artifact hash", "audit integrity", "integrity", "audit trail"}},
	{id: "guardian_screening", label: "Guardian policy screening", description: "Screens demand and untrusted research/specification metadata.", terms: []string{"guardian", "safety screening", "policy check", "harm screening"}},
	{id: "offline_core", label: "Model-optional offline core", description: "Can derive a generic specification without external models or network research.", terms: []string{"offline operation", "model optional", "no model", "without network"}},
	{id: "queue_recovery", label: "Durable queue recovery", description: "Persists queued demand and recovers interrupted queue work.", terms: []string{"queue recovery", "durable queue", "restart recovery", "retry interrupted work"}},
	{id: "test_scaffold", label: "Acceptance-test scaffold", description: "Generates initial tests and CI validation for proposal packages.", terms: []string{"acceptance tests", "test scaffold", "unit tests", "validation tests"}},
	{id: "privacy_consent", label: "Privacy and consent boundary", description: "Documents privacy/consent requirements for relevant integrations; production enforcement remains domain-specific.", terms: []string{"privacy", "consent", "retention", "authorized collection"}},
	{id: "hardware_boundary", label: "Hardware integration boundary", description: "Produces a non-certified hardware guide and requires exact-part review.", terms: []string{"hardware integration", "hardware guide", "device integration", "datasheet"}},
	{id: "hardware_safety", label: "Hardware safety review", description: "Requires schematic, ratings, safe fixture and qualified review before physical connection.", terms: []string{"hardware safety", "emergency stop", "fail safe", "interlock"}},
}

type inferredRequirement struct {
	capability string
	description string
	origin string
	criteria []string
}

func BuildCapabilityPlan(spec ToolSpec, evidence ResearchEvidence, coreRoot string) (CapabilityPlan, error) {
	if strings.TrimSpace(spec.Name) == "" || strings.TrimSpace(spec.Demand) == "" {
		return CapabilityPlan{}, errors.New("capability planner requires a named specification and demand")
	}
	plan := CapabilityPlan{
		Version: "1.0",
		Invention: spec.Name,
		Demand: spec.Demand,
		GeneratedAt: time.Now().UTC(),
		Status: "await_merge",
		Requirements: []PlannedRequirement{},
		Nodes: []CapabilityNode{},
		Edges: []CapabilityEdge{},
		ReusableCandidates: []ReusableLibraryCandidate{},
		MissingCapabilities: []string{},
		AcceptanceChecks: []string{},
		UnresolvedRisks: []string{},
		ExecutionPolicy: "proposal_only",
		HumanApprovalNeeded: true,
		Notice: "Capability matches are planning evidence only. A library candidate is not a verified dependency; missing capabilities require implementation and tests before production use.",
	}

	nativeByID := make(map[string]nativeCapability, len(nativeCapabilityCatalogue))
	for _, capability := range nativeCapabilityCatalogue {
		nativeByID[capability.id] = capability
		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID: capability.id, Label: capability.label, Kind: "native_contract",
			Status: "available_contract", Source: "core-one",
			Description: capability.description,
		})
	}

	libraries, err := loadCapabilityLibraries(filepath.Join(coreRoot, "libraries", "created"))
	if err != nil {
		return CapabilityPlan{}, fmt.Errorf("load reusable library catalogue: %w", err)
	}
	candidates := rankReusableLibraries(spec, libraries, 5)
	for _, candidate := range candidates {
		plan.ReusableCandidates = append(plan.ReusableCandidates, candidate)
		nodeID := "library:" + candidate.Name
		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID: nodeID, Label: candidate.Name, Kind: "reusable_library",
			Status: "candidate_unverified", Source: "core-one/libraries/created/" + candidate.Name,
			Description: "Metadata matched part of this demand. Review dependency API, license, tests and safety before reuse.",
		})
	}

	requirements := inferRequirements(spec)
	nativeCovered := 0
	libraryCovered := 0
	unresolved := 0
	for _, req := range requirements {
		id := "req:" + slugName(req.capability)
		planned := PlannedRequirement{
			ID: id, Description: req.description, Origin: req.origin, Priority: "required",
			Capability: req.capability, Status: "unresolved",
			AcceptanceCriteria: append([]string{}, req.criteria...),
		}
		if node, ok := findNativeCapability(req.capability, nativeByID); ok {
			planned.Status = "native_contract_available"
			planned.SatisfiedBy = node.id
			nativeCovered++
			plan.Edges = append(plan.Edges, CapabilityEdge{From: id, To: node.id, Rel: "uses_contract", Reason: "Requirement maps to an existing Core-One contract primitive; domain implementation still needs validation."})
		} else if candidate, ok := bestLibraryForRequirement(req.capability, candidates); ok {
			planned.Status = "reuse_candidate_unverified"
			planned.SatisfiedBy = "library:" + candidate.Name
			libraryCovered++
			plan.Edges = append(plan.Edges, CapabilityEdge{From: id, To: "library:" + candidate.Name, Rel: "candidate_dependency", Reason: "Capability metadata overlaps; verify behavior and dependency quality before adoption."})
		} else {
			unresolved++
			plan.MissingCapabilities = append(plan.MissingCapabilities, req.capability)
			plan.Nodes = append(plan.Nodes, CapabilityNode{
				ID: id, Label: req.capability, Kind: "requirement_gap",
				Status: "implementation_required", Source: req.origin,
				Description: req.description,
			})
		}
		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID: id, Label: req.capability, Kind: "requirement",
			Status: planned.Status, Source: req.origin, Description: req.description,
		})
		plan.Requirements = append(plan.Requirements, planned)
		plan.AcceptanceChecks = append(plan.AcceptanceChecks, req.criteria...)
	}
	// Express safety dependencies between hardware requirements and the approval/consent gates.
	for _, req := range plan.Requirements {
		if strings.Contains(strings.ToLower(req.Capability), "hardware") || strings.Contains(strings.ToLower(req.Capability), "actuator") || strings.Contains(strings.ToLower(req.Capability), "device control") {
			if _, ok := nativeByID["hardware_safety"]; ok {
				plan.Edges = append(plan.Edges,
					CapabilityEdge{From: req.ID, To: "hardware_safety", Rel: "safety_prerequisite", Reason: "Hardware-related proposals must have safe-fixture, ratings and qualified-review criteria."},
					CapabilityEdge{From: req.ID, To: "human_merge_gate", Rel: "approval_prerequisite", Reason: "No hardware plan may be activated without owner approval."})
			}
		}
		if strings.Contains(strings.ToLower(req.Capability), "privacy") || strings.Contains(strings.ToLower(req.Capability), "consent") || strings.Contains(strings.ToLower(req.Capability), "authorized collection") {
			plan.Edges = append(plan.Edges, CapabilityEdge{From: req.ID, To: "privacy_consent", Rel: "policy_prerequisite", Reason: "Collection involving people or personal information needs a documented lawful purpose, access controls and retention policy."})
		}
	}
	required := len(plan.Requirements)
	coverage := 0.0
	if required > 0 {
		coverage = (float64(nativeCovered) / float64(required)) * 100
	}
	plan.Coverage = CapabilityCoverage{Required: required, NativeContracts: nativeCovered, LibraryCandidates: libraryCovered, Unresolved: unresolved, NativeCoverage: coverage}
	if unresolved > 0 {
		plan.Status = "await_merge_with_implementation_gaps"
		plan.UnresolvedRisks = append(plan.UnresolvedRisks, "One or more requirements have no matching native contract or reusable-library candidate.")
	}
	if libraryCovered > 0 {
		plan.UnresolvedRisks = append(plan.UnresolvedRisks, "Reusable-library matches are unverified candidates; matching metadata is not proof of correctness or compatibility.")
	}
	if spec.NeedsHardwareGuide {
		plan.UnresolvedRisks = append(plan.UnresolvedRisks,
			"Hardware guide is a reference scaffold, not a certified wiring diagram; exact part numbers, datasheets, electrical ratings and qualified review are mandatory.",
			"Do not attach physical actuators or mains-powered loads until the approved schematic, interlocks and safe-fixture tests pass.")
	}
	if strings.Contains(strings.ToLower(spec.Demand), "privacy") || containsAny(strings.ToLower(spec.Demand), "camera", "cctv", "patient", "student", "personal data") {
		plan.UnresolvedRisks = append(plan.UnresolvedRisks, "Review lawful purpose, authorization, data minimization, retention/deletion, access controls and audit requirements for the target jurisdiction.")
	}
	if len(evidence.Sources) == 0 {
		plan.UnresolvedRisks = append(plan.UnresolvedRisks, "No research source records were supplied; validate the requirements and external assumptions before implementation.")
	}
	plan.AcceptanceChecks = append(plan.AcceptanceChecks,
		"Run generated unit and integration tests in an isolated environment.",
		"Verify every selected dependency's public API, version, license and security posture.",
		"Confirm each unresolved capability has an implementation task and a passing acceptance test before production use.",
		"Require owner review and explicit merge; never execute generated source automatically.")
	plan.AcceptanceChecks = uniqueStrings(plan.AcceptanceChecks)
	plan.MissingCapabilities = uniqueStrings(plan.MissingCapabilities)
	plan.UnresolvedRisks = uniqueStrings(plan.UnresolvedRisks)
	return plan, nil
}

func inferRequirements(spec ToolSpec) []inferredRequirement {
	out := make([]inferredRequirement, 0, len(spec.Capabilities)+10)
	seen := map[string]bool{}
	add := func(capability, description, origin string, criteria ...string) {
		key := slugName(capability)
		if key == "" || seen[key] { return }
		seen[key] = true
		out = append(out, inferredRequirement{capability: capability, description: description, origin: origin, criteria: criteria})
	}
	for _, cap := range spec.Capabilities {
		add(cap, "Demand-derived capability: "+cap, "tool_specification",
			"Demonstrate the capability with a named automated test: "+cap+".",
			"Document limitations and the behavior that remains proposal-only.")
	}
	demand := strings.ToLower(spec.Demand)
	if containsAny(demand, "offline", "without internet", "no network") {
		add("offline operation", "Core planning and the documented minimum workflow must operate without an external model or network.", "demand_analysis",
			"Run the invention flow with GENESIS_OFFLINE=1 and no model endpoint configured.",
			"Fail clearly when an optional online integration is unavailable; preserve the evidence and proposal status.")
	}
	if containsAny(demand, "queue", "daemon", "scheduler", "background job", "retry", "restart") {
		add("durable queue recovery", "Work items must survive interruption and be processed without silently losing their durable record.", "demand_analysis",
			"Simulate cancellation/crash after a queue claim and confirm the item can be recovered.",
			"Repeat a processing attempt and verify idempotent status handling.")
	}
	if containsAny(demand, "file", "document", "storage", "vault", "backup", "archive") {
		add("data integrity and recovery", "Stored artifacts require verifiable integrity and a documented recovery/restore path.", "demand_analysis",
			"Corrupt a test artifact and verify integrity validation detects it.",
			"Document backup, restore, deletion and failure recovery; do not invent cryptographic guarantees.")
	}
	if containsAny(demand, "payment", "transaction", "billing", "checkout", "wallet") {
		add("transaction idempotency and reconciliation", "Financial operations require duplicate-request protection and reconciliation before any live transaction integration.", "demand_analysis",
			"Replay the same test transaction and confirm duplicate handling is deterministic.",
			"Reconcile recorded test transactions against a simulated provider ledger.",
			"Keep live payment execution disabled until provider sandbox and compliance review pass.")
	}
	if containsAny(demand, "camera", "cctv", "image capture", "video capture", "sensor collecting people") {
		add("authorized data collection and retention", "Capture-related functionality requires an approved purpose, access control, data minimization and retention/deletion rules.", "demand_analysis",
			"Verify access is denied without authorization.",
			"Verify retention expiry and deletion behavior using synthetic test data.",
			"Verify visible notice and a documented lawful purpose before deployment.")
	}
	if containsAny(demand, "motor", "mill", "pump", "valve", "actuator", "robot", "machine", "industrial control") {
		add("hardware safety and fail-safe control", "Physical control requires verified electrical ratings, independent safeguards and a safe failure state.", "demand_analysis",
			"Run simulation or hardware-in-the-loop tests with a dummy load before real hardware is connected.",
			"Verify an emergency stop/interlock or equivalent independent safe shutdown where the design requires it.",
			"Verify loss of sensor, power or network does not cause uncontrolled actuation.")
	}
	if containsAny(demand, "remote", "network", "internet", "multi-user", "api client") {
		add("authenticated remote access", "Remote access requires authentication, transport security, rate limits and authorization checks.", "demand_analysis",
			"Confirm unauthenticated remote calls are rejected.",
			"Confirm remote traffic uses TLS outside a loopback development environment.",
			"Test rate limits and least-privilege authorization.")
	}
	if containsAny(demand, "ai", "model", "neural", "inference", "machine learning") {
		add("model adapter isolation and provenance", "Optional model use must be bounded, traceable and separated from code execution.", "demand_analysis",
			"Verify operation falls back safely when the model endpoint is unavailable.",
			"Verify model output cannot directly execute commands or write arbitrary source files.",
			"Record model identifier and the source/evidence context used for each proposal.")
	}
	if containsAny(demand, "health", "clinic", "medical", "patient", "diagnosis") {
		add("domain expert validation and privacy review", "Health-related functionality requires domain expert validation, privacy review and applicable regulatory assessment.", "demand_analysis",
			"Require domain-expert sign-off on clinical/operational requirements before any real-world use.",
			"Test with synthetic data only until approved safeguards and intended use are documented.")
	}
	if spec.NeedsHardwareGuide {
		add("hardware integration and datasheet verification", "A hardware proposal needs part-specific interfaces, ratings and a reviewed bill of materials.", "hardware_classification",
			"List exact manufacturer part numbers and cite their official datasheets.",
			"Verify voltage, current, isolation, protection and connector assignments against the actual parts.",
			"Keep mains wiring and hazardous loads disconnected during initial tests.")
	}
	sort.Slice(out, func(i, j int) bool { return slugName(out[i].capability) < slugName(out[j].capability) })
	return out
}

func findNativeCapability(requirement string, catalogue map[string]nativeCapability) (nativeCapability, bool) {
	lower := strings.ToLower(requirement)
	for _, capability := range catalogue {
		for _, term := range capability.terms {
			if lower == term || strings.Contains(lower, term) || strings.Contains(term, lower) {
				return capability, true
			}
		}
	}
	return nativeCapability{}, false
}

func loadCapabilityLibraries(root string) ([]libraryMetadata, error) {
	entries, err := os.ReadDir(root)
	if os.IsNotExist(err) { return []libraryMetadata{}, nil }
	if err != nil { return nil, err }
	out := make([]libraryMetadata, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".staging-") { continue }
		path := filepath.Join(root, entry.Name(), "library.json")
		info, err := os.Lstat(path)
		if os.IsNotExist(err) { continue }
		if err != nil { return nil, err }
		if !info.Mode().IsRegular() { continue }
		raw, err := os.ReadFile(path)
		if err != nil { return nil, err }
		var meta libraryMetadata
		if err := json.Unmarshal(raw, &meta); err != nil { continue }
		if meta.Name == "" || len(meta.Capabilities) > 100 { continue }
		out = append(out, meta)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

func rankReusableLibraries(spec ToolSpec, libraries []libraryMetadata, limit int) []ReusableLibraryCandidate {
	out := make([]ReusableLibraryCandidate, 0, len(libraries))
	for _, lib := range libraries {
		score := scoreLibrary(spec, lib)
		if score <= 0 { continue }
		reason := "Capability metadata has partial overlap; verify implementation and tests before composing."
		if lib.Industry == spec.Industry && lib.Category == spec.Category {
			reason = "Category and industry match, and at least one capability overlaps; verification is still required."
		}
		out = append(out, ReusableLibraryCandidate{Name: lib.Name, Industry: lib.Industry, Category: lib.Category, Score: score, Capabilities: append([]string{}, lib.Capabilities...), Reason: reason, Status: "candidate_unverified"})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Score == out[j].Score { return out[i].Name < out[j].Name }
		return out[i].Score > out[j].Score
	})
	if limit > 0 && len(out) > limit { out = out[:limit] }
	return out
}

func scoreLibrary(spec ToolSpec, lib libraryMetadata) int {
	score := 0
	if lib.Industry != "" && lib.Industry == spec.Industry && spec.Industry != "general" { score += 4 }
	if lib.Category != "" && lib.Category == spec.Category { score += 2 }
	for _, required := range spec.Capabilities {
		best := 0
		for _, existing := range lib.Capabilities {
			if capabilityLexicalOverlap(required, existing) > best { best = capabilityLexicalOverlap(required, existing) }
		}
		if best >= 2 { score += best }
	}
	if len(lib.Capabilities) == 0 { score -= 2 }
	return score
}

func bestLibraryForRequirement(requirement string, candidates []ReusableLibraryCandidate) (ReusableLibraryCandidate, bool) {
	bestScore := 0
	var best ReusableLibraryCandidate
	for _, candidate := range candidates {
		for _, cap := range candidate.Capabilities {
			s := capabilityLexicalOverlap(requirement, cap)
			if s > bestScore {
				bestScore = s
				best = candidate
			}
		}
	}
	return best, bestScore >= 2
}

func capabilityLexicalOverlap(a, b string) int {
	left, right := normalizedCapabilityTokens(a), normalizedCapabilityTokens(b)
	score := 0
	for token := range left { if right[token] { score++ } }
	return score
}

func normalizedCapabilityTokens(value string) map[string]bool {
	tokens := strings.FieldsFunc(strings.ToLower(value), func(r rune) bool {
		return !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9')
	})
	out := map[string]bool{}
	for _, token := range tokens {
		switch token {
		case "the", "and", "for", "from", "with", "without", "into", "that", "this", "must", "shall", "before", "after", "only", "using", "use", "support", "supports", "required", "requires", "provide", "provides", "create", "creates", "produce", "produces", "record", "records":
			continue
		case "validate", "validates", "validation", "validated": token = "valid"
		case "inputs", "input": token = "input"
		case "plans", "planning", "planned": token = "plan"
		case "tests", "testing", "tested": token = "test"
		case "documents", "documented", "documentation": token = "document"
		case "authenticated", "authentication", "authorisation", "authorization": token = "auth"
		case "privacy-aware": token = "privacy"
		case "traceable", "tracing": token = "trace"
		}
		if len(token) > 2 { out[token] = true }
	}
	return out
}

func uniqueStrings(values []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] { continue }
		seen[value] = true
		out = append(out, value)
	}
	return out
}
