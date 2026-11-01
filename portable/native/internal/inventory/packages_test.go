package inventory

import (
	"strings"
	"testing"
)

func TestParseDpkgOutputNormalizesBinaryPackageArchitecture(t *testing.T) {
	data := []byte("libssl3:amd64\t3.0.11-1~deb12u2\tamd64\nca-certificates\t20230311\tall\n")
	packages, skipped, err := parseDpkgOutput(data, "debian", "12")
	if err != nil { t.Fatal(err) }
	if skipped != 0 || len(packages) != 2 { t.Fatalf("unexpected dpkg parse: %+v skipped=%d", packages, skipped) }
	if packages[0].Name != "libssl3" || packages[0].PackageURL != "pkg:deb/debian/libssl3?arch=amd64&distro=debian-12" {
		t.Fatalf("unexpected Debian package coordinate: %+v", packages[0])
	}
}

func TestParseRPMOutputIncludesArchitectureAndDistro(t *testing.T) {
	data := []byte("openssl-libs\t3.2.2-1.el9\tx86_64\n")
	packages, skipped, err := parseRPMOutput(data, "rocky", "9.4")
	if err != nil { t.Fatal(err) }
	if skipped != 0 || len(packages) != 1 { t.Fatalf("unexpected RPM parse: %+v", packages) }
	if packages[0].PackageURL != "pkg:rpm/openssl-libs?arch=x86_64&distro=rocky-9.4" {
		t.Fatalf("unexpected RPM coordinate: %+v", packages[0])
	}
}

func TestParseWindowsRegistryOutputExtractsOnlySoftwareNameVersionPublisher(t *testing.T) {
	data := []byte(`HKEY_LOCAL_MACHINE\\SOFTWARE\\Vendor\\Product
    DisplayName    REG_SZ    Example Product
    DisplayVersion REG_SZ    4.2.1
    Publisher      REG_SZ    Example Vendor
    InstallLocation REG_SZ   C:\\Program Files\\Example

HKEY_CURRENT_USER\\SOFTWARE\\Other\\Tool
    DisplayName    REG_SZ    Other Tool
    DisplayVersion REG_SZ    1.0
`)
	packages, skipped := parseWindowsRegistryOutput(data)
	if skipped != 0 || len(packages) != 2 { t.Fatalf("unexpected registry parse: %+v skipped=%d", packages, skipped) }
	if packages[0].PackageURL != "pkg:generic/Example%20Vendor/Example%20Product" {
		t.Fatalf("unexpected generic purl: %+v", packages[0])
	}
	joined := packages[0].Name + packages[0].Version + packages[0].Publisher
	if strings.Contains(joined, "C:\\Program Files") { t.Fatal("install path must not be collected") }
}

func TestPackageParsersSkipMalformedRowsAndDeduplicate(t *testing.T) {
	data := []byte("demo\t1.0\tamd64\ndemo\t1.0\tamd64\nmalformed\n")
	packages, skipped, err := parseDpkgOutput(data, "ubuntu", "24.04")
	if err != nil { t.Fatal(err) }
	if len(packages) != 1 || skipped != 1 { t.Fatalf("unexpected parse counts: packages=%d skipped=%d", len(packages), skipped) }
}
