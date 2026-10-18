package assemble

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRegisteredFixtureProducesReviewArtifacts(t *testing.T) {
	d := t.TempDir()
	r, e := Generate("esp32-sensor", d)
	if e != nil { t.Fatal(e) }
	if r.Status != "artifacts_generated_pending_review" || !r.HumanReviewRequired || len(r.Artifacts) != 5 { t.Fatalf("bad result: %#v",r) }
	for _, n := range []string{"bom.txt","wiring.svg","mount_plate.stl","flash.sh","README.md"} {
		b,e := os.ReadFile(filepath.Join(d,n)); if e != nil { t.Fatal(e) }; if len(strings.TrimSpace(string(b)))==0 { t.Fatalf("%s empty",n) }
	}
	script,_ := os.ReadFile(filepath.Join(d,"flash.sh")); if strings.Contains(string(script),"arduino-cli upload") { t.Fatal("stub must not flash hardware") }
}
func TestUnknownTargetDoesNotInventDesign(t *testing.T) { if _,e := Generate("unknown-robot",t.TempDir()); e==nil { t.Fatal("unknown target should require a curated template") } }
