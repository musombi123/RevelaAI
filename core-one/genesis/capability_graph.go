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

	worldguardian "revela-worldwide.local/libs/guardian"
)

// CapabilityPlan is a deterministic, model-optional capability graph.
// It distinguishes platform contracts from verified implementations,
// unverified reusable-library candidates, and unresolved requirements.
type CapabilityPlan struct {
	Version             string                    `json:"version"`
	SchemaVersion       string                    `json:"schema_version"`
	PlanID              string                    `json:"plan_id"`
	Invention           string                    `json:"invention"`
	Demand              string                    `json:"demand"`
	GeneratedAt         time.Time                 `json:"generated_at"`
	Status              string                    `json:"status"`
	Requirements        []PlannedRequirement      `json:"requirements"`
	Nodes               []CapabilityNode          `json:"nodes"`
	Edges               []CapabilityEdge         `json:"edges"`
	ReusableCandidates  []ReusableLibraryCandidate `json:"reusable_library_candidates"`
	MissingCapabilities []string                  `json:"missing_capabilities"`
	Coverage             CapabilityCoverage        `json:"coverage"`
	Evidence             CapabilityEvidenceSummary `json:"evidence_summary"`
	AcceptanceChecks     []string                  `json:"acceptance_checks"`
	UnresolvedRisks      []string                  `json:"unresolved_risks"`
	ExecutionPolicy      string                    `json:"execution_policy"`
	HumanApprovalNeeded  bool                      `json:"human_approval_needed"`
	Notice               string                    `json:"notice"`
}

type PlannedRequirement struct {
	ID                 string   `json:"id"`
	Description        string   `json:"description"`
	Origin             string   `json:"origin"`
	Priority           string   `json:"priority"`
	Capability         string   `json:"capability"`
	Status             string   `json:"status"`
	SatisfiedBy        string   `json:"satisfied_by,omitempty"`
	AcceptanceCriteria []string `json:"acceptance_criteria"`
	EvidenceRefs       []string `json:"evidence_refs,omitempty"`
	VerificationGate   string   `json:"verification_gate"`
	MatchConfidence    string   `json:"match_confidence,omitempty"`
}

type CapabilityNode struct {
	ID          string `json:"id"`
	Label       string `json:"label"`
	Kind        string `json:"kind"`
	Status      string `json:"status"`
	Source      string `json:"source"`
	Description string `json:"description"`
	Trust       string `json:"trust,omitempty"`
}

type CapabilityEdge struct {
	From   string `json:"from"`
	To     string `json:"to"`
	Rel    string `json:"relationship"`
	Reason string `json:"reason"`
}

type ReusableLibraryCandidate struct {
	Name                  string   `json:"name"`
	Industry              string   `json:"industry"`
	Category              string   `json:"category"`
	Score                 int      `json:"score"`
	Capabilities          []string `json:"capabilities"`
	Dependencies          []string `json:"dependencies,omitempty"`
	MatchedCapabilities   []string `json:"matched_capabilities,omitempty"`
	MatchReasons          []string `json:"match_reasons,omitempty"`
	Reason                string   `json:"reason"`
	Status                string   `json:"status"`
	SourcePath            string   `json:"source_path,omitempty"`
	VerificationRequired  bool     `json:"verification_required"`
}

type CapabilityCoverage struct {
	Required                    int     `json:"required"`
	NativeContracts             int     `json:"native_contracts"`
	LibraryCandidates           int     `json:"library_candidates"`
	Unresolved                  int     `json:"unresolved"`
	UnverifiedCandidates        int     `json:"unverified_candidates"`
	RequirementsWithEvidence    int     `json:"requirements_with_evidence"`
	NativeCoverage              float64 `json:"native_coverage_percent"`
	CandidateCoverage           float64 `json:"candidate_coverage_percent"`
	UnresolvedPercent           float64 `json:"unresolved_percent"`
	VerifiedImplementationCount int     `json:"verified_implementation_count"`
}

type CapabilityEvidenceSummary struct {
	Mode                   string `json:"mode,omitempty"`
	ResearchID             string `json:"research_id,omitempty"`
	CollectedAt            time.Time `json:"collected_at,omitempty"`
	SourceRecords          int    `json:"source_records"`
	RetrievedSources       int    `json:"retrieved_sources"`
	Findings                int    `json:"findings"`
	RequirementsWithSources int   `json:"requirements_with_source_refs"`
	Notice                  string `json:"notice"`
}

type nativeCapability struct {
	id          string
	label       string
	description string
	terms       []string
}

type inferredRequirement struct {
	capability string
	description string
	origin     string
	priority   string
	criteria   []string
	gate       string
}

type capabilityLibraryMatch struct {
	candidate ReusableLibraryCandidate
	score     int
}

// These are platform-level contract primitives. Their presence means that
// Genesis knows how to plan and guard a capability, not that a production
// adapter, domain implementation, certification, or external service exists.
var nativeCapabilityCatalogue = []nativeCapability{
	{
		id: "input_validation",
		label: "Structured input validation",
		description: "Defines input validation and bounded structured request handling.",
		terms: []string{
			"structured input validation",
			"validate structured input",
			"validate input",
			"input validation",
			"structured inputs",
		},
	},
	{
		id: "deterministic_planning",
		label: "Deterministic proposal planning",
		description: "Derives a bounded proposal specification and a reviewable capability plan.",
		terms: []string{
			"deterministic plan",
			"deterministic planning",
			"produce a deterministic plan",
			"deterministic proposal planning",
			"produce a plan",
		},
	},
	{
		id: "evidence_provenance",
		label: "Research provenance",
		description: "Records research source metadata, retrieval status, findings, and evidence bundles.",
		terms: []string{
			"traceable evidence",
			"evidence provenance",
			"research provenance",
			"record evidence",
			"research source records",
		},
	},
	{
		id: "api_contract",
		label: "Documented API contract",
		description: "Produces a reviewable API contract and proposal SDK artifacts.",
		terms: []string{
			"documented api",
			"api contract",
			"openapi",
			"sdk",
			"documented api contract",
		},
	},
	{
		id: "human_merge_gate",
		label: "Human approval gate",
		description: "Stages artifacts for review and prevents automatic merge or activation.",
		terms: []string{
			"human review",
			"human approval",
			"merge approval",
			"review before activation",
			"human approval gate",
		},
	},
	{
		id: "artifact_integrity",
		label: "Artifact integrity metadata",
		description: "Produces artifact hashes and integrity metadata for later verification.",
		terms: []string{
			"artifact hash",
			"artifact integrity",
			"audit integrity",
			"audit trail",
			"artifact integrity metadata",
		},
	},
	{
		id: "guardian_screening",
		label: "Guardian policy screening",
		description: "Screens demands, research evidence, and model-proposed metadata against Guardian policy.",
		terms: []string{
			"guardian",
			"safety screening",
			"policy check",
			"harm screening",
			"guardian policy screening",
		},
	},
	{
		id: "offline_core",
		label: "Model-optional offline core",
		description: "Allows generic planning without depending on a model endpoint.",
		terms: []string{
			"offline operation",
			"model optional",
			"no model",
			"without network",
			"offline core",
		},
	},
	{
		id: "queue_recovery",
		label: "Durable queue recovery",
		description: "Persists queued demands and supports recovery of interrupted work.",
		terms: []string{
			"queue recovery",
			"durable queue",
			"restart recovery",
			"retry interrupted work",
			"durable queue recovery",
		},
	},
	{
		id: "test_scaffold",
		label: "Acceptance-test scaffold",
		description: "Provides a starting point for generated tests and automated validation.",
		terms: []string{
			"acceptance tests",
			"test scaffold",
			"unit tests",
			"validation tests",
			"acceptance test scaffold",
		},
	},
	{
		id: "privacy_consent",
		label: "Privacy and consent boundary",
		description: "Documents privacy and consent boundaries; actual enforcement remains domain-specific.",
		terms: []string{
			"privacy",
			"consent",
			"explicit consent",
			"retention",
			"authorized collection",
			"authorized data collection and retention",
			"privacy and consent boundary",
		},
	},
	{
		id: "hardware_boundary",
		label: "Hardware integration boundary",
		description: "Produces a non-certified hardware guide and identifies where exact-part review is required.",
		terms: []string{
			"hardware integration",
			"hardware guide",
			"device integration",
			"datasheet",
			"hardware integration and datasheet verification",
		},
	},
	{
		id: "hardware_safety",
		label: "Hardware safety review",
		description: "Requires part ratings, safe fixtures, protective measures, and qualified review before physical connection.",
		terms: []string{
			"hardware safety",
			"emergency stop",
			"fail safe",
			"interlock",
			"hardware safety and fail safe control",
		},
	},
	{
		id: "authentication",
		label: "Authentication boundary",
		description: "Defines the need for verified identity when a feature is protected by authentication.",
		terms: []string{
			"authentication",
			"authenticated remote access",
			"verify user identity",
		},
	},
	{
		id: "authorization",
		label: "Authorization boundary",
		description: "Defines permission checks and least-privilege access requirements.",
		terms: []string{
			"authorization",
			"access control",
			"least privilege",
			"least privilege authorization",
		},
	},
	{
		id: "observability",
		label: "Operational observability",
		description: "Plans traceable lifecycle events and operational error reporting.",
		terms: []string{
			"observability",
			"structured logging",
			"operational monitoring",
			"traceable lifecycle events",
		},
	},
	{
		id: "error_handling",
		label: "Explicit error handling",
		description: "Requires predictable failures, actionable errors, and documented recovery behavior.",
		terms: []string{
			"error handling",
			"failure recovery",
			"documented error behavior",
			"predictable failures",
		},
	},
	{
		id: "configuration_secrets",
		label: "Configuration and secrets boundary",
		description: "Requires environment-specific configuration and prohibits hard-coded credentials.",
		terms: []string{
			"secrets handling",
			"configuration security",
			"secret management",
			"environment configuration",
		},
	},
	{
		id: "data_lifecycle",
		label: "Data lifecycle controls",
		description: "Plans data retention, export, deletion, backup, and recovery requirements.",
		terms: []string{
			"data lifecycle",
			"retention and deletion",
			"backup and recovery",
			"data integrity and recovery",
		},
	},
	{
		id: "rate_limiting",
		label: "Abuse and rate-limit boundary",
		description: "Defines throttling and abuse controls for exposed endpoints where applicable.",
		terms: []string{
			"rate limiting",
			"rate limits",
			"abuse protection",
			"request throttling",
		},
	},
	{
		id: "localization",
		label: "Worldwide localization boundary",
		description: "Carries resolved country and language context into planning without assuming full localization or compliance.",
		terms: []string{
			"worldwide localization",
			"country and language localization",
			"localized user experience",
			"country specific adaptation",
		},
	},
	{
		id: "api_versioning",
		label: "API version compatibility",
		description: "Requires explicit contract and migration review when changing public APIs or SDKs.",
		terms: []string{
			"api versioning",
			"api compatibility",
			"backward compatibility",
			"migration compatibility",
		},
	},
	{
		id: "accessibility",
		label: "Accessibility requirements boundary",
		description: "Tracks accessibility acceptance criteria and requires validation for the intended interface.",
		terms: []string{
			"accessibility",
			"accessible interface",
			"keyboard navigation",
			"screen reader support",
		},
	},
}

const (
	maxCapabilityDemandBytes    = 4000
	maxCapabilityEvidenceItems  = 200
	maxCapabilityFindingItems   = 100
	maxCapabilityLibraryFile    = 512 * 1024
	maxCapabilityLibraries      = 2000
	maxCapabilityCandidates     = 5
	maxCapabilityTermsPerSpec   = 100
	maxCapabilityTextBytes      = 4000
	maxCapabilityLibraryItems   = 100
)

// BuildCapabilityPlan maps the demand and deterministic ToolSpec to a graph
// of requirements, native contracts, reusable-library candidates, evidence,
// dependency edges, acceptance checks, and unresolved risks.
//
// Library metadata is treated as untrusted. Matching never upgrades an
// existing library to verified or production-ready status.
func BuildCapabilityPlan(
	spec ToolSpec,
	evidence ResearchEvidence,
	coreRoot string,
) (CapabilityPlan, error) {
	if strings.TrimSpace(spec.Name) == "" ||
		strings.TrimSpace(spec.Demand) == "" {
		return CapabilityPlan{}, errors.New(
			"capability planner requires a named specification and demand",
		)
	}

	spec.Name = strings.TrimSpace(spec.Name)
	spec.Demand = strings.TrimSpace(spec.Demand)

	if !validResourceName(spec.Name) {
		return CapabilityPlan{}, errors.New(
			"capability planner received an invalid invention name",
		)
	}

	if len(spec.Demand) > maxCapabilityDemandBytes {
		return CapabilityPlan{}, errors.New(
			"capability planner demand exceeds the configured size limit",
		)
	}

	if len(spec.Capabilities) > maxCapabilityTermsPerSpec ||
		len(spec.Inputs) > maxCapabilityTermsPerSpec ||
		len(spec.Outputs) > maxCapabilityTermsPerSpec ||
		len(spec.Safeguards) > maxCapabilityTermsPerSpec {
		return CapabilityPlan{}, errors.New(
			"capability planner received too many specification metadata items",
		)
	}

	if err := validateCapabilityEvidence(evidence); err != nil {
		return CapabilityPlan{}, err
	}

	decision := worldguardian.CheckText(spec.Demand)
	if !decision.Allowed {
		return CapabilityPlan{}, fmt.Errorf(
			"%w: capability planner demand rejected by worldwide Guardian",
			ErrBlocked,
		)
	}

	plan := CapabilityPlan{
		Version:             "2.0",
		SchemaVersion:       "genesis.capability-plan.v2",
		PlanID:              newID("capplan"),
		Invention:            spec.Name,
		Demand:              spec.Demand,
		GeneratedAt:         time.Now().UTC(),
		Status:               "await_merge",
		Requirements:         []PlannedRequirement{},
		Nodes:                []CapabilityNode{},
		Edges:                []CapabilityEdge{},
		ReusableCandidates:   []ReusableLibraryCandidate{},
		MissingCapabilities:  []string{},
		AcceptanceChecks:     []string{},
		UnresolvedRisks:      []string{},
		ExecutionPolicy:      "proposal_only",
		HumanApprovalNeeded:  true,
		Notice: "Capability matches are planning evidence only. Native contracts are not verified domain implementations; library matches are unverified candidates. All unresolved requirements require implementation and testing before production use.",
		Evidence: CapabilityEvidenceSummary{
			Mode:        evidence.Mode,
			ResearchID:  evidence.ID,
			CollectedAt: evidence.CollectedAt,
			SourceRecords: len(evidence.Sources),
			Findings:    len(evidence.Findings),
			Notice: "Research records are provenance hints. Source retrieval does not establish correctness, safety, legal compliance, market demand, or completeness.",
		},
	}

	nativeByID := make(map[string]nativeCapability, len(nativeCapabilityCatalogue))
	for _, capability := range nativeCapabilityCatalogue {
		nativeByID[capability.id] = capability

		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID:          capability.id,
			Label:       capability.label,
			Kind:        "native_contract",
			Status:      "available_contract",
			Source:      "core-one",
			Description: capability.description,
			Trust:       "platform_catalogue",
		})
	}

	libraries, err := loadCapabilityLibraries(
		filepath.Join(coreRoot, "libraries", "created"),
	)
	if err != nil {
		return CapabilityPlan{}, fmt.Errorf(
			"load reusable library catalogue: %w",
			err,
		)
	}

	candidates := rankReusableLibraries(
		spec,
		libraries,
		maxCapabilityCandidates,
	)

	for _, candidate := range candidates {
		plan.ReusableCandidates = append(
			plan.ReusableCandidates,
			candidate,
		)

		nodeID := "library:" + candidate.Name
		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID:          nodeID,
			Label:       candidate.Name,
			Kind:        "reusable_library",
			Status:      "candidate_unverified",
			Source:      candidate.SourcePath,
			Description: candidate.Reason,
			Trust:       "unverified_metadata",
		})
	}

	// Evidence nodes make source references navigable from requirements while
	// preserving the distinction between a retrieved source and a verified fact.
	sourceNodes := make(map[string]ResearchSource)
	for _, source := range sortedCapabilitySources(evidence.Sources) {
		sourceID := capabilitySourceID(source)
		if sourceID == "" {
			continue
		}

		sourceNodes[sourceID] = source

		status := "unverified"
		if source.Status == "retrieved" {
			status = "retrieved_unverified"
			plan.Evidence.RetrievedSources++
		}

		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID:          sourceID,
			Label:       capabilitySourceLabel(source),
			Kind:        "research_source",
			Status:      status,
			Source:      source.URL,
			Description: "Research provenance record. Retrieved status does not independently verify its claims.",
			Trust:       "external_untrusted",
		})

		plan.Edges = append(plan.Edges, CapabilityEdge{
			From:   "evidence",
			To:     sourceID,
			Rel:    "contains_source",
			Reason: "The source is recorded as part of the research evidence bundle.",
		})
	}

	// Always map the minimum reviewable proposal lifecycle explicitly.
	requirements := inferRequirements(spec)
	nativeCovered := 0
	libraryCovered := 0
	unresolved := 0
	requirementsWithSources := 0

	for _, req := range requirements {
		id := "req:" + slugName(req.capability)

		planned := PlannedRequirement{
			ID:                 id,
			Description:        req.description,
			Origin:             req.origin,
			Priority:           req.priority,
			Capability:         req.capability,
			Status:             "unresolved",
			AcceptanceCriteria: append([]string{}, req.criteria...),
			EvidenceRefs:       []string{},
			VerificationGate:   req.gate,
		}

		planned.EvidenceRefs = findRelevantCapabilityEvidence(
			req,
			evidence,
			sourceNodes,
		)

		if len(planned.EvidenceRefs) > 0 {
			requirementsWithSources++
		}

		if native, ok := findNativeCapability(req.capability, nativeByID); ok {
			planned.Status = "native_contract_available"
			planned.SatisfiedBy = native.id
			planned.MatchConfidence = "exact_alias"
			nativeCovered++

			plan.Edges = append(plan.Edges, CapabilityEdge{
				From:   id,
				To:     native.id,
				Rel:    "uses_contract",
				Reason: "Requirement maps to an explicit native contract alias. Domain-specific implementation and verification are still required.",
			})
		} else if candidate, score, ok := bestLibraryForRequirement(
			req.capability,
			candidates,
		); ok {
			planned.Status = "reuse_candidate_unverified"
			planned.SatisfiedBy = "library:" + candidate.Name
			planned.MatchConfidence = capabilityMatchConfidence(score)
			libraryCovered++

			plan.Edges = append(plan.Edges, CapabilityEdge{
				From:   id,
				To:     "library:" + candidate.Name,
				Rel:    "candidate_dependency",
				Reason: "Capability metadata overlaps with this requirement. Verify public API, behavior, dependencies, licensing, security, and tests before adoption.",
			})
		} else {
			unresolved++

			plan.MissingCapabilities = append(
				plan.MissingCapabilities,
				req.capability,
			)

			gapID := "gap:" + slugName(req.capability)
			plan.Nodes = append(plan.Nodes, CapabilityNode{
				ID:          gapID,
				Label:       req.capability,
				Kind:        "capability_gap",
				Status:      "implementation_required",
				Source:      req.origin,
				Description: req.description,
				Trust:       "derived_requirement",
			})

			plan.Edges = append(plan.Edges, CapabilityEdge{
				From:   id,
				To:     gapID,
				Rel:    "requires_implementation",
				Reason: "No exact native contract or sufficiently matching reusable-library candidate was found.",
			})
		}

		plan.Nodes = append(plan.Nodes, CapabilityNode{
			ID:          id,
			Label:       req.capability,
			Kind:        "requirement",
			Status:      planned.Status,
			Source:      req.origin,
			Description: req.description,
			Trust:       "derived_requirement",
		})

		for _, sourceID := range planned.EvidenceRefs {
			plan.Edges = append(plan.Edges, CapabilityEdge{
				From:   id,
				To:     sourceID,
				Rel:    "related_evidence",
				Reason: "Requirement terminology overlaps with the source metadata; this is a relevance link, not validation of the source's claims.",
			})
		}

		plan.Requirements = append(plan.Requirements, planned)
		plan.AcceptanceChecks = append(
			plan.AcceptanceChecks,
			req.criteria...,
		)
	}

	// Add explicit safety and policy prerequisites where the inferred
	// requirement involves physical control or personal information.
	for _, req := range plan.Requirements {
		lower := strings.ToLower(req.Capability)

		if containsAny(
			lower,
			"hardware",
			"actuator",
			"device control",
			"motor",
			"pump",
			"valve",
		) {
			plan.Edges = append(plan.Edges,
				CapabilityEdge{
					From: req.ID,
					To:   "hardware_safety",
					Rel:  "safety_prerequisite",
					Reason: "Physical-control proposals require part-specific ratings, safe-fixture testing, independent protection where appropriate, and qualified review.",
				},
				CapabilityEdge{
					From: req.ID,
					To:   "human_merge_gate",
					Rel:  "approval_prerequisite",
					Reason: "Hardware-related plans must not be activated without explicit owner approval.",
				},
			)
		}

		if containsAny(
			lower,
			"privacy",
			"consent",
			"personal data",
			"authorized collection",
			"retention",
		) {
			plan.Edges = append(plan.Edges, CapabilityEdge{
				From: req.ID,
				To:   "privacy_consent",
				Rel:  "policy_prerequisite",
				Reason: "Collection involving people or personal information requires documented purpose, authorization, data minimization, access controls, and retention/deletion policy.",
			})
		}

		if containsAny(
			lower,
			"authentication",
			"authorization",
			"remote access",
		) {
			plan.Edges = append(plan.Edges, CapabilityEdge{
				From: req.ID,
				To:   "authorization",
				Rel:  "security_prerequisite",
				Reason: "Protected operations require explicit authorization and least-privilege checks.",
			})
		}
	}

	required := len(plan.Requirements)

	var nativeCoverage float64
	var candidateCoverage float64
	var unresolvedPercent float64

	if required > 0 {
		nativeCoverage = float64(nativeCovered) * 100 / float64(required)
		candidateCoverage = float64(libraryCovered) * 100 / float64(required)
		unresolvedPercent = float64(unresolved) * 100 / float64(required)
	}

	plan.Coverage = CapabilityCoverage{
		Required:                    required,
		NativeContracts:             nativeCovered,
		LibraryCandidates:           libraryCovered,
		Unresolved:                  unresolved,
		UnverifiedCandidates:        libraryCovered,
		RequirementsWithEvidence:    requirementsWithSources,
		NativeCoverage:              nativeCoverage,
		CandidateCoverage:           candidateCoverage,
		UnresolvedPercent:           unresolvedPercent,
		VerifiedImplementationCount: 0,
	}

	plan.Evidence.RequirementsWithSources = requirementsWithSources

	if unresolved > 0 {
		plan.Status = "await_merge_with_implementation_gaps"
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"At least one requirement has no matching native contract or metadata-compatible reusable-library candidate.",
		)
	} else if libraryCovered > 0 {
		plan.Status = "await_merge_with_unverified_dependencies"
	} else {
		plan.Status = "await_merge"
	}

	if libraryCovered > 0 {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"Reusable-library candidates are unverified metadata matches. Matching does not establish implementation correctness, API compatibility, license suitability, security, maintenance status, or fitness for production.",
		)
	}

	if spec.NeedsHardwareGuide {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"Hardware guidance is a reference scaffold, not a certified wiring diagram. Exact parts, manufacturer datasheets, ratings, protection, and qualified review remain mandatory.",
			"Do not connect mains wiring, hazardous loads, or physical actuators until the reviewed schematic, interlocks, and safe-fixture tests pass.",
		)
	}

	demand := strings.ToLower(spec.Demand)

	if containsAny(
		demand,
		"privacy",
		"camera",
		"cctv",
		"patient",
		"student",
		"personal data",
		"location tracking",
	) {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"Review lawful purpose, authorization, data minimization, retention and deletion, access controls, security logging, and applicable jurisdictional requirements.",
		)
	}

	if containsAny(
		demand,
		"payment",
		"transaction",
		"billing",
		"checkout",
		"wallet",
	) {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"Financial workflows need idempotency, reconciliation, audit evidence, controlled error handling, and provider-specific sandbox testing before live financial operations.",
		)
	}

	if len(evidence.Sources) == 0 {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"No research source records were supplied. Validate assumptions and requirements before implementation.",
		)
	}

	if len(evidence.Findings) == 0 {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"No research findings were supplied. The capability graph is based primarily on the demand and deterministic specification.",
		)
	}

	if spec.ModelAssisted {
		plan.UnresolvedRisks = append(
			plan.UnresolvedRisks,
			"Model-assisted metadata is untrusted descriptive input. Review it against the original demand and deterministic classification before implementation.",
		)
	}

	plan.AcceptanceChecks = append(
		plan.AcceptanceChecks,
		"Run generated unit, integration, and negative tests in an isolated environment.",
		"Verify each selected library's API, version, license, dependencies, maintenance status, and security posture.",
		"Create an implementation task and passing acceptance test for every unresolved capability before production use.",
		"Confirm that unverified candidate coverage is not represented as native or production-verified coverage.",
		"Review source provenance, artifact hashes, assumptions, limitations, and reproducibility evidence.",
		"Require explicit owner review and merge; never execute or deploy generated source automatically.",
	)

	plan.AcceptanceChecks = uniqueStrings(plan.AcceptanceChecks)
	plan.MissingCapabilities = uniqueStrings(plan.MissingCapabilities)
	plan.UnresolvedRisks = uniqueStrings(plan.UnresolvedRisks)
	plan.Edges = uniqueCapabilityEdges(plan.Edges)
	plan.Nodes = uniqueCapabilityNodes(plan.Nodes)

	sort.Slice(plan.Requirements, func(i, j int) bool {
		return plan.Requirements[i].ID < plan.Requirements[j].ID
	})

	sort.Strings(plan.MissingCapabilities)
	sort.Strings(plan.AcceptanceChecks)
	sort.Strings(plan.UnresolvedRisks)

	return plan, nil
}

// inferRequirements builds a deterministic requirement list from the tool
// specification and common domain-specific risk indicators.
func inferRequirements(spec ToolSpec) []inferredRequirement {
	out := make([]inferredRequirement, 0, len(spec.Capabilities)+24)
	seen := make(map[string]bool)

	add := func(
		capability string,
		description string,
		origin string,
		priority string,
		gate string,
		criteria ...string,
	) {
		capability = strings.TrimSpace(capability)
		if capability == "" {
			return
		}

		key := normalizeCapabilityPhrase(capability)
		if key == "" || seen[key] {
			return
		}

		seen[key] = true

		out = append(out, inferredRequirement{
			capability:  capability,
			description: description,
			origin:      origin,
			priority:    priority,
			gate:        gate,
			criteria:    uniqueStrings(criteria),
		})
	}

	// Baseline proposal lifecycle capabilities are required for all inventions.
	add(
		"validate structured input",
		"Validate bounded input and reject malformed requests before processing.",
		"platform_baseline",
		"critical",
		"input_validation",
		"Test empty, malformed, oversized, and boundary-value inputs.",
		"Confirm invalid requests fail without creating partial artifacts.",
	)

	add(
		"produce a deterministic plan",
		"Derive a reviewable plan from deterministic rules without requiring a model.",
		"platform_baseline",
		"required",
		"planning_validation",
		"Repeat the same request in a controlled fixture and confirm stable planning decisions.",
		"Confirm optional model enrichment cannot override protected classification and policy fields.",
	)

	add(
		"record traceable evidence",
		"Preserve research source records and findings so proposal assumptions can be reviewed.",
		"platform_baseline",
		"required",
		"evidence_review",
		"Verify sources retain identity, URL, status, and retrieval metadata where provided.",
		"Distinguish source retrieval from factual verification.",
	)

	add(
		"documented API contract",
		"Define a reviewable API contract and document request, response, and error behavior.",
		"platform_baseline",
		"required",
		"api_contract_review",
		"Validate the generated API schema and exercise representative success and error responses.",
		"Check public-contract compatibility before changing an existing API.",
	)

	add(
		"human approval gate",
		"Keep proposal generation separate from activation, merge, and production deployment.",
		"platform_baseline",
		"critical",
		"human_approval",
		"Verify generated work remains awaiting approval.",
		"Confirm no generation path automatically imports, merges, or deploys the result.",
	)

	add(
		"artifact integrity metadata",
		"Provide artifact hashes or equivalent integrity metadata for proposal review.",
		"platform_baseline",
		"required",
		"artifact_integrity_review",
		"Recompute artifact hashes and detect a changed test artifact.",
		"Document which artifacts are included in the integrity manifest.",
	)

	add(
		"guardian policy screening",
		"Screen untrusted demand, research, and model metadata through the Guardian policy layer.",
		"platform_baseline",
		"critical",
		"guardian_review",
		"Test a blocked demand and confirm no invention is generated.",
		"Test unsafe research metadata and model output against the applicable Guardian checks.",
	)

	for _, capability := range spec.Capabilities {
		add(
			capability,
			"Demand-derived capability: "+capability,
			"tool_specification",
			"required",
			"capability_acceptance_test",
			"Demonstrate the capability with a named automated test: "+capability+".",
			"Document limitations and behavior that remains proposal-only.",
		)
	}

	for _, input := range spec.Inputs {
		add(
			"input contract: "+input,
			"Required or supported input contract: "+input,
			"tool_specification_input",
			"required",
			"input_schema_review",
			"Document valid values, bounds, validation rules, and failure behavior for input: "+input+".",
		)
	}

	for _, output := range spec.Outputs {
		add(
			"output contract: "+output,
			"Expected output contract: "+output,
			"tool_specification_output",
			"required",
			"output_contract_review",
			"Verify output shape, semantic meaning, and error behavior for output: "+output+".",
		)
	}

	for _, safeguard := range spec.Safeguards {
		add(
			"safeguard: "+safeguard,
			"Required safeguard recorded in the specification: "+safeguard,
			"tool_specification_safeguard",
			"critical",
			"safeguard_validation",
			"Define and execute a test or review check demonstrating the safeguard: "+safeguard+".",
		)
	}

	demand := strings.ToLower(spec.Demand)

	if containsAny(demand, "offline", "without internet", "no network") {
		add(
			"offline operation",
			"Core planning and the minimum documented workflow must work without external model or research services.",
			"demand_analysis",
			"required",
			"offline_integration_test",
			"Run the invention flow without an external model endpoint.",
			"Confirm an unavailable online integration produces an explicit status and does not corrupt existing evidence.",
		)
	}

	if containsAny(demand, "queue", "daemon", "scheduler", "background job", "retry", "restart") {
		add(
			"durable queue recovery",
			"Queued work must survive interruption without silently losing its durable record.",
			"demand_analysis",
			"critical",
			"queue_recovery_test",
			"Simulate interruption after claiming a queued item and confirm recoverability.",
			"Repeat processing and confirm idempotent status handling.",
		)
	}

	if containsAny(demand, "file", "document", "storage", "vault", "backup", "archive") {
		add(
			"data integrity and recovery",
			"Stored artifacts require verifiable integrity and a documented recovery path.",
			"demand_analysis",
			"required",
			"data_integrity_test",
			"Corrupt a test artifact and confirm integrity validation detects the change.",
			"Document backup, restore, deletion, and recovery behavior.",
		)
	}

	if containsAny(demand, "payment", "transaction", "billing", "checkout", "wallet") {
		add(
			"transaction idempotency and reconciliation",
			"Financial workflows require duplicate-operation protection and reconciliation before live integration.",
			"demand_analysis",
			"critical",
			"financial_workflow_test",
			"Replay the same simulated transaction and confirm deterministic duplicate handling.",
			"Reconcile recorded test transactions against a simulated provider ledger.",
			"Keep live payment execution disabled until provider and compliance reviews are complete.",
		)
	}

	if containsAny(demand, "refund", "chargeback", "settlement", "ledger") {
		add(
			"financial exception reconciliation",
			"Exceptional financial states require auditable reconciliation and controlled recovery.",
			"demand_analysis",
			"critical",
			"financial_reconciliation_review",
			"Test rejected, delayed, reversed, and duplicated simulated transactions.",
			"Confirm reconciliation evidence can be reviewed without exposing secrets.",
		)
	}

	if containsAny(demand, "camera", "cctv", "image capture", "video capture", "sensor collecting people") {
		add(
			"authorized data collection and retention",
			"Collection features require a documented purpose, access control, minimization, and retention/deletion policy.",
			"demand_analysis",
			"critical",
			"privacy_review",
			"Confirm unauthorized capture or access requests are rejected.",
			"Test retention expiry and deletion with synthetic data.",
			"Document notice, lawful purpose, and access restrictions before deployment.",
		)
	}

	if containsAny(demand, "motor", "mill", "pump", "valve", "actuator", "robot", "machine", "industrial control") {
		add(
			"hardware safety and fail-safe control",
			"Physical control requires verified ratings, independent safeguards, and a safe failure state.",
			"demand_analysis",
			"critical",
			"qualified_hardware_review",
			"Test simulated sensor, power, and network failures before connecting real loads.",
			"Verify emergency stop or equivalent independent shutdown where required by the design.",
			"Keep hazardous actuators disconnected until the reviewed test plan passes.",
		)
	}

	if containsAny(demand, "hardware", "device", "sensor", "microcontroller", "circuit", "electronics", "iot") ||
		spec.NeedsHardwareGuide {
		add(
			"hardware integration and datasheet verification",
			"Hardware integration requires exact component identifiers, manufacturer documentation, interface details, and reviewed ratings.",
			"hardware_classification",
			"critical",
			"hardware_design_review",
			"List exact manufacturer part numbers and official datasheet references.",
			"Verify voltage, current, isolation, protection, and pin assignments against the selected parts.",
			"Use a safe fixture or simulation before connecting the target equipment.",
		)
	}

	if containsAny(demand, "remote", "network", "internet", "multi-user", "api client") {
		add(
			"authenticated remote access",
			"Remote access requires authentication, transport protection, authorization checks, and abuse controls.",
			"demand_analysis",
			"critical",
			"remote_security_test",
			"Confirm unauthenticated protected operations are rejected.",
			"Verify transport security outside loopback development mode.",
			"Test least-privilege authorization and rate-limit behavior.",
		)
	}

	if containsAny(demand, "ai", "model", "neural", "inference", "machine learning") {
		add(
			"model adapter isolation and provenance",
			"Optional model use must be bounded, traceable, and separated from direct code execution.",
			"demand_analysis",
			"required",
			"model_boundary_test",
			"Verify operation degrades safely when the model endpoint is unavailable.",
			"Verify model output cannot execute commands or write arbitrary files directly.",
			"Record relevant model and evidence context for each generated proposal.",
		)

		add(
			"untrusted content and prompt-injection boundary",
			"External text and model output must be treated as untrusted data rather than privileged instructions.",
			"demand_analysis",
			"critical",
			"untrusted_content_test",
			"Test hostile instructions embedded in retrieved content and confirm they cannot bypass platform policy.",
			"Screen generated metadata before using it to create artifacts.",
		)
	}

	if containsAny(demand, "health", "clinic", "medical", "patient", "diagnosis") {
		add(
			"domain expert validation and privacy review",
			"Health-related use requires domain expertise, privacy review, and assessment of applicable regulation.",
			"demand_analysis",
			"critical",
			"domain_expert_review",
			"Require appropriate domain-expert review before real-world use.",
			"Use synthetic data during development until required safeguards are reviewed.",
			"Document intended use and known limitations.",
		)
	}

	if containsAny(demand, "school", "student", "learner", "teacher", "education") {
		add(
			"education data protection",
			"Education-related workflows must account for student information, access boundaries, retention, and age-appropriate protections.",
			"demand_analysis",
			"critical",
			"education_privacy_review",
			"Test role-based access to student and staff records.",
			"Document retention and deletion rules for personal records.",
			"Use synthetic student data in automated tests.",
		)
	}

	if containsAny(demand, "multi-tenant", "multi tenant", "organizations", "multiple businesses", "workspace", "tenant") {
		add(
			"tenant isolation",
			"Multiple organizations or tenants require isolation of records, permissions, and tenant-specific configuration.",
			"demand_analysis",
			"critical",
			"tenant_isolation_test",
			"Attempt cross-tenant reads and writes using two isolated test tenants.",
			"Confirm tenant identity is derived from a trusted server-side authorization context.",
			"Verify tenant scoping applies consistently to background jobs and administrative endpoints.",
		)
	}

	if containsAny(demand, "webhook", "callback", "event delivery") {
		add(
			"webhook authenticity and replay protection",
			"Incoming callbacks require authenticity checks, bounded payloads, and a documented replay/idempotency strategy.",
			"demand_analysis",
			"critical",
			"webhook_security_test",
			"Reject invalid signatures or authentication data.",
			"Test duplicate event delivery and replay behavior.",
			"Bound payload size and document retry policy.",
		)
	}

	if containsAny(demand, "report", "analytics", "dashboard", "metrics") {
		add(
			"data interpretation and metric provenance",
			"Reporting outputs should identify the data scope, calculation method, freshness, and known limitations.",
			"demand_analysis",
			"required",
			"reporting_validation",
			"Test calculations against fixed reference fixtures.",
			"Expose the relevant time range and missing-data behavior.",
			"Do not represent sample or stale data as live verified data.",
		)
	}

	if spec.Country != "" || spec.Language != "" {
		add(
			"country and language localization",
			"Country-aware proposals require resolved locale metadata and explicit checks for which adaptations are verified versus generic.",
			"worldwide_profile",
			"required",
			"worldwide_profile_review",
			"Confirm the country and language profile is valid.",
			"Identify generic fallback profile data and avoid presenting it as country-verified.",
			"Review localized wording, prices, standards, and legal references independently.",
		)
	}

	sort.Slice(out, func(i, j int) bool {
		return normalizeCapabilityPhrase(out[i].capability) <
			normalizeCapabilityPhrase(out[j].capability)
	})

	return out
}

// findNativeCapability deliberately uses exact normalized aliases instead of
// broad substring matching, reducing false positives in capability coverage.
func findNativeCapability(
	requirement string,
	catalogue map[string]nativeCapability,
) (nativeCapability, bool) {
	normalized := normalizeCapabilityPhrase(requirement)
	if normalized == "" {
		return nativeCapability{}, false
	}

	for _, item := range nativeCapabilityCatalogue {
		capability, exists := catalogue[item.id]
		if !exists {
			continue
		}

		for _, term := range capability.terms {
			if normalizeCapabilityPhrase(term) == normalized {
				return capability, true
			}
		}
	}

	return nativeCapability{}, false
}

// loadCapabilityLibraries reads only bounded regular metadata files from
// immediate library directories. It skips staging entries and rejects
// Guardian-blocked content before exposing metadata to the ranking process.
func loadCapabilityLibraries(root string) ([]libraryMetadata, error) {
	info, err := os.Lstat(root)
	if os.IsNotExist(err) {
		return []libraryMetadata{}, nil
	}
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("library catalogue root must be a regular directory")
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}

	out := make([]libraryMetadata, 0, len(entries))

	for _, entry := range entries {
		if len(out) >= maxCapabilityLibraries {
			break
		}

		if !entry.IsDir() ||
			entry.Type()&os.ModeSymlink != 0 ||
			strings.HasPrefix(entry.Name(), ".staging-") {
			continue
		}

		if !validCapabilityLibraryName(entry.Name()) {
			continue
		}

		libraryDir := filepath.Join(root, entry.Name())
		dirInfo, err := os.Lstat(libraryDir)
		if err != nil {
			continue
		}
		if !dirInfo.IsDir() || dirInfo.Mode()&os.ModeSymlink != 0 {
			continue
		}

		path := filepath.Join(libraryDir, "library.json")
		metaInfo, err := os.Lstat(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, err
		}
		if !metaInfo.Mode().IsRegular() ||
			metaInfo.Mode()&os.ModeSymlink != 0 ||
			metaInfo.Size() > maxCapabilityLibraryFile {
			continue
		}

		raw, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}

		var meta libraryMetadata
		if err := json.Unmarshal(raw, &meta); err != nil {
			// One malformed legacy catalogue entry should not hide the
			// remaining libraries.
			continue
		}

		if meta.Name == "" {
			meta.Name = entry.Name()
		}

		// Prevent metadata names from redirecting graph references to paths
		// outside the library directory or creating ambiguous candidate IDs.
		if meta.Name != entry.Name() ||
			!validCapabilityLibraryName(meta.Name) ||
			len(meta.Capabilities) > maxCapabilityLibraryItems ||
			len(meta.Dependencies) > maxCapabilityLibraryItems {
			continue
		}

		metadataText := strings.Join(
			append(
				append([]string{
					meta.Name,
					meta.Category,
					meta.Industry,
				}, meta.Capabilities...),
				meta.Dependencies...,
			),
			" ",
		)

		decision := worldguardian.CheckText(metadataText)
		if !decision.Allowed {
			return nil, fmt.Errorf(
				"%w: reusable library metadata %q was rejected by Guardian (%s)",
				ErrBlocked,
				meta.Name,
				decision.Code,
			)
		}

		if err := validateLibraryMetadataFields(meta); err != nil {
			continue
		}

		meta.Capabilities = uniqueStrings(meta.Capabilities)
		meta.Dependencies = uniqueStrings(meta.Dependencies)

		out = append(out, meta)
	}

	sort.Slice(out, func(i, j int) bool {
		return out[i].Name < out[j].Name
	})

	return out, nil
}

func validateLibraryMetadataFields(meta libraryMetadata) error {
	if len(meta.Name) > 100 ||
		len(meta.Category) > 100 ||
		len(meta.Industry) > 100 {
		return errors.New("library metadata field exceeded its configured limit")
	}

	for _, value := range meta.Capabilities {
		if len(value) > maxCapabilityTextBytes {
			return errors.New("library capability exceeded its configured limit")
		}
	}

	for _, value := range meta.Dependencies {
		if len(value) > maxCapabilityTextBytes {
			return errors.New("library dependency exceeded its configured limit")
		}
	}

	return nil
}

func validCapabilityLibraryName(name string) bool {
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

// rankReusableLibraries computes deterministic metadata matches. Scores are
// ranking aids, not quality ratings or evidence of production readiness.
func rankReusableLibraries(
	spec ToolSpec,
	libraries []libraryMetadata,
	limit int,
) []ReusableLibraryCandidate {
	out := make([]ReusableLibraryCandidate, 0, len(libraries))

	for _, lib := range libraries {
		candidate := scoreReusableLibrary(spec, lib)
		if candidate.Score <= 0 {
			continue
		}

		out = append(out, candidate)
	}

	sort.Slice(out, func(i, j int) bool {
		if out[i].Score == out[j].Score {
			return out[i].Name < out[j].Name
		}
		return out[i].Score > out[j].Score
	})

	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}

	return out
}

func scoreReusableLibrary(
	spec ToolSpec,
	lib libraryMetadata,
) ReusableLibraryCandidate {
	score := 0
	reasons := []string{}
	matched := []string{}

	if lib.Industry != "" &&
		lib.Industry == spec.Industry &&
		spec.Industry != "" &&
		spec.Industry != "general" {
		score += 4
		reasons = append(reasons, "industry matches the invention specification")
	}

	if lib.Category != "" &&
		lib.Category == spec.Category &&
		spec.Category != "" {
		score += 2
		reasons = append(reasons, "category matches the invention specification")
	}

	for _, required := range spec.Capabilities {
		bestScore := 0
		for _, available := range lib.Capabilities {
			s := capabilityLexicalOverlap(required, available)
			if s > bestScore {
				bestScore = s
			}
		}

		if bestScore >= 2 {
			score += bestScore
			matched = append(matched, required)
		}
	}

	if len(matched) > 0 {
		reasons = append(
			reasons,
			fmt.Sprintf("%d capability descriptions overlap", len(matched)),
		)
	}

	if len(lib.Dependencies) > 0 {
		reasons = append(
			reasons,
			"declares dependencies that must be reviewed before reuse",
		)
	}

	reason := "Metadata overlap only; inspect the actual code, API, dependency provenance, license, tests, and security before adopting this library."
	if len(reasons) > 0 {
		reason += " Matching signals: " + strings.Join(reasons, "; ") + "."
	}

	return ReusableLibraryCandidate{
		Name:                 lib.Name,
		Industry:             lib.Industry,
		Category:             lib.Category,
		Score:                score,
		Capabilities:         append([]string{}, lib.Capabilities...),
		Dependencies:         append([]string{}, lib.Dependencies...),
		MatchedCapabilities:  uniqueStrings(matched),
		MatchReasons:         uniqueStrings(reasons),
		Reason:               reason,
		Status:               "candidate_unverified",
		SourcePath:           filepath.ToSlash(filepath.Join("core-one", "libraries", "created", lib.Name)),
		VerificationRequired: true,
	}
}

func bestLibraryForRequirement(
	requirement string,
	candidates []ReusableLibraryCandidate,
) (ReusableLibraryCandidate, int, bool) {
	var best ReusableLibraryCandidate
	bestScore := 0

	for _, candidate := range candidates {
		for _, capability := range candidate.Capabilities {
			score := capabilityLexicalOverlap(requirement, capability)
			if score > bestScore ||
				(score == bestScore &&
					score > 0 &&
					(candidate.Name < best.Name || best.Name == "")) {
				best = candidate
				bestScore = score
			}
		}
	}

	return best, bestScore, bestScore >= 2
}

// capabilityLexicalOverlap returns a deterministic ranking score. Exact and
// near-exact names receive stronger scores; incidental one-word overlap does
// not qualify as a reusable-library match.
func capabilityLexicalOverlap(a, b string) int {
	leftPhrase := normalizeCapabilityPhrase(a)
	rightPhrase := normalizeCapabilityPhrase(b)

	if leftPhrase == "" || rightPhrase == "" {
		return 0
	}

	if leftPhrase == rightPhrase {
		return 100
	}

	left := normalizedCapabilityTokens(a)
	right := normalizedCapabilityTokens(b)

	if len(left) == 0 || len(right) == 0 {
		return 0
	}

	intersection := 0
	for token := range left {
		if right[token] {
			intersection++
		}
	}

	if intersection == 0 {
		return 0
	}

	// A common descriptive phrase is more useful than one shared generic word.
	smaller := len(left)
	larger := len(right)
	if len(right) < smaller {
		smaller = len(right)
	}
	if len(right) > larger {
		larger = len(right)
	}

	score := intersection * 10
	if intersection == smaller {
		score += 5
	}
	if intersection == larger {
		score += 5
	}

	return score
}

func normalizedCapabilityTokens(value string) map[string]bool {
	tokens := strings.Fields(normalizeCapabilityPhrase(value))
	out := make(map[string]bool, len(tokens))

	for _, token := range tokens {
		switch token {
		case "the", "and", "for", "from", "with", "without",
			"into", "that", "this", "must", "shall", "before",
			"after", "only", "using", "use", "support", "supports",
			"required", "requires", "provide", "provides", "create",
			"creates", "produce", "produces", "record", "records",
			"system", "tool", "tools", "general", "feature",
			"features", "functionality", "capability", "capabilities":
			continue
		case "validates", "validation", "validated":
			token = "validate"
		case "inputs":
			token = "input"
		case "plans", "planning", "planned":
			token = "plan"
		case "tests", "testing", "tested":
			token = "test"
		case "documents", "documented", "documentation":
			token = "document"
		case "authenticated", "authentication":
			token = "auth"
		case "authorisation", "authorization", "authorized", "authorised":
			token = "authorize"
		case "traceable", "tracing":
			token = "trace"
		case "libraries":
			token = "library"
		}

		if len(token) > 2 {
			out[token] = true
		}
	}

	return out
}

func normalizeCapabilityPhrase(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))

	var b strings.Builder
	space := false

	for _, r := range value {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
			space = false
		case r >= '0' && r <= '9':
			b.WriteRune(r)
			space = false
		default:
			if b.Len() > 0 && !space {
				b.WriteByte(' ')
				space = true
			}
		}
	}

	return strings.TrimSpace(b.String())
}

func validateCapabilityEvidence(evidence ResearchEvidence) error {
	if len(evidence.Sources) > maxCapabilityEvidenceItems {
		return errors.New(
			"capability planner received too many research source records",
		)
	}

	if len(evidence.Findings) > maxCapabilityFindingItems {
		return errors.New(
			"capability planner received too many research findings",
		)
	}

	for _, finding := range evidence.Findings {
		if len(finding) > maxCapabilityTextBytes {
			return errors.New(
				"capability planner received an oversized research finding",
			)
		}

		decision := worldguardian.CheckText(finding)
		if !decision.Allowed {
			return fmt.Errorf(
				"%w: research finding rejected by Guardian",
				ErrBlocked,
			)
		}
	}

	for _, source := range evidence.Sources {
		if len(source.Name) > 200 ||
			len(source.Title) > 500 ||
			len(source.URL) > 2048 ||
			len(source.Snippet) > maxCapabilityTextBytes {
			return errors.New(
				"capability planner received an oversized research source field",
			)
		}

		sourceText := strings.Join([]string{
			source.Name,
			source.Title,
			source.URL,
			source.Snippet,
		}, " ")

		decision := worldguardian.CheckText(sourceText)
		if !decision.Allowed {
			return fmt.Errorf(
				"%w: research source metadata rejected by Guardian",
				ErrBlocked,
			)
		}
	}

	return nil
}

func sortedCapabilitySources(sources []ResearchSource) []ResearchSource {
	out := append([]ResearchSource{}, sources...)

	sort.Slice(out, func(i, j int) bool {
		if out[i].URL == out[j].URL {
			if out[i].Title == out[j].Title {
				return out[i].Name < out[j].Name
			}
			return out[i].Title < out[j].Title
		}
		return out[i].URL < out[j].URL
	})

	return out
}

func capabilitySourceID(source ResearchSource) string {
	value := strings.TrimSpace(source.URL) + "\n" +
		strings.TrimSpace(source.Title) + "\n" +
		strings.TrimSpace(source.Name)

	if strings.Trim(value, "\n ") == "" {
		return ""
	}

	return "source:" + sha256String(value)[:16]
}

func capabilitySourceLabel(source ResearchSource) string {
	label := strings.TrimSpace(source.Title)
	if label == "" {
		label = strings.TrimSpace(source.Name)
	}
	if label == "" {
		label = "Unlabelled research source"
	}

	return capabilityOneLine(label, 160)
}

func findRelevantCapabilityEvidence(
	req inferredRequirement,
	evidence ResearchEvidence,
	sourceNodes map[string]ResearchSource,
) []string {
	requirementTokens := normalizedCapabilityTokens(
		req.capability + " " + req.description,
	)
	if len(requirementTokens) == 0 {
		return []string{}
	}

	type matchedSource struct {
		id    string
		score int
	}
	matches := make([]matchedSource, 0)

	for sourceID, source := range sourceNodes {
		if source.Status != "retrieved" {
			continue
		}

		sourceTokens := normalizedCapabilityTokens(
			source.Name + " " + source.Title + " " + source.Snippet,
		)

		score := 0
		for token := range requirementTokens {
			if sourceTokens[token] {
				score++
			}
		}

		if score >= 2 {
			matches = append(matches, matchedSource{
				id:    sourceID,
				score: score,
			})
		}
	}

	sort.Slice(matches, func(i, j int) bool {
		if matches[i].score == matches[j].score {
			return matches[i].id < matches[j].id
		}
		return matches[i].score > matches[j].score
	})

	const maxEvidenceRefsPerRequirement = 5
	if len(matches) > maxEvidenceRefsPerRequirement {
		matches = matches[:maxEvidenceRefsPerRequirement]
	}

	out := make([]string, 0, len(matches))
	for _, match := range matches {
		out = append(out, match.id)
	}

	return out
}

func capabilityMatchConfidence(score int) string {
	switch {
	case score >= 100:
		return "exact_phrase"
	case score >= 25:
		return "strong_lexical_overlap"
	default:
		return "partial_lexical_overlap"
	}
}

func uniqueCapabilityEdges(edges []CapabilityEdge) []CapabilityEdge {
	seen := make(map[string]bool, len(edges))
	out := make([]CapabilityEdge, 0, len(edges))

	for _, edge := range edges {
		if edge.From == "" || edge.To == "" || edge.Rel == "" {
			continue
		}

		key := edge.From + "\x00" + edge.To + "\x00" + edge.Rel
		if seen[key] {
			continue
		}

		seen[key] = true
		out = append(out, edge)
	}

	sort.Slice(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.From != b.From {
			return a.From < b.From
		}
		if a.To != b.To {
			return a.To < b.To
		}
		return a.Rel < b.Rel
	})

	return out
}

func uniqueCapabilityNodes(nodes []CapabilityNode) []CapabilityNode {
	seen := make(map[string]bool, len(nodes))
	out := make([]CapabilityNode, 0, len(nodes))

	for _, node := range nodes {
		if node.ID == "" || seen[node.ID] {
			continue
		}

		seen[node.ID] = true
		out = append(out, node)
	}

	return out
}

func uniqueStrings(values []string) []string {
	seen := make(map[string]bool, len(values))
	out := make([]string, 0, len(values))

	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}

		seen[value] = true
		out = append(out, value)
	}

	return out
}

func capabilityOneLine(value string, maxLength int) string {
	value = strings.Join(strings.Fields(value), " ")
	if maxLength <= 0 {
		return ""
	}

	runes := []rune(value)
	if len(runes) > maxLength {
		return string(runes[:maxLength])
	}

	return value
}
