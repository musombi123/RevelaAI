package radar

import (
	"math"
	"testing"
)

func TestThresholdAndSemverAreBothRequired(t *testing.T) {
	comparison, err := Compare(
		Evidence{
			Name:      "local",
			Version:   "1.0.0",
			Benchmark: 100,
			Source:    "offline-fixture",
			EvidenceID: "current-1",
		},
		Evidence{
			Name:       "candidate",
			Version:    "1.1.0",
			Benchmark:  131,
			Source:     "offline-import",
			EvidenceID: "fixture-1",
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	if !comparison.ExceedsThirtyPercent {
		t.Fatal("131/100 should exceed the 30% improvement threshold")
	}
	if comparison.Recommendation != "upgrade_candidate_for_human_review" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
	if comparison.VersionOrder != 1 {
		t.Fatalf("expected newer candidate, got version_order=%d", comparison.VersionOrder)
	}
	if math.Abs(comparison.ImprovementRatio-1.31) > 1e-12 {
		t.Fatalf("unexpected improvement ratio: %v", comparison.ImprovementRatio)
	}
	if comparison.NetworkUsed {
		t.Fatal("offline comparison must not use the network")
	}
	if !comparison.HumanApprovalRequired {
		t.Fatal("candidate must require human approval")
	}
}

func TestExactlyThirtyPercentDoesNotExceedStrictThreshold(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.1.0", Benchmark: 130},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.ExceedsThirtyPercent {
		t.Fatal("exactly 30% improvement must not exceed a strict greater-than threshold")
	}
	if comparison.Recommendation != "newer_version_without_thirty_percent_benchmark_gain" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestBenchmarkBelowThresholdDoesNotProposeUpgrade(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.1.0", Benchmark: 129},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.ExceedsThirtyPercent {
		t.Fatal("29% improvement must not exceed the threshold")
	}
	if comparison.Recommendation != "newer_version_without_thirty_percent_benchmark_gain" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestOlderVersionWithLargeBenchmarkGainRequiresMetadataReview(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "2.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.9.0", Benchmark: 150},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.VersionOrder != -1 {
		t.Fatalf("expected older candidate, got %d", comparison.VersionOrder)
	}
	if !comparison.ExceedsThirtyPercent {
		t.Fatal("expected the large benchmark improvement to be detected")
	}
	if comparison.Recommendation != "benchmark_improved_but_version_not_newer_review_metadata" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestSameVersionWithLargeBenchmarkGainRequiresMetadataReview(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.2.3", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.2.3", Benchmark: 140},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.VersionOrder != 0 {
		t.Fatalf("expected equal version precedence, got %d", comparison.VersionOrder)
	}
	if comparison.Recommendation != "benchmark_improved_but_version_not_newer_review_metadata" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestNewerVersionWithBenchmarkRegressionRequiresReview(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.1.0", Benchmark: 90},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.ExceedsThirtyPercent {
		t.Fatal("benchmark regression must not be reported as a large improvement")
	}
	if comparison.Recommendation != "newer_version_with_benchmark_regression_review_required" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestEqualBenchmarkAndVersionMakesNoUpgradeProposal(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.0.0", Benchmark: 100},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.ImprovementRatio != 1 {
		t.Fatalf("expected ratio 1, got %v", comparison.ImprovementRatio)
	}
	if comparison.ExceedsThirtyPercent {
		t.Fatal("equal benchmarks cannot exceed the improvement threshold")
	}
	if comparison.Recommendation != "no_upgrade_proposed" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestCandidateBenchmarkMayBeZero(t *testing.T) {
	comparison, err := Compare(
		Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
		Evidence{Name: "candidate", Version: "1.1.0", Benchmark: 0},
	)
	if err != nil {
		t.Fatal(err)
	}

	if comparison.ImprovementRatio != 0 {
		t.Fatalf("expected zero ratio, got %v", comparison.ImprovementRatio)
	}
	if comparison.Recommendation != "newer_version_with_benchmark_regression_review_required" {
		t.Fatalf("unexpected recommendation: %q", comparison.Recommendation)
	}
}

func TestInvalidCurrentBenchmarkIsRejected(t *testing.T) {
	tests := []struct {
		name      string
		benchmark float64
	}{
		{name: "zero", benchmark: 0},
		{name: "negative", benchmark: -1},
		{name: "NaN", benchmark: math.NaN()},
		{name: "positive infinity", benchmark: math.Inf(1)},
		{name: "negative infinity", benchmark: math.Inf(-1)},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := Compare(
				Evidence{Name: "current", Version: "1.0.0", Benchmark: test.benchmark},
				Evidence{Name: "candidate", Version: "1.1.0", Benchmark: 100},
			)
			if err == nil {
				t.Fatal("invalid current benchmark should be rejected")
			}
		})
	}
}

func TestInvalidCandidateBenchmarkIsRejected(t *testing.T) {
	tests := []struct {
		name      string
		benchmark float64
	}{
		{name: "negative", benchmark: -0.01},
		{name: "NaN", benchmark: math.NaN()},
		{name: "positive infinity", benchmark: math.Inf(1)},
		{name: "negative infinity", benchmark: math.Inf(-1)},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := Compare(
				Evidence{Name: "current", Version: "1.0.0", Benchmark: 100},
				Evidence{Name: "candidate", Version: "1.1.0", Benchmark: test.benchmark},
			)
			if err == nil {
				t.Fatal("invalid candidate benchmark should be rejected")
			}
		})
	}
}

func TestBenchmarkRatioOverflowIsRejected(t *testing.T) {
	_, err := Compare(
		Evidence{
			Name:      "current",
			Version:   "1.0.0",
			Benchmark: math.SmallestNonzeroFloat64,
		},
		Evidence{
			Name:      "candidate",
			Version:   "1.1.0",
			Benchmark: math.MaxFloat64,
		},
	)
	if err == nil {
		t.Fatal("overflowing benchmark ratio should be rejected")
	}
}

func TestBenchmarkRatioUnderflowIsRejected(t *testing.T) {
	_, err := Compare(
		Evidence{
			Name:      "current",
			Version:   "1.0.0",
			Benchmark: math.MaxFloat64,
		},
		Evidence{
			Name:      "candidate",
			Version:   "1.1.0",
			Benchmark: math.SmallestNonzeroFloat64,
		},
	)
	if err == nil {
		t.Fatal("underflowing nonzero benchmark ratio should be rejected")
	}
}

func TestComparisonAlwaysRequiresHumanApprovalAndUsesNoNetwork(t *testing.T) {
	comparisons := []struct {
		name      string
		current   Evidence
		candidate Evidence
	}{
		{
			name:      "upgrade candidate",
			current:   Evidence{Version: "1.0.0", Benchmark: 100},
			candidate: Evidence{Version: "1.1.0", Benchmark: 150},
		},
		{
			name:      "regression",
			current:   Evidence{Version: "1.0.0", Benchmark: 100},
			candidate: Evidence{Version: "1.1.0", Benchmark: 90},
		},
		{
			name:      "no upgrade",
			current:   Evidence{Version: "1.0.0", Benchmark: 100},
			candidate: Evidence{Version: "1.0.0", Benchmark: 100},
		},
	}

	for _, test := range comparisons {
		t.Run(test.name, func(t *testing.T) {
			result, err := Compare(test.current, test.candidate)
			if err != nil {
				t.Fatal(err)
			}

			if result.NetworkUsed {
				t.Fatal("Radar must not claim network use")
			}
			if !result.HumanApprovalRequired {
				t.Fatal("comparison must require human approval")
			}
		})
	}
}

func TestBadSemverRejected(t *testing.T) {
	if _, err := CompareSemver("1.0", "2.0.0"); err == nil {
		t.Fatal("expected strict SemVer validation")
	}
}

func TestInvalidSemverCasesRejected(t *testing.T) {
	invalid := []string{
		"",
		"1",
		"1.0",
		"1.0.0.0",
		"01.0.0",
		"1.01.0",
		"1.0.01",
		"v",
		"1.0.0-",
		"1.0.0+",
		"1.0.0-alpha..1",
		"1.0.0-01",
		"1.0.0-!invalid",
		"1.0.0+build..1",
		"1.0.0+build+extra",
		"1.0.x",
	}

	for _, version := range invalid {
		t.Run(version, func(t *testing.T) {
			if _, err := CompareSemver(version, "1.0.0"); err == nil {
				t.Fatalf("invalid SemVer version %q was accepted", version)
			}
		})
	}
}

func TestSemverCoreVersionOrdering(t *testing.T) {
	tests := []struct {
		name string
		a    string
		b    string
		want int
	}{
		{name: "major increase", a: "2.0.0", b: "1.9.9", want: 1},
		{name: "major decrease", a: "1.0.0", b: "2.0.0", want: -1},
		{name: "minor increase", a: "1.2.0", b: "1.1.9", want: 1},
		{name: "patch increase", a: "1.0.2", b: "1.0.1", want: 1},
		{name: "equal versions", a: "1.2.3", b: "1.2.3", want: 0},
		{name: "v prefix accepted", a: "v1.2.3", b: "1.2.2", want: 1},
		{name: "build metadata ignored", a: "1.2.3+build.2", b: "1.2.3+build.1", want: 0},
		{name: "large major numbers", a: "999999999999999999999.0.0", b: "999999999999999999998.0.0", want: 1},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := CompareSemver(test.a, test.b)
			if err != nil {
				t.Fatal(err)
			}
			if got != test.want {
				t.Fatalf("CompareSemver(%q, %q) = %d, want %d", test.a, test.b, got, test.want)
			}
		})
	}
}

func TestSemverPrereleaseOrdering(t *testing.T) {
	// Semantic Versioning 2.0.0 prerelease precedence examples.
	versions := []string{
		"1.0.0-alpha",
		"1.0.0-alpha.1",
		"1.0.0-alpha.beta",
		"1.0.0-beta",
		"1.0.0-beta.2",
		"1.0.0-beta.11",
		"1.0.0-rc.1",
		"1.0.0",
	}

	for i := 0; i < len(versions)-1; i++ {
		t.Run(versions[i]+"_before_"+versions[i+1], func(t *testing.T) {
			order, err := CompareSemver(versions[i], versions[i+1])
			if err != nil {
				t.Fatal(err)
			}
			if order != -1 {
				t.Fatalf("expected %q < %q, got comparison result %d", versions[i], versions[i+1], order)
			}
		})
	}
}

func TestSemverPrereleaseNumericIdentifiersCompareNumerically(t *testing.T) {
	tests := []struct {
		a    string
		b    string
		want int
	}{
		{a: "1.0.0-alpha.2", b: "1.0.0-alpha.10", want: -1},
		{a: "1.0.0-alpha.10", b: "1.0.0-alpha.2", want: 1},
		{a: "1.0.0-alpha.2", b: "1.0.0-alpha.2", want: 0},
		{a: "1.0.0-2", b: "1.0.0-alpha", want: -1},
		{a: "1.0.0-alpha", b: "1.0.0-2", want: 1},
	}

	for _, test := range tests {
		t.Run(test.a+"_vs_"+test.b, func(t *testing.T) {
			got, err := CompareSemver(test.a, test.b)
			if err != nil {
				t.Fatal(err)
			}
			if got != test.want {
				t.Fatalf("got %d, want %d", got, test.want)
			}
		})
	}
}
