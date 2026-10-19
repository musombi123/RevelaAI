package genesis

import (
	"encoding/json"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	maxOpenAPIRouteLength = 64
	maxOpenAPITextLength  = 2000
	maxGeneratedListItems = 128
)

// generatedOpenAPI creates a staged OpenAPI 3.1 proposal. It documents
// validation and planning only: it does not activate or register an endpoint.
func generatedOpenAPI(spec ToolSpec) string {
	title := openAPIOneLine(spec.Title, 160)
	if title == "" {
		title = openAPIOneLine(spec.Name, 160)
	}
	if title == "" {
		title = "Genesis Tool"
	}

	route := normalizeOpenAPIRoute(spec.Name)
	operation := operationName(route)

	return fmt.Sprintf(`openapi: 3.1.0
info:
  title: %s
  version: 1.0.0
  description: %s
  license:
    name: "Proprietary - review required"
servers:
  - url: /
    description: "Relative server base; configure explicitly after human approval."
tags:
  - name: Planning
    description: "Proposal validation; no automatic execution or activation."
  - name: Capabilities
    description: "Generated requirements and capability coverage."
paths:
  /v1/%s/plan:
    post:
      tags: [Planning]
      summary: Validate input and return a non-executing plan
      operationId: create%sPlan
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PlanRequest'
      responses:
        '200':
          description: Plan created without activating or executing the proposal
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PlanResult'
        '400':
          description: Invalid request
        '401':
          description: Authentication required
        '403':
          description: Consent, authorization, or safety requirements not satisfied
        '413':
          description: Request exceeds the permitted size
        '429':
          description: Rate limit exceeded
        '500':
          description: Internal planning error
  /v1/%s/capability_plan:
    get:
      tags: [Capabilities]
      summary: Read the generated capability graph and requirement plan
      operationId: get%sCapabilityPlan
      security:
        - bearerAuth: []
      responses:
        '200':
          description: Staged capability plan; gaps and library matches require review
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CapabilityPlanResult'
        '401':
          description: Authentication required
        '404':
          description: Capability plan not found
        '500':
          description: Capability plan could not be read
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: "Genesis admin token"
  schemas:
    PlanRequest:
      type: object
      additionalProperties: false
      required:
        - action
      properties:
        action:
          type: string
          minLength: 1
          maxLength: 2000
          description: "Requested action to validate and plan."
        inputs:
          type: object
          maxProperties: 100
          propertyNames:
            minLength: 1
            maxLength: 100
          additionalProperties:
            type: string
            maxLength: 4000
        consent:
          type: boolean
          default: false
          description: "Explicit consent indicator; not a substitute for authorization."
    PlanResult:
      type: object
      properties:
        status:
          type: string
        tool:
          type: string
        summary:
          type: string
      required:
        - status
        - tool
        - summary
    CapabilityPlanResult:
      type: object
      properties:
        name:
          type: string
        status:
          type: string
          const: await_merge
        capability_plan:
          type: object
          description: "Generated capability plan. Actual fields are defined by the saved plan schema."
      required:
        - name
        - status
        - capability_plan
`, yamlSafe(title+" API proposal"),
		yamlSafe("Staged proposal only. This contract does not activate the endpoint. Human review, merge, and explicit host registration are required."),
		route,
		operation,
		route,
		operation)
}

// normalizeOpenAPIRoute constrains the route fragment to characters suitable
// for the project's tool URL format. It never accepts path separators.
func normalizeOpenAPIRoute(raw string) string {
	raw = strings.ToLower(strings.TrimSpace(raw))

	var b strings.Builder
	b.Grow(minOpenAPIInt(len(raw), maxOpenAPIRouteLength))

	lastSeparator := false

	for _, r := range raw {
		switch {
		case r >= 'a' && r <= 'z',
			r >= '0' && r <= '9':
			b.WriteRune(r)
			lastSeparator = false

		case r == '_' || r == '-':
			if b.Len() > 0 && !lastSeparator {
				b.WriteRune(r)
				lastSeparator = true
			}

		default:
			if b.Len() > 0 && !lastSeparator {
				b.WriteByte('-')
				lastSeparator = true
			}
		}

		if b.Len() >= maxOpenAPIRouteLength {
			break
		}
	}

	route := strings.Trim(b.String(), "-_")
	if route == "" || route == "." || route == ".." {
		return "genesis-tool"
	}

	return route
}

// operationName produces a stable ASCII operation identifier without slicing
// arbitrary UTF-8 byte sequences.
func operationName(raw string) string {
	raw = normalizeOpenAPIRoute(raw)

	var b strings.Builder
	b.Grow(len(raw))

	upperNext := true

	for _, r := range raw {
		if r == '-' || r == '_' {
			upperNext = true
			continue
		}

		if upperNext {
			if r >= 'a' && r <= 'z' {
				r = r - ('a' - 'A')
			}
			upperNext = false
		}

		b.WriteRune(r)
	}

	result := b.String()
	if result == "" {
		return "GenesisTool"
	}
	if result[0] >= '0' && result[0] <= '9' {
		result = "Tool" + result
	}
	return result
}

// yamlSafe returns a quoted YAML scalar. JSON double-quoted strings are
// compatible with YAML's double-quoted scalar syntax.
func yamlSafe(s string) string {
	raw, err := json.Marshal(s)
	if err != nil {
		return `""`
	}
	return string(raw)
}

// markdownList renders each input as exactly one Markdown bullet. Newlines
// and control characters cannot introduce additional checklist entries.
func markdownList(items []string) string {
	var b strings.Builder

	count := 0
	for _, item := range items {
		item = openAPIOneLine(item, maxOpenAPITextLength)
		if item == "" {
			continue
		}

		fmt.Fprintf(&b, "- %s\n", item)
		count++

		if count >= maxGeneratedListItems {
			break
		}
	}

	return strings.TrimSpace(b.String())
}

func generatedMergeChecklist(spec ToolSpec) string {
	title := openAPIOneLine(spec.Title, 200)
	if title == "" {
		title = "Untitled proposal"
	}

	category := openAPIOneLine(spec.Category, 120)
	if category == "" {
		category = "unspecified"
	}

	industry := openAPIOneLine(spec.Industry, 120)
	if industry == "" {
		industry = "unspecified"
	}

	return fmt.Sprintf(`# AWAIT MERGE — %s

Genesis has generated a proposal. It intentionally does not merge, install, execute, or activate the invention.

## Required before merge

- [ ] Review the demand, research provenance, and evidence.json. Independently verify external claims.
- [ ] Review capability_plan.json and assign an owner and test to every unresolved capability.
- [ ] Review all generated source files and reusable-library drivers.
- [ ] Run gofmt and go test ./... from core-one/.
- [ ] Run static analysis, dependency and license checks, secret scanning, and security tests.
- [ ] Verify external endpoints, authentication, authorization, rate limits, and data-retention rules.
- [ ] If hardware is involved, validate the exact BOM, schematics, and datasheets and obtain qualified review.
- [ ] Review privacy, consent, accessibility, rollback, observability, and disaster-recovery plans.
- [ ] Verify the generated OpenAPI contract against the actual handler and response shapes.
- [ ] Approve a deployment target and register the proposed API paths explicitly.
- [ ] Merge only after documented owner approval.

## Proposal metadata

**Generated category:** %s

**Industry:** %s

**Execution:** proposal only

**Activation:** prohibited until all required reviews are approved.
`, title, category, industry)
}

// generatedModel produces a constrained YAML metadata document. All dynamic
// scalar values are quoted, and empty collections are explicitly represented.
func generatedModel(spec ToolSpec) string {
	name := openAPIOneLine(spec.Name, 160)
	if name == "" {
		name = "genesis-tool"
	}

	category := openAPIOneLine(spec.Category, 120)
	if category == "" {
		category = "unspecified"
	}

	purpose := openAPIOneLine(spec.Purpose, 1000)
	if purpose == "" {
		purpose = "Purpose requires review."
	}

	return fmt.Sprintf(`schema_version: 1
name: %s
version: 1
family: %s
purpose: %s
%s%sconstraints:
  execution: proposal_only
  requires_guardian: true
  human_review_before_merge: true
  automatic_self_import: false
  model_optional: true
reusable_capabilities:
%s`,
		yamlSafe(name),
		yamlSafe(category),
		yamlSafe(purpose),
		yamlSequenceField("inputs", spec.Inputs),
		yamlSequenceField("outputs", spec.Outputs),
		yamlSequenceField("items", spec.Capabilities))
}

// yamlList retains the original helper interface and returns an indented
// sequence suitable for insertion beneath a YAML mapping key.
func yamlList(values []string) string {
	var b strings.Builder
	count := 0

	for _, value := range values {
		value = openAPIOneLine(value, maxOpenAPITextLength)
		if value == "" {
			continue
		}

		fmt.Fprintf(&b, "  - %s\n", yamlSafe(value))
		count++

		if count >= maxGeneratedListItems {
			break
		}
	}

	return b.String()
}

func yamlSequenceField(name string, values []string) string {
	var b strings.Builder

	b.WriteString(name)
	b.WriteByte(':')

	list := yamlList(values)
	if strings.TrimSpace(list) == "" {
		b.WriteString(" []\n")
		return b.String()
	}

	b.WriteByte('\n')
	b.WriteString(list)
	return b.String()
}

func openAPIOneLine(raw string, maxBytes int) string {
	if maxBytes <= 0 || !utf8.ValidString(raw) {
		return ""
	}

	raw = strings.TrimSpace(raw)

	var b strings.Builder
	b.Grow(minOpenAPIInt(len(raw), maxBytes))

	for _, r := range raw {
		if unicode.IsControl(r) || r == '\u2028' || r == '\u2029' {
			r = ' '
		}

		size := utf8.RuneLen(r)
		if size <= 0 || b.Len()+size > maxBytes {
			break
		}

		b.WriteRune(r)
	}

	return strings.Join(strings.Fields(b.String()), " ")
}

func minOpenAPIInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
