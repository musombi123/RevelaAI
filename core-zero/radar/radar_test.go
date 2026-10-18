package radar

import "testing"

func TestThresholdAndSemverAreBothRequired(t *testing.T) {
	c,e:=Compare(Evidence{Name:"local",Version:"1.0.0",Benchmark:100},Evidence{Name:"new",Version:"1.1.0",Benchmark:131,Source:"offline-import",EvidenceID:"fixture-1"});if e!=nil{t.Fatal(e)};if !c.ExceedsThirtyPercent||c.Recommendation!="upgrade_candidate_for_human_review"||c.NetworkUsed{t.Fatalf("unexpected comparison: %#v",c)}
}
func TestBadSemverRejected(t *testing.T){if _,e:=CompareSemver("1.0","2.0.0");e==nil{t.Fatal("expected strict semver validation")}}
