// Package bridge describes explicit, reviewable adapters.
//
// It creates declarative integration plans only. It does not connect to
// devices, open network connections, execute drivers, generate bitstreams,
// or perform physical actions.
package bridge

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	// StatusAdapterScaffoldRequired indicates that a target-specific adapter
	// must be implemented, reviewed, and tested before integration can occur.
	StatusAdapterScaffoldRequired = "adapter_scaffold_required"

	maxTargetInputBytes = 64
)

var (
	ErrUnsupportedTarget = errors.New(
		"unsupported bridge target; use ros2, fpga, labview, or device",
	)

	ErrInvalidTarget = errors.New(
		"bridge target is empty or invalid",
	)

	ErrInvalidPlan = errors.New(
		"bridge plan is invalid",
	)
)

// Plan describes a proposed integration without performing it.
//
// RuntimeAdapterPresent remains false until a real adapter is implemented
// and registered by a separate, explicitly approved integration subsystem.
//
// NetworkOrDeviceAccessed always remains false for plans produced here.
type Plan struct {
	Target                  string   `json:"target"`
	Status                  string   `json:"status"`
	RuntimeAdapterPresent   bool     `json:"runtime_adapter_present"`
	AllowedOperations       []string `json:"allowed_operations"`
	RequiredApprovals       []string `json:"required_approvals"`
	NetworkOrDeviceAccessed bool     `json:"network_or_device_accessed"`
	Note                    string   `json:"note"`
}

type targetSpec struct {
	operations  []string
	approvals   []string
	description string
}

// targetSpecs is the authoritative local registry of scaffold-level targets.
//
// Keep these operations descriptive and bounded. Adding an operation here
// does not implement or authorize an executable adapter.
var targetSpecs = map[string]targetSpec{
	"ros2": {
		operations: []string{
			"emit_ros2_package_scaffold",
			"mock_contract_tests",
		},
		approvals: []string{
			"review adapter manifest",
			"verify least-privilege device/API scope",
			"run mock contract tests",
			"approve any physical action separately",
		},
		description: "ROS 2 package scaffold and mock contracts only",
	},

	"fpga": {
		operations: []string{
			"emit_verilog_module_scaffold",
			"lint_before_synthesis",
		},
		approvals: []string{
			"review adapter manifest",
			"verify target FPGA and toolchain compatibility",
			"run HDL lint and mock contract tests",
			"review synthesis outputs before deployment",
			"approve hardware programming separately",
		},
		description: "Verilog scaffold and pre-synthesis lint planning only",
	},

	"labview": {
		operations: []string{
			"emit_driver_contract",
			"manual_labview_project_generation",
		},
		approvals: []string{
			"review adapter manifest",
			"verify least-privilege device/API scope",
			"review driver contracts and mock tests",
			"approve any physical action separately",
		},
		description: "Driver contracts and manual project-generation guidance only",
	},

	"device": {
		operations: []string{
			"inventory_usb_bluetooth_only_after_explicit_local_permission",
			"read_only_identity_probe",
		},
		approvals: []string{
			"review adapter manifest",
			"obtain explicit local user permission before device inventory",
			"verify device and operating-system permission boundaries",
			"confirm the identity probe is read-only",
			"approve any state-changing device operation separately",
		},
		description: "Potential local device inventory and read-only probing plan only",
	},
}

// BuildPlan creates a reviewable plan for a supported target.
//
// It does not execute the plan, initialize an adapter, or access a device
// or network. The caller must independently enforce authorization and
// human-approval requirements before any future integration is attempted.
func BuildPlan(target string) (Plan, error) {
	canonicalTarget, err := normalizeTarget(target)
	if err != nil {
		return Plan{}, err
	}

	spec, ok := targetSpecs[canonicalTarget]
	if !ok {
		return Plan{}, ErrUnsupportedTarget
	}

	// Copy each slice so callers cannot modify the definitions held in
	// targetSpecs by mutating the returned Plan.
	operations := cloneStrings(spec.operations)
	approvals := cloneStrings(spec.approvals)

	plan := Plan{
		Target:                  canonicalTarget,
		Status:                  StatusAdapterScaffoldRequired,
		RuntimeAdapterPresent:   false,
		AllowedOperations:       operations,
		RequiredApprovals:       approvals,
		NetworkOrDeviceAccessed: false,
		Note: fmt.Sprintf(
			"Plan only: %s. No adapter was executed or connected. No network or device was accessed. A separate, explicitly authorized implementation and approval process is required before any real operation.",
			spec.description,
		),
	}

	if err := ValidatePlan(plan); err != nil {
		return Plan{}, fmt.Errorf("internal bridge plan validation failed: %w", err)
	}

	return plan, nil
}

// SupportedTargets returns the supported target identifiers in sorted order.
//
// A new slice is returned on each call; modifying it does not affect the
// bridge registry.
func SupportedTargets() []string {
	result := make([]string, 0, len(targetSpecs))

	for target := range targetSpecs {
		result = append(result, target)
	}

	sort.Strings(result)
	return result
}

// ValidatePlan verifies that a plan corresponds to the current registered
// scaffold specification and retains the required safety properties.
//
// This validates the plan's structure and policy flags. It does not prove
// that a real-world adapter, if separately developed, is safe or correct.
func ValidatePlan(plan Plan) error {
	target, err := normalizeTarget(plan.Target)
	if err != nil {
		return fmt.Errorf("%w: invalid target", ErrInvalidPlan)
	}

	// Plans use canonical lowercase target identifiers.
	if plan.Target != target {
		return fmt.Errorf("%w: target is not canonical", ErrInvalidPlan)
	}

	spec, ok := targetSpecs[target]
	if !ok {
		return fmt.Errorf("%w: unsupported target %q", ErrInvalidPlan, target)
	}

	if plan.Status != StatusAdapterScaffoldRequired {
		return fmt.Errorf(
			"%w: unexpected status %q",
			ErrInvalidPlan,
			plan.Status,
		)
	}

	if plan.RuntimeAdapterPresent {
		return fmt.Errorf(
			"%w: scaffold-only plans cannot claim a runtime adapter",
			ErrInvalidPlan,
		)
	}

	if plan.NetworkOrDeviceAccessed {
		return fmt.Errorf(
			"%w: plan-only generation cannot claim network or device access",
			ErrInvalidPlan,
		)
	}

	if !equalStrings(plan.AllowedOperations, spec.operations) {
		return fmt.Errorf(
			"%w: operations do not match the registered target specification",
			ErrInvalidPlan,
		)
	}

	if !equalStrings(plan.RequiredApprovals, spec.approvals) {
		return fmt.Errorf(
			"%w: required approvals do not match the registered target specification",
			ErrInvalidPlan,
		)
	}

	if strings.TrimSpace(plan.Note) == "" {
		return fmt.Errorf("%w: explanatory note is required", ErrInvalidPlan)
	}

	if !utf8.ValidString(plan.Note) {
		return fmt.Errorf("%w: note is not valid UTF-8", ErrInvalidPlan)
	}

	return nil
}

func normalizeTarget(target string) (string, error) {
	if !utf8.ValidString(target) {
		return "", ErrInvalidTarget
	}

	if len(target) > maxTargetInputBytes {
		return "", ErrInvalidTarget
	}

	normalized := strings.ToLower(strings.TrimSpace(target))

	if normalized == "" {
		return "", ErrInvalidTarget
	}

	for _, r := range normalized {
		if unicode.IsControl(r) {
			return "", ErrInvalidTarget
		}
	}

	return normalized, nil
}

func cloneStrings(values []string) []string {
	if len(values) == 0 {
		return []string{}
	}

	result := make([]string, len(values))
	copy(result, values)
	return result
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}

	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}

	return true
}
