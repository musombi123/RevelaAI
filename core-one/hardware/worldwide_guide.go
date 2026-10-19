// Package hardware builds localized hardware integration guides and
// authorized, reviewable tool-integration proposals.
//
// Generated tools are proposals. This package does not flash firmware,
// connect to devices, actuate physical equipment, or activate generated code.
package hardware

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"revela-worldwide.local/libs/country"
	"revela-worldwide.local/libs/i18n"
)

const (
	AuthorityScopeGenerateHardwareProposal = "generate_hardware_proposal"

	maxToolNameBytes       = 64
	maxPurposeBytes        = 2000
	maxHardwareFieldBytes  = 200
	maxHardwareURLBytes    = 2048
	maxHardwareListItems   = 64
	maxHardwareItemBytes   = 300
	maxGeneratedFileBytes  = 2 << 20
	maxGeneratedTotalBytes = 8 << 20
)

// ToolIntegrationRequest describes the requested tool and its intended
// hardware target. The supplied hardware information must still be verified
// against manufacturer datasheets before real equipment is connected.
type ToolIntegrationRequest struct {
	ToolName                  string   `json:"tool_name"`
	ToolPurpose               string   `json:"tool_purpose"`
	HardwareType              string   `json:"hardware_type"`
	HardwareManufacturer      string   `json:"hardware_manufacturer"`
	HardwareModel             string   `json:"hardware_model"`
	Controller                string   `json:"controller"`
	DatasheetURL              string   `json:"datasheet_url"`
	Interfaces                []string `json:"interfaces"`
	RequiredCapabilities      []string `json:"required_capabilities"`
	OperatingVoltage          string   `json:"operating_voltage,omitempty"`
	OperatingCurrent          string   `json:"operating_current,omitempty"`
	RequiresPhysicalActuation bool     `json:"requires_physical_actuation"`
	CountryCode               string   `json:"country_code,omitempty"`
	Language                  string   `json:"language,omitempty"`
}

// IntegrationAuthority represents an approval issued by a trusted host
// application or review workflow.
//
// Do not populate this structure directly from an untrusted HTTP request.
// The caller must verify the actual approval record before constructing it.
type IntegrationAuthority struct {
	Granted             bool      `json:"granted"`
	Scope               string    `json:"scope"`
	Reviewer            string    `json:"reviewer"`
	ApprovalReference   string    `json:"approval_reference"`
	ToolName            string    `json:"tool_name"`
	HardwareManufacturer string    `json:"hardware_manufacturer"`
	HardwareModel       string    `json:"hardware_model"`
	ExpiresAt           time.Time `json:"expires_at"`
}

// IntegrationArtifact is one generated source or documentation file.
// Content is held in memory until an authorized proposal is materialized.
type IntegrationArtifact struct {
	Path    string `json:"path"`
	Content string `json:"content"`
	SHA256  string `json:"sha256"`
}

// IntegrationProposal is an immutable-in-intent proposal bundle. Its status
// remains review-only even when its generation and storage were authorized.
type IntegrationProposal struct {
	ID                    string                `json:"id"`
	Status                string                `json:"status"`
	CreatedAt             time.Time             `json:"created_at"`
	ToolName              string                `json:"tool_name"`
	CountryCode           string                `json:"country_code"`
	Language              string                `json:"language"`
	HardwareManufacturer  string                `json:"hardware_manufacturer"`
	HardwareModel         string                `json:"hardware_model"`
	Authorized            bool                  `json:"authorized"`
	AuthorizedBy          string                `json:"authorized_by,omitempty"`
	ApprovalReference     string                `json:"approval_reference,omitempty"`
	AuthorizationExpiresAt time.Time             `json:"authorization_expires_at,omitempty"`
	Artifacts             []IntegrationArtifact `json:"artifacts"`
	Notice                string                `json:"notice"`
}

// BuildWorldwideGuide preserves the original API and returns a localized
// reference guide with an explicit hardware-integration workflow.
//
// Country and language localization uses the existing country and i18n
// libraries. This function does not need generation authority because it
// only returns guidance and does not create or activate a tool.
func BuildWorldwideGuide(
	countryCode string,
	language string,
) (string, country.Profile, error) {
	profile, err := country.Resolve(countryCode, language)
	if err != nil {
		return "", country.Profile{}, err
	}

	var guide strings.Builder
	guide.WriteString(i18n.WorldwideGuide(profile))

	guide.WriteString("\n\n")
	guide.WriteString(generalIntegrationGuide(profile))

	return guide.String(), profile, nil
}

// BuildToolIntegrationGuide returns a guide specifically tailored to a
// requested tool, controller, device, interfaces, and country profile.
//
// Incomplete hardware information does not authorize guesswork. Unknown
// part numbers, electrical ratings, and pin mappings are explicitly left
// for verification during engineering review.
func BuildToolIntegrationGuide(
	request ToolIntegrationRequest,
) (string, country.Profile, error) {
	request, err := normalizeIntegrationRequest(request, false)
	if err != nil {
		return "", country.Profile{}, err
	}

	guide, profile, err := BuildWorldwideGuide(
		request.CountryCode,
		request.Language,
	)
	if err != nil {
		return "", country.Profile{}, err
	}

	var extra strings.Builder

	extra.WriteString("\n\n# Tool-Specific Hardware Integration\n\n")
	fmt.Fprintf(&extra, "**Tool:** %s\n\n", request.ToolName)
	fmt.Fprintf(&extra, "**Purpose:** %s\n\n", request.ToolPurpose)
	writeHardwareField(&extra, "Hardware type", request.HardwareType)
	writeHardwareField(&extra, "Manufacturer", request.HardwareManufacturer)
	writeHardwareField(&extra, "Hardware model", request.HardwareModel)
	writeHardwareField(&extra, "Controller", request.Controller)
	writeHardwareField(&extra, "Operating voltage", request.OperatingVoltage)
	writeHardwareField(&extra, "Operating current", request.OperatingCurrent)

	if request.DatasheetURL != "" {
		fmt.Fprintf(&extra, "**Datasheet reference:** %s\n\n", request.DatasheetURL)
	} else {
		extra.WriteString("**Datasheet reference:** Not supplied; obtain the exact manufacturer's datasheet before selecting pins, power, drivers, or protection.\n\n")
	}

	extra.WriteString("## 1. Match the tool to the actual hardware\n\n")
	extra.WriteString("1. Confirm the exact hardware manufacturer, model, board revision, and controller.\n")
	extra.WriteString("2. Verify the original manufacturer datasheet and its revision.\n")
	extra.WriteString("3. Confirm supported interfaces, logic levels, operating limits, connector layout, and environmental conditions.\n")
	extra.WriteString("4. Map every requested tool capability to a documented hardware function. Mark unsupported capabilities as unresolved.\n")
	extra.WriteString("5. Do not infer pin numbers, register addresses, electrical ratings, or device commands from the product category alone.\n\n")

	extra.WriteString("## 2. Interface and capability mapping\n\n")
	extra.WriteString("### Declared interfaces\n\n")
	extra.WriteString(renderIntegrationList(request.Interfaces))
	extra.WriteString("\n\n### Requested capabilities\n\n")
	extra.WriteString(renderIntegrationList(request.RequiredCapabilities))
	extra.WriteString("\n\n")

	extra.WriteString("## 3. Proposed software integration architecture\n\n")
	extra.WriteString("Separate the user-facing tool contract from the device-specific adapter. Validate input at the tool boundary, validate hardware configuration in the adapter, and keep physical-device execution behind a separately reviewed service with explicit authorization.\n\n")
	extra.WriteString("The generated scaffold implements planning only. Adding a hardware driver requires a separately reviewed adapter, documented permissions, appropriate test equipment, and integration-specific tests.\n\n")

	extra.WriteString("## 4. Electrical and physical safeguards\n\n")
	extra.WriteString("- Verify operating voltage, current, inrush, grounding, isolation, and protection from actual datasheets.\n")
	extra.WriteString("- Never connect an unknown load directly to a controller output.\n")
	extra.WriteString("- Use appropriate drivers and protection for motors, relays, and other inductive or high-current equipment.\n")
	extra.WriteString("- Have qualified personnel handle mains wiring and other hazardous electrical work.\n")
	extra.WriteString("- Test with an appropriate fixture and current-limited supply before connecting real loads.\n")
	extra.WriteString("- Confirm safe boot defaults, timeout behavior, emergency stopping, fault handling, and recovery behavior where applicable.\n\n")

	if request.RequiresPhysicalActuation {
		extra.WriteString("**Actuation requirement:** This request indicates that the eventual system may control physical equipment. Generation authority does not authorize actuation. A real driver requires separate implementation review, safety validation, and explicit operational permissions.\n\n")
	} else {
		extra.WriteString("**Execution boundary:** This request is documented as non-actuating. Any later physical-control requirement must undergo a separate review.\n\n")
	}

	extra.WriteString("## 5. Country and compliance context\n\n")
	fmt.Fprintf(&extra, "- Country profile: %s (%s)\n", profile.Name, profile.Code)
	fmt.Fprintf(&extra, "- Language: %s\n", profile.Language)
	fmt.Fprintf(&extra, "- Currency context: %s\n", profile.Currency)

	if profile.NominalACVoltage > 0 {
		fmt.Fprintf(&extra, "- Nominal AC voltage recorded in the profile: %d V\n", profile.NominalACVoltage)
	}
	if profile.FrequencyHz != "" {
		fmt.Fprintf(&extra, "- Frequency recorded in the profile: %s\n", profile.FrequencyHz)
	}

	extra.WriteString("\nCountry-profile data is contextual information, not proof of compliance or a substitute for verifying the applicable current standards.\n\n")

	extra.WriteString("## 6. Acceptance checklist\n\n")
	extra.WriteString("- [ ] Exact hardware and controller model confirmed.\n")
	extra.WriteString("- [ ] Manufacturer datasheet and revision verified.\n")
	extra.WriteString("- [ ] Capability-to-interface mapping documented.\n")
	extra.WriteString("- [ ] Electrical ratings and required protection checked.\n")
	extra.WriteString("- [ ] Adapter contract and failure behavior reviewed.\n")
	extra.WriteString("- [ ] Unit and integration tests completed.\n")
	extra.WriteString("- [ ] Physical testing performed where applicable.\n")
	extra.WriteString("- [ ] Permissions, privacy, and safety controls approved.\n")
	extra.WriteString("- [ ] Owner approves integration before activation.\n")

	return guide + extra.String(), profile, nil
}

// GenerateIntegrationProposal creates the source and documentation for a
// hardware-adapted tool scaffold. A trusted approval bound to this tool and
// hardware model is required.
//
// The returned driver supports validation and planning through an adapter
// interface. It does not implement device-specific commands or actuate
// physical equipment.
func GenerateIntegrationProposal(
	request ToolIntegrationRequest,
	authority IntegrationAuthority,
) (IntegrationProposal, error) {
	request, err := normalizeIntegrationRequest(request, true)
	if err != nil {
		return IntegrationProposal{}, err
	}

	if err := validateGenerationAuthority(request, authority); err != nil {
		return IntegrationProposal{}, err
	}

	guide, profile, err := BuildToolIntegrationGuide(request)
	if err != nil {
		return IntegrationProposal{}, err
	}

	now := time.Now().UTC()
	id := integrationProposalID(request, authority)

	proposal := IntegrationProposal{
		ID:                    id,
		Status:                "await_hardware_review",
		CreatedAt:             now,
		ToolName:              request.ToolName,
		CountryCode:           profile.Code,
		Language:              profile.Language,
		HardwareManufacturer:  request.HardwareManufacturer,
		HardwareModel:         request.HardwareModel,
		Authorized:            true,
		AuthorizedBy:          cleanIntegrationText(authority.Reviewer, 120),
		ApprovalReference:     cleanIntegrationText(authority.ApprovalReference, 200),
		AuthorizationExpiresAt: authority.ExpiresAt.UTC(),
		Notice:                "Authorized for proposal generation only. No device access, firmware flashing, physical actuation, or production activation is performed.",
		Artifacts:             []IntegrationArtifact{},
	}

	driver := generatedHardwareDriver(request, profile)
	driverTest := generatedHardwareDriverTest(request)
	readme := generatedHardwareReadme(request, profile, id)

	manifest := struct {
		SchemaVersion int                    `json:"schema_version"`
		ID             string                 `json:"id"`
		Status         string                 `json:"status"`
		CreatedAt      time.Time              `json:"created_at"`
		Tool           ToolIntegrationRequest `json:"tool"`
		Authorization  map[string]any        `json:"authorization"`
		ReviewRequired []string               `json:"review_required"`
		Execution      string                 `json:"execution"`
	}{
		SchemaVersion: 1,
		ID:            id,
		Status:        proposal.Status,
		CreatedAt:     now,
		Tool:          request,
		Authorization: map[string]any{
			"scope":             AuthorityScopeGenerateHardwareProposal,
			"reviewer":          proposal.AuthorizedBy,
			"approval_reference": proposal.ApprovalReference,
			"expires_at":        proposal.AuthorizationExpiresAt,
		},
		ReviewRequired: []string{
			"Verify exact hardware and controller datasheets.",
			"Review interface mappings and electrical ratings.",
			"Implement and review any device-specific adapter separately.",
			"Run tests and appropriate hardware-in-the-loop validation.",
			"Approve deployment and operational permissions separately.",
		},
		Execution: "proposal_only",
	}

	planBytes, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return IntegrationProposal{}, fmt.Errorf("encode integration plan: %w", err)
	}

	artifacts := []struct {
		path    string
		content string
	}{
		{"driver.go", driver},
		{"driver_test.go", driverTest},
		{"README.md", readme},
		{"hardware_guide.md", guide},
		{"integration_plan.json", string(planBytes) + "\n"},
	}

	total := 0
	for _, artifact := range artifacts {
		if len(artifact.content) > maxGeneratedFileBytes {
			return IntegrationProposal{}, fmt.Errorf("generated artifact %s exceeds the size limit", artifact.path)
		}
		total += len(artifact.content)
		if total > maxGeneratedTotalBytes {
			return IntegrationProposal{}, errors.New("generated integration proposal exceeds the total size limit")
		}

		hash := sha256.Sum256([]byte(artifact.content))
		proposal.Artifacts = append(proposal.Artifacts, IntegrationArtifact{
			Path:    artifact.path,
			Content: artifact.content,
			SHA256:  hex.EncodeToString(hash[:]),
		})
	}

	return proposal, nil
}

// WriteIntegrationProposal persists an authorized proposal into a new,
// dedicated directory under an existing non-symlink output root.
//
// The function refuses to overwrite an existing proposal directory. It does
// not compile, install, execute, flash, or activate the generated tool.
func WriteIntegrationProposal(
	outputRoot string,
	proposal IntegrationProposal,
) (string, error) {
	if !proposal.Authorized {
		return "", errors.New("proposal does not contain authorized generation evidence")
	}
	if proposal.Status != "await_hardware_review" {
		return "", errors.New("proposal status is not eligible for materialization")
	}
	if !validProposalID(proposal.ID) {
		return "", errors.New("invalid integration proposal identifier")
	}
	if !proposal.AuthorizationExpiresAt.IsZero() &&
		time.Now().UTC().After(proposal.AuthorizationExpiresAt) {
		return "", errors.New("proposal generation authorization has expired")
	}
	if len(proposal.Artifacts) == 0 || len(proposal.Artifacts) > 16 {
		return "", errors.New("proposal artifact list is empty or exceeds the limit")
	}

	root := filepath.Clean(strings.TrimSpace(outputRoot))
	if root == "" || root == "." {
		return "", errors.New("an explicit output root is required")
	}

	info, err := os.Lstat(root)
	if err != nil {
		return "", fmt.Errorf("inspect output root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("output root must be an existing directory, not a symlink")
	}

	target := filepath.Join(root, "hardware-"+proposal.ID)
	if err := os.Mkdir(target, 0o700); err != nil {
		return "", fmt.Errorf("create proposal directory without overwriting existing content: %w", err)
	}

	complete := false
	defer func() {
		if !complete {
			_ = os.RemoveAll(target)
		}
	}()

	seen := make(map[string]struct{}, len(proposal.Artifacts))
	total := 0

	for _, artifact := range proposal.Artifacts {
		if !validArtifactFilename(artifact.Path) {
			return "", fmt.Errorf("invalid artifact filename %q", artifact.Path)
		}

		if _, exists := seen[artifact.Path]; exists {
			return "", fmt.Errorf("duplicate artifact path %q", artifact.Path)
		}
		seen[artifact.Path] = struct{}{}

		if len(artifact.Content) > maxGeneratedFileBytes {
			return "", fmt.Errorf("artifact %s exceeds the size limit", artifact.Path)
		}
		total += len(artifact.Content)
		if total > maxGeneratedTotalBytes {
			return "", errors.New("proposal exceeds the total size limit")
		}

		sum := sha256.Sum256([]byte(artifact.Content))
		if artifact.SHA256 != hex.EncodeToString(sum[:]) {
			return "", fmt.Errorf("artifact integrity check failed for %s", artifact.Path)
		}

		path := filepath.Join(target, artifact.Path)
		file, err := os.OpenFile(
			path,
			os.O_CREATE|os.O_EXCL|os.O_WRONLY,
			0o600,
		)
		if err != nil {
			return "", fmt.Errorf("create artifact %s: %w", artifact.Path, err)
		}

		written, writeErr := file.Write([]byte(artifact.Content))
		if writeErr == nil && written != len(artifact.Content) {
			writeErr = errors.New("short write")
		}
		if writeErr == nil {
			writeErr = file.Sync()
		}
		closeErr := file.Close()

		if writeErr != nil {
			return "", fmt.Errorf("write artifact %s: %w", artifact.Path, writeErr)
		}
		if closeErr != nil {
			return "", fmt.Errorf("close artifact %s: %w", artifact.Path, closeErr)
		}
	}

	complete = true
	return target, nil
}

func validateGenerationAuthority(
	request ToolIntegrationRequest,
	authority IntegrationAuthority,
) error {
	if !authority.Granted {
		return errors.New("explicit trusted authorization is required to generate a hardware tool proposal")
	}
	if authority.Scope != AuthorityScopeGenerateHardwareProposal {
		return errors.New("authorization scope does not permit hardware proposal generation")
	}
	if cleanIntegrationText(authority.Reviewer, 120) == "" {
		return errors.New("authorization must identify the approving reviewer")
	}
	if cleanIntegrationText(authority.ApprovalReference, 200) == "" {
		return errors.New("authorization must contain an approval reference")
	}
	if authority.ExpiresAt.IsZero() || !time.Now().UTC().Before(authority.ExpiresAt) {
		return errors.New("a valid, unexpired generation authorization is required")
	}

	if normalizeHardwareName(authority.ToolName) != request.ToolName {
		return errors.New("authorization is not bound to this tool name")
	}
	if !strings.EqualFold(
		cleanIntegrationText(authority.HardwareManufacturer, maxHardwareFieldBytes),
		request.HardwareManufacturer,
	) {
		return errors.New("authorization is not bound to this hardware manufacturer")
	}
	if !strings.EqualFold(
		cleanIntegrationText(authority.HardwareModel, maxHardwareFieldBytes),
		request.HardwareModel,
	) {
		return errors.New("authorization is not bound to this hardware model")
	}

	return nil
}

func normalizeIntegrationRequest(
	request ToolIntegrationRequest,
	requireHardwareDetails bool,
) (ToolIntegrationRequest, error) {
	request.ToolName = normalizeHardwareName(request.ToolName)
	if request.ToolName == "" {
		return request, errors.New("a valid tool name is required")
	}

	var ok bool
	request.ToolPurpose, ok = normalizeRequiredField(request.ToolPurpose, maxPurposeBytes)
	if !ok {
		return request, errors.New("a non-empty, bounded tool purpose is required")
	}

	fields := []*string{
		&request.HardwareType,
		&request.HardwareManufacturer,
		&request.HardwareModel,
		&request.Controller,
		&request.OperatingVoltage,
		&request.OperatingCurrent,
	}

	for _, field := range fields {
		*field = cleanIntegrationText(*field, maxHardwareFieldBytes)
	}

	request.DatasheetURL = strings.TrimSpace(request.DatasheetURL)
	if request.DatasheetURL != "" {
		if !validDatasheetURL(request.DatasheetURL) {
			return request, errors.New("datasheet URL must be a valid HTTPS URL without embedded credentials")
		}
		if len(request.DatasheetURL) > maxHardwareURLBytes {
			return request, errors.New("datasheet URL exceeds the permitted size")
		}
	}

	var err error
	request.Interfaces, err = normalizeStringList(request.Interfaces, maxHardwareListItems, maxHardwareFieldBytes)
	if err != nil {
		return request, fmt.Errorf("interfaces: %w", err)
	}
	request.RequiredCapabilities, err = normalizeStringList(request.RequiredCapabilities, maxHardwareListItems, maxHardwareItemBytes)
	if err != nil {
		return request, fmt.Errorf("required capabilities: %w", err)
	}

	if requireHardwareDetails {
		required := map[string]string{
			"hardware type":         request.HardwareType,
			"manufacturer":           request.HardwareManufacturer,
			"hardware model":        request.HardwareModel,
			"controller":             request.Controller,
			"manufacturer datasheet": request.DatasheetURL,
		}
		for label, value := range required {
			if strings.TrimSpace(value) == "" {
				return request, fmt.Errorf("%s is required for hardware-specific tool generation", label)
			}
		}
		if len(request.Interfaces) == 0 {
			return request, errors.New("at least one documented hardware interface is required")
		}
		if len(request.RequiredCapabilities) == 0 {
			return request, errors.New("at least one required capability is needed to generate a tool")
		}
	}

	return request, nil
}

func generatedHardwareDriver(
	request ToolIntegrationRequest,
	profile country.Profile,
) string {
	pkg := hardwareGoPackageName(request.ToolName)
	capabilities := goStringSlice(request.RequiredCapabilities)
	interfaces := goStringSlice(request.Interfaces)

	return fmt.Sprintf(`// Code generated by Revela Genesis Hardware Integration Forge.
// Proposal only. Review against the manufacturer's datasheets before integration.
package %s

import (
	"context"
	"errors"
	"strings"
	"time"
)

const (
	ToolName = %s
	ToolPurpose = %s
	HardwareType = %s
	HardwareManufacturer = %s
	HardwareModel = %s
	Controller = %s
	DatasheetURL = %s
	CountryCode = %s
	Language = %s
	OperatingVoltage = %s
	OperatingCurrent = %s
	RequiresPhysicalActuation = %t
)

var RequiredCapabilities = []string{%s}
var SupportedInterfaceDeclarations = []string{%s}

type Request struct {
	Action string
	Inputs map[string]string
	Consent bool
}

type Plan struct {
	Status string
	Tool string
	HardwareModel string
	Summary string
	CreatedAt time.Time
	RequiredCapabilities []string
	UnresolvedRequirements []string
}

// HardwareAdapter is an integration boundary for reviewed, device-specific
// adapters. Implementations must validate configuration and build plans.
// Do not put physical actuation into BuildPlan.
type HardwareAdapter interface {
	Validate(context.Context, Request) error
	BuildPlan(context.Context, Request) (Plan, error)
}

type Tool struct {
	Adapter HardwareAdapter
}

// Run validates the request and produces a proposal plan. It never sends
// device commands or directly actuates physical equipment.
func (t Tool) Run(ctx context.Context, request Request) (Plan, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return Plan{}, err
	}

	request.Action = strings.TrimSpace(request.Action)
	if request.Action == "" {
		return Plan{}, errors.New("action is required")
	}
	if len(request.Action) > 2000 {
		return Plan{}, errors.New("action exceeds the maximum size")
	}
	if len(request.Inputs) > 100 {
		return Plan{}, errors.New("too many input fields")
	}
	if RequiresPhysicalActuation && !request.Consent {
		return Plan{}, errors.New("explicit consent is required for this hardware-related plan")
	}

	// No device-specific adapter has been implemented by the generator.
	// Returning a reviewable plan is safer than guessing hardware commands.
	if t.Adapter == nil {
		return Plan{
			Status: "await_hardware_adapter",
			Tool: ToolName,
			HardwareModel: HardwareModel,
			Summary: "Proposal created. Exact hardware integration and testing are still required.",
			CreatedAt: time.Now().UTC(),
			RequiredCapabilities: append([]string(nil), RequiredCapabilities...),
			UnresolvedRequirements: []string{
				"Review manufacturer datasheet and hardware compatibility.",
				"Implement and review the device-specific adapter.",
				"Verify electrical ratings and required protection.",
				"Run unit and integration tests before deployment.",
				"Obtain separate approval before physical actuation.",
			},
		}, nil
	}

	if err := t.Adapter.Validate(ctx, request); err != nil {
		return Plan{}, err
	}

	plan, err := t.Adapter.BuildPlan(ctx, request)
	if err != nil {
		return Plan{}, err
	}

	// Never convert an adapter response into an active/approved state.
	plan.Status = "await_hardware_review"
	plan.Tool = ToolName
	plan.HardwareModel = HardwareModel
	if plan.CreatedAt.IsZero() {
		plan.CreatedAt = time.Now().UTC()
	}
	return plan, nil
}
`,
		pkg,
		strconv.Quote(request.ToolName),
		strconv.Quote(request.ToolPurpose),
		strconv.Quote(request.HardwareType),
		strconv.Quote(request.HardwareManufacturer),
		strconv.Quote(request.HardwareModel),
		strconv.Quote(request.Controller),
		strconv.Quote(request.DatasheetURL),
		strconv.Quote(profile.Code),
		strconv.Quote(profile.Language),
		strconv.Quote(request.OperatingVoltage),
		strconv.Quote(request.OperatingCurrent),
		request.RequiresPhysicalActuation,
		capabilities,
		interfaces,
	)
}

func generatedHardwareDriverTest(request ToolIntegrationRequest) string {
	pkg := hardwareGoPackageName(request.ToolName)

	return fmt.Sprintf(`package %s

import (
	"context"
	"testing"
)

func TestRunWithoutAdapterProducesReviewProposal(t *testing.T) {
	tool := Tool{}
	plan, err := tool.Run(context.Background(), Request{Action: "inspect"})
	if %t && err == nil {
		t.Fatal("physical-operation request without consent should fail")
	}
	if err != nil {
		if %t {
			return
		}
		t.Fatal(err)
	}
	if plan.Status != "await_hardware_adapter" {
		t.Fatalf("expected await_hardware_adapter, got %%s", plan.Status)
	}
	if plan.Tool != ToolName {
		t.Fatalf("unexpected tool name %%q", plan.Tool)
	}
	if len(plan.UnresolvedRequirements) == 0 {
		t.Fatal("hardware review requirements should be present")
	}
}

func TestRunRejectsEmptyAction(t *testing.T) {
	if _, err := (Tool{}).Run(context.Background(), Request{}); err == nil {
		t.Fatal("empty action should fail")
	}
}

func TestRunRejectsTooManyInputs(t *testing.T) {
	inputs := make(map[string]string, 101)
	for i := 0; i < 101; i++ {
		inputs[string(rune('a'+i))] = "value"
	}
	if _, err := (Tool{}).Run(context.Background(), Request{
		Action: "inspect",
		Inputs: inputs,
		Consent: true,
	}); err == nil {
		t.Fatal("too many inputs should fail")
	}
}
`,
		pkg,
		request.RequiresPhysicalActuation,
		request.RequiresPhysicalActuation,
	)
}

func generatedHardwareReadme(
	request ToolIntegrationRequest,
	profile country.Profile,
	id string,
) string {
	var b strings.Builder

	fmt.Fprintf(&b, "# %s Hardware Integration Proposal\n\n", request.ToolName)
	fmt.Fprintf(&b, "- **Proposal ID:** `%s`\n", id)
	fmt.Fprintf(&b, "- **Status:** `await_hardware_review`\n")
	fmt.Fprintf(&b, "- **Purpose:** %s\n", request.ToolPurpose)
	fmt.Fprintf(&b, "- **Hardware:** %s %s\n", request.HardwareManufacturer, request.HardwareModel)
	fmt.Fprintf(&b, "- **Controller:** %s\n", request.Controller)
	fmt.Fprintf(&b, "- **Country:** %s (%s)\n", profile.Name, profile.Code)
	fmt.Fprintf(&b, "- **Language:** %s\n\n", profile.Language)

	b.WriteString("## Generated artifacts\n\n")
	b.WriteString("- `driver.go`: proposal-only driver contract and review-gated planner.\n")
	b.WriteString("- `driver_test.go`: initial input-validation and proposal-boundary tests.\n")
	b.WriteString("- `hardware_guide.md`: localized guide for integration and testing.\n")
	b.WriteString("- `integration_plan.json`: request metadata, authorization evidence, and outstanding reviews.\n\n")

	b.WriteString("## Hardware integration boundary\n\n")
	b.WriteString("The generated code does not control physical equipment. A device-specific adapter must be implemented and reviewed against the exact manufacturer datasheet. Declared interfaces and capabilities are based on the request and have not been independently verified.\n\n")

	b.WriteString("## Required review\n\n")
	b.WriteString("- [ ] Verify the exact hardware model, revision, datasheet, and operating ratings.\n")
	b.WriteString("- [ ] Confirm that the requested interfaces exist on the selected controller.\n")
	b.WriteString("- [ ] Map capabilities to documented device functions.\n")
	b.WriteString("- [ ] Implement and review the device-specific adapter.\n")
	b.WriteString("- [ ] Validate input, permissions, error handling, and safe failure behavior.\n")
	b.WriteString("- [ ] Run unit and hardware integration tests using an appropriate test fixture.\n")
	b.WriteString("- [ ] Approve deployment and any physical actuation separately.\n\n")

	b.WriteString("## Security and activation\n\n")
	b.WriteString("Generation authority permits creation of this scaffold only. It does not grant authority to flash firmware, connect to a device, alter safety settings, actuate equipment, merge the source into Genesis Core-One, or deploy the tool.\n")

	return b.String()
}

func generalIntegrationGuide(profile country.Profile) string {
	var b strings.Builder

	b.WriteString("\n\n# Hardware Tool Integration Workflow\n\n")
	b.WriteString("This guide is intended to help adapt a generated tool to a specific hardware platform. It also describes how an authorized integration service can generate a reviewable tool scaffold.\n\n")

	fmt.Fprintf(&b, "- Country profile: %s (%s)\n", profile.Name, profile.Code)
	fmt.Fprintf(&b, "- Language: %s\n", profile.Language)
	fmt.Fprintf(&b, "- Currency context: %s\n", profile.Currency)

	if profile.NominalACVoltage > 0 {
		fmt.Fprintf(&b, "- Profile AC voltage: %d V\n", profile.NominalACVoltage)
	}
	if profile.FrequencyHz != "" {
		fmt.Fprintf(&b, "- Profile frequency: %s\n", profile.FrequencyHz)
	}

	b.WriteString("\n## Integration stages\n\n")
	b.WriteString("1. Identify the exact device, manufacturer, model, controller, and board revision.\n")
	b.WriteString("2. Obtain the manufacturer's datasheet and verify electrical and communication requirements.\n")
	b.WriteString("3. Describe the tool capabilities and map each to a supported hardware interface.\n")
	b.WriteString("4. Generate a proposal scaffold under a trusted integration workflow.\n")
	b.WriteString("5. Implement the device-specific adapter and appropriate validation.\n")
	b.WriteString("6. Test with a safe fixture and verify failure handling.\n")
	b.WriteString("7. Obtain independent integration approval before any physical operation.\n\n")

	b.WriteString("## Generation authority\n\n")
	b.WriteString("A host system may call `GenerateIntegrationProposal` only after authenticating the approver and verifying an unexpired authorization bound to the specific tool, hardware manufacturer, and model. It may then call `WriteIntegrationProposal` to store the generated files in a new proposal directory. Never manufacture an authorization from untrusted request fields.\n\n")

	b.WriteString("## Country-specific limits\n\n")
	b.WriteString("Country and language profiles supply contextual information. They do not verify that hardware complies with applicable electrical, radio, privacy, product-safety, or other requirements. Supplier directories are leads, not verified price or availability quotations.\n")

	return b.String()
}

func integrationProposalID(
	request ToolIntegrationRequest,
	authority IntegrationAuthority,
) string {
	identity := strings.Join([]string{
		request.ToolName,
		strings.ToLower(request.HardwareManufacturer),
		strings.ToLower(request.HardwareModel),
		request.Controller,
		authority.ApprovalReference,
	}, "\x00")

	hash := sha256.Sum256([]byte(identity))
	return "hw-" + hex.EncodeToString(hash[:12])
}

func validProposalID(value string) bool {
	if len(value) != len("hw-")+24 || !strings.HasPrefix(value, "hw-") {
		return false
	}

	for _, r := range strings.TrimPrefix(value, "hw-") {
		if !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f') {
			return false
		}
	}
	return true
}

func validArtifactFilename(name string) bool {
	if name == "" || filepath.Base(name) != name || strings.ContainsAny(name, `/\`) {
		return false
	}
	if name == "." || name == ".." || len(name) > 120 {
		return false
	}

	for _, r := range name {
		if !(r >= 'a' && r <= 'z' ||
			r >= 'A' && r <= 'Z' ||
			r >= '0' && r <= '9' ||
			r == '_' || r == '-' || r == '.') {
			return false
		}
	}
	return true
}

func validDatasheetURL(raw string) bool {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return false
	}

	return parsed.Scheme == "https" &&
		parsed.Hostname() != "" &&
		parsed.User == nil &&
		parsed.Fragment == ""
}

func normalizeHardwareName(raw string) string {
	raw = strings.ToLower(strings.TrimSpace(raw))

	var b strings.Builder
	b.Grow(minHardwareInt(len(raw), maxToolNameBytes))

	separator := false

	for _, r := range raw {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
			separator = false
		case r == '_' || r == '-' || unicode.IsSpace(r):
			if b.Len() > 0 && !separator {
				if r == '_' {
					b.WriteByte('_')
				} else {
					b.WriteByte('-')
				}
				separator = true
			}
		default:
			if b.Len() > 0 && !separator {
				b.WriteByte('-')
				separator = true
			}
		}

		if b.Len() >= maxToolNameBytes {
			break
		}
	}

	result := strings.Trim(b.String(), "-_")
	if result == "" || result == "." || result == ".." {
		return ""
	}
	if result[0] >= '0' && result[0] <= '9' {
		result = "tool-" + result
	}
	if len(result) > maxToolNameBytes {
		return ""
	}

	return result
}

func hardwareGoPackageName(name string) string {
	name = normalizeHardwareName(name)
	if name == "" {
		return "hardware_tool"
	}

	var b strings.Builder
	for _, r := range name {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			b.WriteRune(r)
		} else {
			b.WriteByte('_')
		}
	}

	result := strings.Trim(b.String(), "_")
	if result == "" {
		return "hardware_tool"
	}
	if result[0] >= '0' && result[0] <= '9' {
		result = "tool_" + result
	}

	switch result {
	case "break", "default", "func", "interface", "select", "case",
		"defer", "go", "map", "struct", "chan", "else", "goto",
		"package", "switch", "const", "fallthrough", "if", "range",
		"type", "continue", "for", "import", "return", "var":
		result += "_tool"
	}

	return result
}

func normalizeRequiredField(raw string, maxBytes int) (string, bool) {
	value := cleanIntegrationText(raw, maxBytes)
	return value, value != ""
}

func cleanIntegrationText(raw string, maxBytes int) string {
	if maxBytes <= 0 || !utf8.ValidString(raw) {
		return ""
	}

	raw = strings.TrimSpace(raw)
	var b strings.Builder
	b.Grow(minHardwareInt(len(raw), maxBytes))

	for _, r := range raw {
		if unicode.IsControl(r) {
			if unicode.IsSpace(r) {
				r = ' '
			} else {
				return ""
			}
		}

		size := utf8.RuneLen(r)
		if size <= 0 || b.Len()+size > maxBytes {
			break
		}

		b.WriteRune(r)
	}

	return strings.Join(strings.Fields(b.String()), " ")
}

func normalizeStringList(
	values []string,
	maxItems int,
	maxBytes int,
) ([]string, error) {
	if len(values) > maxItems {
		return nil, fmt.Errorf("exceeds the limit of %d items", maxItems)
	}

	result := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))

	for i, raw := range values {
		value := cleanIntegrationText(raw, maxBytes)
		if value == "" {
			return nil, fmt.Errorf("item %d is empty or invalid", i+1)
		}

		key := strings.ToLower(value)
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}
		result = append(result, value)
	}

	return result, nil
}

func renderIntegrationList(values []string) string {
	if len(values) == 0 {
		return "- Not specified; determine this during engineering review."
	}

	var b strings.Builder
	for _, value := range values {
		fmt.Fprintf(&b, "- %s\n", value)
	}
	return strings.TrimSpace(b.String())
}

func writeHardwareField(b *strings.Builder, label, value string) {
	if strings.TrimSpace(value) == "" {
		fmt.Fprintf(b, "**%s:** Not specified; verify before implementation.\n\n", label)
		return
	}
	fmt.Fprintf(b, "**%s:** %s\n\n", label, value)
}

func goStringSlice(values []string) string {
	var b strings.Builder
	for i, value := range values {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(strconv.Quote(value))
	}
	return b.String()
}

func minHardwareInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
