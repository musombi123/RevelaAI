// Package inventory provides bounded, read-only host and package metadata
// collection for the Revela USB Field Engine.
package inventory

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"
)

const MaxPackageInventoryBytes = 16 << 20

type PackageRecord struct {
	Ecosystem string `json:"ecosystem"`
	Name string `json:"name"`
	Version string `json:"version"`
	PackageURL string `json:"package_url"`
	Architecture string `json:"architecture,omitempty"`
	Publisher string `json:"publisher,omitempty"`
}

type PackageSnapshot struct {
	GeneratedAt time.Time `json:"generated_at"`
	Source string `json:"source"`
	Packages []PackageRecord `json:"packages"`
	Skipped int `json:"skipped"`
	Warnings []string `json:"warnings"`
}

func purlSegment(value string) string {
	return url.PathEscape(strings.TrimSpace(value))
}

func genericPURL(publisher, name string) string {
	if strings.TrimSpace(publisher) != "" {
		return "pkg:generic/" + purlSegment(publisher) + "/" + purlSegment(name)
	}
	return "pkg:generic/" + purlSegment(name)
}

func distroPURL(distro, name, distroVersion, arch string) string {
	qualifiers := []string{}
	if strings.TrimSpace(arch) != "" {
		qualifiers = append(qualifiers, "arch="+url.QueryEscape(strings.TrimSpace(arch)))
	}
	if strings.TrimSpace(distro) != "" {
		distroValue := strings.TrimSpace(distro)
		if strings.TrimSpace(distroVersion) != "" { distroValue += "-" + strings.TrimSpace(distroVersion) }
		qualifiers = append(qualifiers, "distro="+url.QueryEscape(distroValue))
	}
	purl := "pkg:deb/" + purlSegment(distro) + "/" + purlSegment(name)
	if len(qualifiers) > 0 { purl += "?" + strings.Join(qualifiers, "&") }
	return purl
}

func rpmPURL(name, arch, distro, distroVersion string) string {
	qualifiers := []string{}
	if strings.TrimSpace(arch) != "" {
		qualifiers = append(qualifiers, "arch="+url.QueryEscape(strings.TrimSpace(arch)))
	}
	if strings.TrimSpace(distro) != "" {
		distroValue := strings.TrimSpace(distro)
		if strings.TrimSpace(distroVersion) != "" { distroValue += "-" + strings.TrimSpace(distroVersion) }
		qualifiers = append(qualifiers, "distro="+url.QueryEscape(distroValue))
	}
	purl := "pkg:rpm/" + purlSegment(name)
	if len(qualifiers) > 0 { purl += "?" + strings.Join(qualifiers, "&") }
	return purl
}

func parseDpkgOutput(data []byte, distro, distroVersion string) ([]PackageRecord, int, error) {
	if len(data) > MaxPackageInventoryBytes {
		return nil, 0, errors.New("dpkg package listing exceeds the 16 MiB limit")
	}
	records := []PackageRecord{}
	skipped := 0
	seen := map[string]struct{}{}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" { continue }
		fields := strings.Split(line, "\t")
		if len(fields) != 3 {
			skipped++
			continue
		}
		name := strings.TrimSpace(fields[0])
		version := strings.TrimSpace(fields[1])
		arch := strings.TrimSpace(fields[2])
		if colon := strings.LastIndex(name, ":"); colon > 0 {
			name = name[:colon]
		}
		if name == "" || version == "" || arch == "" || strings.ContainsAny(name+version+arch, "\r\x00") {
			skipped++
			continue
		}
		purl := distroPURL(distro, name, distroVersion, arch)
		key := purl + "|" + version
		if _, ok := seen[key]; ok { continue }
		seen[key] = struct{}{}
		records = append(records, PackageRecord{Ecosystem: "deb", Name: name, Version: version, PackageURL: purl, Architecture: arch})
	}
	if len(records) == 0 {
		return nil, skipped, errors.New("dpkg-query returned no parseable installed packages")
	}
	return records, skipped, nil
}

func parseRPMOutput(data []byte, distro, distroVersion string) ([]PackageRecord, int, error) {
	if len(data) > MaxPackageInventoryBytes {
		return nil, 0, errors.New("rpm package listing exceeds the 16 MiB limit")
	}
	records := []PackageRecord{}
	skipped := 0
	seen := map[string]struct{}{}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" { continue }
		fields := strings.Split(line, "\t")
		if len(fields) != 3 {
			skipped++
			continue
		}
		name := strings.TrimSpace(fields[0])
		version := strings.TrimSpace(fields[1])
		arch := strings.TrimSpace(fields[2])
		if name == "" || version == "" || arch == "" || strings.ContainsAny(name+version+arch, "\r\x00") {
			skipped++
			continue
		}
		purl := rpmPURL(name, arch, distro, distroVersion)
		key := purl + "|" + version
		if _, ok := seen[key]; ok { continue }
		seen[key] = struct{}{}
		records = append(records, PackageRecord{Ecosystem: "rpm", Name: name, Version: version, PackageURL: purl, Architecture: arch})
	}
	if len(records) == 0 {
		return nil, skipped, errors.New("rpm query returned no parseable installed packages")
	}
	return records, skipped, nil
}

func parseWindowsRegistryOutput(data []byte) ([]PackageRecord, int) {
	records := []PackageRecord{}
	skipped := 0
	seen := map[string]struct{}{}
	current := map[string]string{}
	flush := func() {
		name := strings.TrimSpace(current["DisplayName"])
		version := strings.TrimSpace(current["DisplayVersion"])
		publisher := strings.TrimSpace(current["Publisher"])
		if name == "" || version == "" {
			if name != "" || version != "" { skipped++ }
			return
		}
		purl := genericPURL(publisher, name)
		key := purl + "|" + version
		if _, ok := seen[key]; ok { return }
		seen[key] = struct{}{}
		records = append(records, PackageRecord{Ecosystem: "generic", Name: name, Version: version, PackageURL: purl, Publisher: publisher})
	}
	for _, line := range strings.Split(string(data), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(strings.ToUpper(trimmed), "HKEY_") {
			flush()
			current = map[string]string{}
			continue
		}
		fields := strings.Fields(trimmed)
		if len(fields) < 3 { continue }
		fieldName := fields[0]
		if fieldName != "DisplayName" && fieldName != "DisplayVersion" && fieldName != "Publisher" { continue }
		typeIndex := strings.Index(trimmed, fields[1])
		if typeIndex < 0 { continue }
		current[fieldName] = strings.TrimSpace(trimmed[typeIndex+len(fields[1]):])
	}
	flush()
	return records, skipped
}

func validatePackageSnapshot(snapshot PackageSnapshot) error {
	if snapshot.GeneratedAt.IsZero() || strings.TrimSpace(snapshot.Source) == "" {
		return fmt.Errorf("package snapshot is missing provenance")
	}
	if len(snapshot.Packages) == 0 {
		return errors.New("no supported installed packages were discovered")
	}
	return nil
}
