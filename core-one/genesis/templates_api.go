package genesis

import (
	"encoding/json"
	"fmt"
	"strings"
)

func generatedOpenAPI(spec ToolSpec) string {
	return fmt.Sprintf(`openapi: 3.1.0
info:
  title: %s API proposal
  version: 0.1.0
  description: "Staged proposal only. This endpoint is not served until human review, merge, and explicit host registration."
paths:
  /v1/%s/plan:
    post:
      summary: Validate input and return a non-executing plan
      operationId: create%sPlan
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [action]
              properties:
                action: {type: string, minLength: 1, maxLength: 160}
                inputs: {type: object, additionalProperties: {type: string}}
                consent: {type: boolean, default: false}
      responses:
        '200':
          description: Plan created; no external side effects performed
        '400': {description: Invalid request}
        '401': {description: Authentication required}
        '403': {description: Consent or authorization missing}
  /v1/%s/capability_plan:
    get:
      summary: Read the generated capability graph and requirement plan
      operationId: get%sCapabilityPlan
      responses:
        '200': {description: Staged capability plan; gaps and library matches require review}
        '404': {description: Capability plan not found}
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
`, yamlSafe(spec.Title), spec.Name, operationName(spec.Name), spec.Name, operationName(spec.Name))
}

func operationName(s string) string {
	p := strings.Split(s, "_")
	for i := range p {
		if p[i] != "" {
			p[i] = strings.ToUpper(p[i][:1]) + p[i][1:]
		}
	}
	return strings.Join(p, "")
}

func yamlSafe(s string) string { b, _ := json.Marshal(s); return string(b) }

func markdownList(items []string) string {
	var b strings.Builder
	for _, item := range items {
		fmt.Fprintf(&b, "- %s\n", item)
	}
	return strings.TrimSpace(b.String())
}

func generatedMergeChecklist(spec ToolSpec) string {
	return fmt.Sprintf(`# AWAIT MERGE — %s

Genesis has generated a proposal. It intentionally does not merge, install, execute, or activate the invention.

## Required before merge

- [ ] Review demand, research provenance, and evidence.json; verify external claims independently.
- [ ] Review capability_plan.json and assign an owner/test to every unresolved capability.
- [ ] Review every generated source file and the reusable library driver.
- [ ] Run go test ./... from core-one/.
- [ ] Run static analysis, dependency/license checks, secret scanning, and security tests.
- [ ] Verify all external endpoints, authentication, authorization, rate limits, and data-retention rules.
- [ ] If hardware is involved, validate the exact BOM/schematic/datasheets and obtain qualified review.
- [ ] Review privacy, consent, accessibility, rollback, observability, and disaster-recovery plans.
- [ ] Approve a deployment target and register the proposed OpenAPI path explicitly.
- [ ] Merge only after owner approval.

**Generated category:** %s  
**Industry:** %s  
**Activation:** prohibited until the checklist is approved.
`, spec.Title, spec.Category, spec.Industry)
}

func generatedModel(spec ToolSpec) string {
	return fmt.Sprintf(`name: %s
version: 1
family: %s
purpose: %s
inputs:
%soutputs:
%sconstraints:
  execution: proposal_only
  requires_guardian: true
  human_review_before_merge: true
  automatic_self_import: false
  model_optional: true
reusable_capabilities:
%s`, spec.Name, spec.Category, yamlSafe(spec.Purpose), yamlList(spec.Inputs), yamlList(spec.Outputs), yamlList(spec.Capabilities))
}

func yamlList(v []string) string {
	var b strings.Builder
	for _, s := range v {
		fmt.Fprintf(&b, "  - %s\n", yamlSafe(s))
	}
	return b.String()
}
