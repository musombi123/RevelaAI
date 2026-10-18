// Package bridge describes explicit adapters; it does not connect to devices or execute drivers.
package bridge

import (
	"errors"
	"strings"
)

type Plan struct {
	Target string `json:"target"`
	Status string `json:"status"`
	RuntimeAdapterPresent bool `json:"runtime_adapter_present"`
	AllowedOperations []string `json:"allowed_operations"`
	RequiredApprovals []string `json:"required_approvals"`
	NetworkOrDeviceAccessed bool `json:"network_or_device_accessed"`
	Note string `json:"note"`
}

var targets = map[string][]string{"ros2": {"emit_ros2_package_scaffold", "mock_contract_tests"}, "fpga": {"emit_verilog_module_scaffold", "lint_before_synthesis"}, "labview": {"emit_driver_contract", "manual_labview_project_generation"}, "device": {"inventory_usb_bluetooth_only_after_explicit_local_permission", "read_only_identity_probe"}}

func BuildPlan(target string) (Plan, error) {
	t := strings.ToLower(strings.TrimSpace(target))
	ops, ok := targets[t]
	if !ok { return Plan{}, errors.New("unsupported bridge target; use ros2, fpga, labview, or device") }
	return Plan{Target: t, Status: "adapter_scaffold_required", RuntimeAdapterPresent: false, AllowedOperations: ops, RequiredApprovals: []string{"review adapter manifest", "verify least-privilege device/API scope", "run mock contract tests", "approve any physical action separately"}, NetworkOrDeviceAccessed: false, Note: "This is a plan only. No ROS node, FPGA bitstream, LabVIEW driver, USB or Bluetooth device was opened or changed."}, nil
}
