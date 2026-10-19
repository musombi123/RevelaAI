package genesis

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	defaultExpansionCoreFileThreshold = 5000
	minExpansionCoreFileThreshold     = 11
	maxExpansionCoreFileThreshold     = 1000000
	maxExpansionResourceNameLength    = 80
	maxExpansionIndustryNameLength    = 64
)

var expansionIgnoredDirectories = map[string]bool{
	".git":         true,
	"node_modules": true,
	"vendor":       true,
	"dist":         true,
	"build":        true,
	"target":       true,
	".next":        true,
	".venv":        true,
	"venv":         true,
	"coverage":     true,
	".cache":       true,
}

func makeExpansionPlan(spec ToolSpec, coreRoot string) map[string]any {
	createdAt := time.Now().UTC()
	resourceName, validName := validateExpansionResourceName(spec.Name)

	threshold := expansionCoreFileThreshold()
	fileCount, scanComplete, scanErr := countExpansionCoreFiles(
		coreRoot,
		threshold,
	)

	useGen2 := scanErr == nil && fileCount >= threshold

	target := ""
	targetStatus := "blocked_invalid_resource_name"

	if validName {
		target = filepath.ToSlash(
			filepath.Join("core-one", "expand", "plans", resourceName+".json"),
		)
		targetStatus = "awaiting_review"
		if useGen2 {
			target = filepath.ToSlash(
				filepath.Join("core-one", "gen2", "staging", resourceName+".json"),
			)
			targetStatus = "gen2_staging"
		}
	}

	scanStatus := "complete"
	if scanErr != nil {
		scanStatus = "error"
	} else if !scanComplete {
		scanStatus = "threshold_reached"
	}

	scanReason := "The core file threshold was not reached; the standard expansion planning directory is selected."
	if useGen2 {
		scanReason = "The configured core file threshold was reached; the Gen2 staging target is selected for review."
	}
	if scanErr != nil {
		scanReason = "Core size inspection failed; the standard expansion target is retained as the conservative fallback."
	}
	if !validName {
		scanReason += " The invention name is invalid, so no proposal target has been assigned."
	}

	worldwideContext := map[string]any{
		"country":                  spec.Country,
		"country_name":             spec.CountryName,
		"language":                 spec.Language,
		"currency":                 spec.Currency,
		"supplier_directory":       append([]string(nil), spec.SupplierDirectory...),
		"nominal_ac_voltage_v":     spec.NominalACVoltage,
		"frequency_hz":             spec.FrequencyHz,
		"local_adaptations":        append([]string(nil), spec.LocalAdaptations...),
		"legal_framework_awareness": append([]string(nil), spec.LegalFrameworks...),
		"bom":                      copyExpansionMap(spec.BOM),
		"live_pricing_verified":    false,
		"compliance_verified":      false,
	}

	validationGates := []map[string]any{
		{
			"id":          "guardian_review",
			"required":    true,
			"description": "Screen the demand, generated specification, evidence, and proposed changes against Guardian policy.",
		},
		{
			"id":          "requirements_review",
			"required":    true,
			"description": "Verify the intended users, acceptance criteria, inputs, outputs, constraints, and failure cases.",
		},
		{
			"id":          "security_privacy_review",
			"required":    true,
			"description": "Review authentication, authorization, secrets handling, data minimization, privacy, and trust boundaries.",
		},
		{
			"id":          "test_gate",
			"required":    true,
			"description": "Run relevant unit, integration, regression, and negative tests before accepting generated artifacts.",
		},
		{
			"id":          "dependency_review",
			"required":    true,
			"description": "Review dependency provenance, licensing, known vulnerabilities, version constraints, and supply-chain risk.",
		},
		{
			"id":          "api_compatibility",
			"required":    true,
			"description": "Validate API schemas, SDK contracts, error behavior, version compatibility, and migration needs where applicable.",
		},
		{
			"id":          "documentation_evidence",
			"required":    true,
			"description": "Check documentation, artifact provenance, generated hashes, limitations, and reproducibility evidence.",
		},
		{
			"id":          "human_approval",
			"required":    true,
			"description": "Obtain explicit human approval before merging, importing, deploying, or enabling generated changes.",
		},
	}

	actions := []string{
		"Convert the invention into a versioned, reviewable model-family proposal.",
		"Identify reusable libraries and define ownership, interfaces, and dependency boundaries.",
		"Prepare versioned API specifications and SDK changes where applicable.",
		"Add acceptance tests for intended behavior, invalid inputs, error handling, and regressions.",
		"Document configuration, installation, rollback, migration, and operational requirements.",
		"Record source provenance, artifact hashes, dependency information, and validation evidence.",
		"Review security, privacy, accessibility, reliability, and failure recovery.",
		"Prepare a staged rollout plan with monitoring, rollback criteria, and an explicit activation gate.",
		"Assess country-specific requirements when a worldwide profile is present.",
		"Keep generated artifacts isolated from active production paths until approval is complete.",
	}

	return map[string]any{
		"schema_version": "genesis.expansion-plan.v2",
		"id":             newID("expand"),
		"created_at":     createdAt,
		"updated_at":     createdAt,

		"demand":        spec.Demand,
		"invention":     resourceName,
		"invention_name_valid": validName,
		"title":         spec.Title,
		"industry":      spec.Industry,
		"category":      spec.Category,
		"purpose":       spec.Purpose,
		"capabilities":  append([]string(nil), spec.Capabilities...),
		"inputs":        append([]string(nil), spec.Inputs...),
		"outputs":       append([]string(nil), spec.Outputs...),
		"safeguards":    append([]string(nil), spec.Safeguards...),
		"model_assisted": spec.ModelAssisted,
		"model_note":     spec.ModelNote,

		"proposal_target":        target,
		"proposal_target_status": targetStatus,
		"target_selection_reason": scanReason,

		"core_size_assessment": map[string]any{
			"status":           scanStatus,
			"files_counted":    fileCount,
			"threshold":        threshold,
			"threshold_reached": fileCount >= threshold && scanErr == nil,
			"scan_complete":    scanComplete,
			"scan_error":       expansionErrorText(scanErr),
			"gen2_selected":    useGen2,
		},

		"verbs": []string{
			"create",
			"innovate",
			"transform",
			"change",
			"emerge",
			"move",
			"adopt",
			"evolve",
			"forge",
			"protect",
			"validate",
			"measure",
			"document",
			"review",
			"version",
			"integrate",
			"monitor",
			"recover",
			"improve",
		},

		"actions": actions,

		"expansion_stages": []map[string]any{
			{
				"stage":  1,
				"name":   "discovery",
				"status": "planned",
				"goal":   "Define the problem, evidence, intended users, constraints, and measurable acceptance criteria.",
			},
			{
				"stage":  2,
				"name":   "design",
				"status": "planned",
				"goal":   "Define architecture, interfaces, data handling, dependencies, safeguards, and failure modes.",
			},
			{
				"stage":  3,
				"name":   "implementation_proposal",
				"status": "planned",
				"goal":   "Generate an isolated and reviewable implementation proposal with supporting artifacts.",
			},
			{
				"stage":  4,
				"name":   "verification",
				"status": "blocked_until_implemented",
				"goal":   "Run the required automated checks and collect evidence; do not treat an unrun test as passing.",
			},
			{
				"stage":  5,
				"name":   "human_review",
				"status": "awaiting_review",
				"goal":   "Review correctness, safety, maintainability, compatibility, and operational impact.",
			},
			{
				"stage":  6,
				"name":   "staged_adoption",
				"status": "blocked_until_approved",
				"goal":   "Plan controlled adoption, observability, rollback, and explicit activation approval.",
			},
		},

		"required_gates": validationGates,

		"quality_requirements": map[string]any{
			"tests_required":                 true,
			"regression_tests_required":      true,
			"security_review_required":       true,
			"dependency_review_required":     true,
			"documentation_required":         true,
			"artifact_provenance_required":   true,
			"rollback_plan_required":         true,
			"human_review_required":          true,
			"unrun_tests_may_be_marked_pass": false,
		},

		"worldwide_context": worldwideContext,

		"expansion_policy": map[string]any{
			"auto_import":                 false,
			"auto_execute":                false,
			"auto_merge":                  false,
			"auto_deploy":                 false,
			"auto_enable_production":      false,
			"generated_code_execution":    "prohibited_during_planning",
			"existing_core_modification":  "explicit_review_required",
			"secrets_in_artifacts":        "prohibited",
			"external_evidence_is_trusted": false,
			"legal_compliance_is_assumed": false,
			"hardware_safety_is_assumed":  false,
			"pricing_is_live_verified":    false,
		},

		"observability": map[string]any{
			"record_lifecycle_events": true,
			"retain_validation_results": true,
			"record_artifact_hashes": true,
			"record_failure_reasons": true,
			"monitor_adoption": true,
			"rollback_on_approved_failure_criteria": true,
		},

		"status": "await_merge",
		"reason": "Genesis can prepare a structured expansion proposal, but the proposal does not authorize its own import, execution, merge, deployment, or production activation.",
	}
}

func shouldUseGen2(coreRoot string) bool {
	threshold := expansionCoreFileThreshold()
	count, _, err := countExpansionCoreFiles(coreRoot, threshold)
	return err == nil && count >= threshold
}

func expansionCoreFileThreshold() int {
	threshold := defaultExpansionCoreFileThreshold

	raw := strings.TrimSpace(os.Getenv("GENESIS_MAX_CORE_FILES"))
	if raw == "" {
		return threshold
	}

	n, err := strconv.Atoi(raw)
	if err != nil ||
		n < minExpansionCoreFileThreshold ||
		n > maxExpansionCoreFileThreshold {
		return threshold
	}

	return n
}

// countExpansionCoreFiles counts ordinary files without following symlinks.
// It stops once the threshold is reached, because additional counting is not
// needed to decide between the standard planning and Gen2 staging targets.
func countExpansionCoreFiles(
	coreRoot string,
	threshold int,
) (int, bool, error) {
	root := strings.TrimSpace(coreRoot)
	if root == "" {
		return 0, false, fmt.Errorf("core root is required")
	}

	if threshold < minExpansionCoreFileThreshold {
		threshold = defaultExpansionCoreFileThreshold
	}

	absRoot, err := filepath.Abs(root)
	if err != nil {
		return 0, false, fmt.Errorf("resolve core root: %w", err)
	}

	info, err := os.Stat(absRoot)
	if err != nil {
		return 0, false, fmt.Errorf("inspect core root: %w", err)
	}

	if !info.IsDir() {
		return 0, false, fmt.Errorf("core root is not a directory")
	}

	count := 0
	complete := true

	err = filepath.WalkDir(
		absRoot,
		func(path string, entry os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}

			if entry.IsDir() {
				if expansionIgnoredDirectories[entry.Name()] ||
					strings.HasPrefix(entry.Name(), ".staging-") {
					return filepath.SkipDir
				}

				return nil
			}

			// WalkDir does not recurse through symlinked directories, and
			// symlinked files are not counted as ordinary core files.
			if entry.Type()&os.ModeSymlink != 0 {
				return nil
			}

			info, err := entry.Info()
			if err != nil {
				return err
			}

			if !info.Mode().IsRegular() {
				return nil
			}

			count++
			if count >= threshold {
				complete = false
				return filepath.SkipAll
			}

			return nil
		},
	)

	if err != nil && err != filepath.SkipAll {
		return count, false, err
	}

	return count, complete, nil
}

func (e *Engine) recordIndustry(spec ToolSpec) error {
	if e == nil {
		return fmt.Errorf("genesis: engine is required")
	}

	if strings.TrimSpace(e.CoreRoot) == "" {
		return fmt.Errorf("genesis: core root is not configured")
	}

	industry, err := normalizeExpansionIndustry(spec.Industry)
	if err != nil {
		return err
	}

	coreRoot, err := filepath.Abs(e.CoreRoot)
	if err != nil {
		return fmt.Errorf("resolve core root: %w", err)
	}

	realCoreRoot, err := filepath.EvalSymlinks(coreRoot)
	if err != nil {
		return fmt.Errorf("resolve core root: %w", err)
	}

	industriesRoot := filepath.Join(realCoreRoot, "industries")

	if err := os.MkdirAll(industriesRoot, 0o700); err != nil {
		return fmt.Errorf("create industry directory: %w", err)
	}

	realIndustriesRoot, err := filepath.EvalSymlinks(industriesRoot)
	if err != nil {
		return fmt.Errorf("resolve industry directory: %w", err)
	}

	rootRelative, err := filepath.Rel(realCoreRoot, realIndustriesRoot)
	if err != nil {
		return fmt.Errorf("validate industry directory: %w", err)
	}

	if rootRelative == ".." ||
		strings.HasPrefix(rootRelative, ".."+string(filepath.Separator)) ||
		filepath.IsAbs(rootRelative) {
		return fmt.Errorf("genesis: industry directory escapes the core root")
	}

	industryDir := filepath.Join(realIndustriesRoot, industry)

	if err := os.MkdirAll(industryDir, 0o700); err != nil {
		return fmt.Errorf("create industry category: %w", err)
	}

	realIndustryDir, err := filepath.EvalSymlinks(industryDir)
	if err != nil {
		return fmt.Errorf("resolve industry category: %w", err)
	}

	industryRelative, err := filepath.Rel(realIndustriesRoot, realIndustryDir)
	if err != nil {
		return fmt.Errorf("validate industry category: %w", err)
	}

	if industryRelative == ".." ||
		strings.HasPrefix(industryRelative, ".."+string(filepath.Separator)) ||
		filepath.IsAbs(industryRelative) {
		return fmt.Errorf("genesis: industry category escapes the industries directory")
	}

	path := filepath.Join(realIndustryDir, "README.md")

	// Never replace the existing industry documentation. It may contain
	// reviewed references, policies, acceptance criteria, or human edits.
	file, err := os.OpenFile(
		path,
		os.O_WRONLY|os.O_CREATE|os.O_EXCL,
		0o600,
	)
	if err != nil {
		if os.IsExist(err) {
			return nil
		}

		return fmt.Errorf("create industry starter: %w", err)
	}

	body := fmt.Sprintf(
		"# %s invention domain\n\n"+
			"This directory was proposed by Revela Genesis for invention %s.\n\n"+
			"The industry classification is a taxonomy hint only. It does not establish verified market demand, regulatory approval, legal compliance, safety, certification, or suitability for deployment.\n\n"+
			"Before accepting changes, add reviewed industry standards, authoritative sources, a threat model, data-handling requirements, measurable acceptance criteria, and relevant regression tests. Record source dates and responsible reviewers. Do not store credentials, access tokens, private customer data, or other secrets in this document.\n\n"+
			"## Review status\n\n"+
			"- Initial classification: %s\n"+
			"- Initial documentation status: review_required\n"+
			"- Production approval: false\n"+
			"- Automatic import or deployment: prohibited\n",
		industry,
		expansionOneLine(spec.Name, maxExpansionResourceNameLength),
		industry,
	)

	_, writeErr := file.WriteString(body)
	if writeErr == nil {
		writeErr = file.Sync()
	}

	closeErr := file.Close()

	if writeErr != nil {
		_ = os.Remove(path)
		return fmt.Errorf("write industry starter: %w", writeErr)
	}

	if closeErr != nil {
		_ = os.Remove(path)
		return fmt.Errorf("close industry starter: %w", closeErr)
	}

	return nil
}

func validateExpansionResourceName(value string) (string, bool) {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > maxExpansionResourceNameLength {
		return "", false
	}

	if value == "." ||
		value == ".." ||
		filepath.Base(value) != value ||
		strings.ContainsAny(value, `/\`) {
		return "", false
	}

	for _, r := range value {
		if (r >= 'a' && r <= 'z') ||
			(r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') ||
			r == '_' ||
			r == '-' {
			continue
		}

		return "", false
	}

	return value, true
}

func normalizeExpansionIndustry(value string) (string, error) {
	value = strings.TrimSpace(strings.ToLower(value))
	if value == "" {
		value = "general"
	}

	if len(value) > maxExpansionIndustryNameLength*2 {
		return "", fmt.Errorf("genesis: industry label is too long")
	}

	if strings.ContainsAny(value, `/\`) ||
		value == "." ||
		value == ".." {
		return "", fmt.Errorf("genesis: invalid industry path")
	}

	var out strings.Builder
	lastSeparator := false

	for _, r := range value {
		switch {
		case r >= 'a' && r <= 'z':
			out.WriteRune(r)
			lastSeparator = false

		case r >= '0' && r <= '9':
			out.WriteRune(r)
			lastSeparator = false

		case r == '-' || r == '_' || r == ' ':
			if out.Len() > 0 && !lastSeparator {
				out.WriteByte('_')
				lastSeparator = true
			}

		default:
			return "", fmt.Errorf(
				"genesis: industry contains unsupported characters",
			)
		}
	}

	industry := strings.Trim(out.String(), "_-")
	if industry == "" || len(industry) > maxExpansionIndustryNameLength {
		return "", fmt.Errorf("genesis: invalid industry category")
	}

	return industry, nil
}

func copyExpansionMap(source map[string]any) map[string]any {
	if len(source) == 0 {
		return map[string]any{}
	}

	out := make(map[string]any, len(source))
	for key, value := range source {
		out[key] = value
	}

	return out
}

func expansionErrorText(err error) string {
	if err == nil {
		return ""
	}

	return expansionOneLine(err.Error(), 240)
}

func expansionOneLine(value string, maxLength int) string {
	value = strings.Join(strings.Fields(value), " ")

	if maxLength <= 0 {
		return ""
	}

	runes := []rune(value)
	if len(runes) > maxLength {
		value = string(runes[:maxLength])
	}

	return value
}
