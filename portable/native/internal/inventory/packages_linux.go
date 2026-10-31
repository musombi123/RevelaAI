//go:build linux

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

func readLinuxOSRelease() (id, version string) {
	data, err := os.ReadFile("/etc/os-release")
	if err != nil { return "linux", "" }
	for _, line := range strings.Split(string(data), "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok { continue }
		value = strings.Trim(strings.TrimSpace(value), "\"'")
		switch key {
		case "ID":
			id = value
		case "VERSION_ID":
			version = value
		}
	}
	if id == "" { id = "linux" }
	return id, version
}

func runPackageQuery(binary string, args ...string) ([]byte, error) {
	info, err := os.Stat(binary)
	if err != nil || info.IsDir() || info.Mode()&0111 == 0 {
		return nil, fmt.Errorf("package query tool is not executable: %s", binary)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, args...)
	var stdout, stderr boundedBuffer
	stdout.max = MaxPackageInventoryBytes
	stderr.max = 1 << 20
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s failed: %w", filepath.Base(binary), err)
	}
	return stdout.data, nil
}

// CollectInstalledPackages reads a local dpkg or RPM database. It does not
// invoke package installation tools, contact repositories or modify packages.
func CollectInstalledPackages() (PackageSnapshot, error) {
	distro, distroVersion := readLinuxOSRelease()
	now := time.Now().UTC()
	candidates := []struct{ binary, format string }{
		{"/usr/bin/dpkg-query", "dpkg"},
		{"/bin/dpkg-query", "dpkg"},
		{"/usr/bin/rpm", "rpm"},
		{"/bin/rpm", "rpm"},
	}
	for _, item := range candidates {
		if _, err := os.Stat(item.binary); err != nil { continue }
		var output []byte
		var err error
		if item.format == "dpkg" {
			output, err = runPackageQuery(item.binary, "-W", "-f=${binary:Package}\\t${Version}\\t${Architecture}\\n")
		} else {
			output, err = runPackageQuery(item.binary, "-qa", "--qf", "%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{ARCH}\\n")
		}
		if err != nil { return PackageSnapshot{}, err }
		var packages []PackageRecord
		var skipped int
		if item.format == "dpkg" {
			packages, skipped, err = parseDpkgOutput(output, distro, distroVersion)
		} else {
			packages, skipped, err = parseRPMOutput(output, distro, distroVersion)
		}
		if err != nil { return PackageSnapshot{}, err }
		snapshot := PackageSnapshot{
			GeneratedAt: now,
			Source: item.format + " local installed-package database (" + distro + ")",
			Packages: packages,
			Skipped: skipped,
			Warnings: []string{"Read-only package metadata only. This inventory excludes portable applications, software copied outside the package manager and other language-specific environments."},
		}
		return snapshot, validatePackageSnapshot(snapshot)
	}
	return PackageSnapshot{}, errors.New("no supported local package database found (supported: dpkg-query, rpm)")
}
