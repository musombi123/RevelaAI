//go:build windows

package inventory

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const maxRegistryOutput = MaxPackageInventoryBytes


func queryRegistry(regExe, key string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, regExe, "query", key, "/s")
	var stdout boundedBuffer
	stdout.max = maxRegistryOutput
	cmd.Stdout = &stdout
	stderr := &boundedBuffer{max: 1 << 20}
	cmd.Stderr = stderr
	// Absent HKCU/WOW6432Node trees are normal on some Windows installations.
	if err := cmd.Run(); err != nil {
		if len(stdout.data) == 0 { return nil, nil }
		return nil, fmt.Errorf("registry query for %s failed: %w", key, err)
	}
	return stdout.data, nil
}

// CollectInstalledPackages reads conventional Windows uninstall registry keys.
// It does not inspect user documents, browser profiles, passwords or tokens.
func CollectInstalledPackages() (PackageSnapshot, error) {
	systemRoot := strings.TrimSpace(os.Getenv("SystemRoot"))
	if systemRoot == "" { return PackageSnapshot{}, errors.New("SystemRoot is unavailable") }
	regExe := filepath.Join(systemRoot, "System32", "reg.exe")
	if info, err := os.Stat(regExe); err != nil || info.IsDir() {
		return PackageSnapshot{}, errors.New("Windows reg.exe was not found")
	}
	keys := []string{
		"HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
		"HKEY_LOCAL_MACHINE\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
		"HKEY_CURRENT_USER\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
	}
	all := []byte{}
	warnings := []string{}
	for _, key := range keys {
		data, err := queryRegistry(regExe, key)
		if err != nil {
			warnings = append(warnings, err.Error())
			continue
		}
		if len(all)+len(data) > maxRegistryOutput {
			return PackageSnapshot{}, errors.New("combined Windows registry package listing exceeds 16 MiB")
		}
		all = append(all, data...)
	}
	packages, skipped := parseWindowsRegistryOutput(all)
	snapshot := PackageSnapshot{
		GeneratedAt: time.Now().UTC(),
		Source: "Windows uninstall registry (HKLM, WOW6432Node, HKCU)",
		Packages: packages,
		Skipped: skipped,
		Warnings: append(warnings, "Registry inventory is limited to conventional uninstall entries. Portable applications, per-user package managers, drivers and software outside these keys may be absent."),
	}
	return snapshot, validatePackageSnapshot(snapshot)
}
