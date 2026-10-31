package vulnfeed

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestParseCycloneDX17AndNormalizePackageURL(t *testing.T) {
	input := []byte(`{
		"bomFormat":"CycloneDX",
		"specVersion":"1.7",
		"metadata":{
			"timestamp":"2026-10-31T12:00:00Z",
			"tools":[{"vendor":"Example","name":"SBOM Builder","version":"2.0"}]
		},
		"components":[
			{"type":"library","name":"example-lib","version":"1.2.3","purl":"pkg:npm/example-lib@1.2.3"},
			{"type":"library","name":"@scope/lib","version":"4.0.0","purl":"pkg:npm/%40scope/lib@4.0.0?repository_url=https%3A%2F%2Fregistry.npmjs.org"},
			{"type":"library","name":"no-purl","version":"1.0.0"},
			{"type":"library","name":"nested","version":"2.0.0","purl":"pkg:golang/example.org/nested@v2.0.0","components":[
				{"type":"library","name":"child","version":"1.0.0","purl":"pkg:pypi/child@1.0.0"}
			]}
		]
	}`)
	result, err := ParseCycloneDXJSON(input)
	if err != nil { t.Fatal(err) }
	if len(result.Manifest.Packages) != 4 || result.Skipped != 1 {
		t.Fatalf("unexpected import result: packages=%d skipped=%d",len(result.Manifest.Packages),result.Skipped)
	}
	if result.Manifest.Packages[0].PackageURL != "pkg:npm/example-lib" {
		t.Fatalf("package version should be removed from purl: %+v",result.Manifest.Packages[0])
	}
	if result.Manifest.Packages[1].PackageURL != "pkg:npm/%40scope/lib?repository_url=https%3A%2F%2Fregistry.npmjs.org" {
		t.Fatalf("scoped purl/qualifier was not preserved: %+v",result.Manifest.Packages[1])
	}
	encoded, err := json.Marshal(result.Manifest)
	if err != nil { t.Fatal(err) }
	if _, err := ParseManifest(encoded); err != nil { t.Fatalf("imported manifest failed validation: %v",err) }
}

func TestParseCycloneDXRejectsUnsupportedVersionAndMissingTimestamp(t *testing.T) {
	if _,err:=ParseCycloneDXJSON([]byte(`{"bomFormat":"CycloneDX","specVersion":"1.3"}`));err==nil {
		t.Fatal("unsupported CycloneDX version must be rejected")
	}
	if _,err:=ParseCycloneDXJSON([]byte(`{"bomFormat":"CycloneDX","specVersion":"1.7","components":[{"purl":"pkg:npm/a@1.0.0","version":"1.0.0"}]}`));err==nil {
		t.Fatal("missing creation timestamp must be rejected")
	}
}

func TestParseSPDX23UsesOnlyExplicitPURLReferences(t *testing.T) {
	input:=[]byte(`{
		"spdxVersion":"SPDX-2.3",
		"name":"test document",
		"creationInfo":{"created":"2026-10-31T12:00:00Z","creators":["Tool: fixture"]},
		"packages":[
			{"name":"example","versionInfo":"1.2.3","externalRefs":[
				{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:npm/example@1.2.3"}
			]},
			{"name":"incomplete","versionInfo":"NOASSERTION","externalRefs":[]}
		]
	}`)
	result,err:=ParseSPDXJSON(input)
	if err!=nil {t.Fatal(err)}
	if len(result.Manifest.Packages)!=1 || result.Skipped!=1 {t.Fatalf("unexpected SPDX import: %+v",result)}
	if result.Manifest.Packages[0].PackageURL!="pkg:npm/example" {t.Fatalf("unexpected purl: %+v",result.Manifest.Packages[0])}
}

func TestNormalizePURLRejectsInvalidCoordinates(t *testing.T) {
	for _,value:=range []string{"https://example.org/pkg","pkg:","pkg:npm/example\n"} {
		if _,err:=NormalizePURL(value);err==nil {t.Errorf("expected invalid PURL rejection: %q",value)}
	}
}

func TestParseCycloneDX17StructuredToolsObject(t *testing.T) {
	input := []byte(`{
		"bomFormat":"CycloneDX",
		"specVersion":"1.7",
		"metadata":{
			"timestamp":"2026-10-31T12:00:00Z",
			"tools":{"components":[{"type":"application","name":"SBOM Builder","version":"3.0.0"}]}
		},
		"components":[
			{"type":"library","name":"example","version":"1.2.3","purl":"pkg:npm/example@1.2.3"}
		]
	}`)
	result, err := ParseCycloneDXJSON(input)
	if err != nil { t.Fatal(err) }
	if len(result.Manifest.Packages) != 1 {
		t.Fatalf("unexpected structured CycloneDX import: %+v", result)
	}
	if !strings.Contains(result.Manifest.Source, "SBOM Builder") {
		t.Fatalf("tool provenance missing from imported manifest source: %q", result.Manifest.Source)
	}
}
