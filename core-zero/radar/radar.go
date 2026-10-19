// Package radar is a deterministic, offline comparison engine.
//
// Radar compares supplied evidence only. It does not download candidates,
// verify external provenance, install upgrades, execute commands, or modify
// the system being evaluated. Recommendations always require human review.
package radar

import (
	"errors"
	"fmt"
	"math"
	"strings"
)

const (
	// RequiredBenchmarkImprovementRatio is the strict minimum ratio for
	// reporting a benchmark improvement greater than 30 percent.
	RequiredBenchmarkImprovementRatio = 1.30
)

type Evidence struct {
	Name       string  `json:"name"`
	Version    string  `json:"version"`
	Benchmark  float64 `json:"benchmark"`
	Source     string  `json:"source"`
	EvidenceID string  `json:"evidence_id"`
}

type Comparison struct {
	Current                Evidence `json:"current"`
	Candidate              Evidence `json:"candidate"`
	VersionOrder           int      `json:"version_order"`
	ImprovementRatio       float64  `json:"improvement_ratio"`
	ExceedsThirtyPercent   bool     `json:"exceeds_thirty_percent"`
	Recommendation         string   `json:"recommendation"`
	NetworkUsed            bool     `json:"network_used"`
	HumanApprovalRequired  bool     `json:"human_approval_required"`
}

type semanticVersion struct {
	major      string
	minor      string
	patch      string
	prerelease []string
}

// Compare compares two supplied evidence records.
//
// VersionOrder is:
//
//   -1: candidate version is older than current
//    0: versions have equal SemVer precedence
//    1: candidate version is newer than current
//
// ImprovementRatio is candidate.Benchmark / current.Benchmark.
// For example, 1.30 represents a 30 percent increase.
//
// The benchmark is assumed to be a metric where larger is better. This
// function cannot independently verify the metric, measurement conditions,
// source authenticity, or comparability of the supplied evidence.
//
// No recommendation from this function authorizes an upgrade.
func Compare(current, candidate Evidence) (Comparison, error) {
	if err := validateBenchmark("current", current.Benchmark, true); err != nil {
		return Comparison{}, err
	}

	if err := validateBenchmark("candidate", candidate.Benchmark, false); err != nil {
		return Comparison{}, err
	}

	order, err := CompareSemver(candidate.Version, current.Version)
	if err != nil {
		return Comparison{}, fmt.Errorf("compare evidence versions: %w", err)
	}

	ratio := candidate.Benchmark / current.Benchmark

	// Extremely large ratios can overflow float64; extremely small ratios
	// can underflow to zero. Neither should be reported as a precise result.
	if math.IsNaN(ratio) || math.IsInf(ratio, 0) {
		return Comparison{}, errors.New(
			"benchmark improvement ratio is outside the representable numeric range",
		)
	}
	if ratio == 0 && candidate.Benchmark > 0 {
		return Comparison{}, errors.New(
			"benchmark improvement ratio underflowed and cannot be represented reliably",
		)
	}

	improved := ratio > RequiredBenchmarkImprovementRatio

	result := Comparison{
		Current:               current,
		Candidate:             candidate,
		VersionOrder:          order,
		ImprovementRatio:      ratio,
		ExceedsThirtyPercent:  improved,
		Recommendation:        "no_upgrade_proposed",
		NetworkUsed:            false,
		HumanApprovalRequired: true,
	}

	switch {
	case order > 0 && improved:
		result.Recommendation = "upgrade_candidate_for_human_review"

	case improved:
		// The benchmark has improved significantly, but the candidate is
		// not semantically newer. This can indicate different builds,
		// measurement conditions, or inaccurate version metadata.
		result.Recommendation = "benchmark_improved_but_version_not_newer_review_metadata"

	case order > 0 && candidate.Benchmark < current.Benchmark:
		result.Recommendation = "newer_version_with_benchmark_regression_review_required"

	case order > 0:
		result.Recommendation = "newer_version_without_thirty_percent_benchmark_gain"

	case candidate.Benchmark > current.Benchmark:
		result.Recommendation = "benchmark_improved_but_version_not_newer_review_metadata"

	case candidate.Benchmark < current.Benchmark:
		result.Recommendation = "no_upgrade_proposed_benchmark_regression"

	default:
		result.Recommendation = "no_upgrade_proposed"
	}

	return result, nil
}

func validateBenchmark(name string, value float64, mustBePositive bool) error {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return fmt.Errorf("%s benchmark must be a finite number", name)
	}

	if mustBePositive && value <= 0 {
		return errors.New("current benchmark must be greater than zero")
	}

	if !mustBePositive && value < 0 {
		return errors.New("candidate benchmark must be non-negative")
	}

	return nil
}

// CompareSemver compares versions according to Semantic Versioning 2.0.0
// precedence. A lowercase "v" prefix is accepted for compatibility.
//
// Prerelease identifiers are compared correctly. Build metadata is ignored
// for precedence, as required by SemVer.
//
// Examples:
//
//	CompareSemver("1.2.0", "1.1.9")       -> 1
//	CompareSemver("1.0.0-rc.1", "1.0.0")  -> -1
//	CompareSemver("1.0.0+build.2", "1.0.0+build.1") -> 0
func CompareSemver(a, b string) (int, error) {
	left, err := parseSemver(a)
	if err != nil {
		return 0, fmt.Errorf("invalid first version %q: %w", a, err)
	}

	right, err := parseSemver(b)
	if err != nil {
		return 0, fmt.Errorf("invalid second version %q: %w", b, err)
	}

	return compareParsedSemver(left, right), nil
}

func parseSemver(input string) (semanticVersion, error) {
	var result semanticVersion

	version := strings.TrimSpace(input)
	if version == "" {
		return result, errors.New("version is empty")
	}

	// Accept a common lowercase v prefix, but do not treat arbitrary prefixes
	// or malformed versions as valid.
	if strings.HasPrefix(version, "v") {
		version = version[1:]
		if version == "" {
			return result, errors.New("version is empty after the v prefix")
		}
	}

	// Split optional build metadata.
	if strings.Count(version, "+") > 1 {
		return result, errors.New("multiple build-metadata separators")
	}

	coreAndPrerelease := version
	buildMetadata := ""

	if index := strings.IndexByte(version, '+'); index >= 0 {
		coreAndPrerelease = version[:index]
		buildMetadata = version[index+1:]

		if err := validateIdentifierList(buildMetadata, false); err != nil {
			return result, fmt.Errorf("invalid build metadata: %w", err)
		}
	}

	// Separate prerelease metadata from the three-part numeric version.
	core := coreAndPrerelease
	prerelease := ""

	if index := strings.IndexByte(coreAndPrerelease, '-'); index >= 0 {
		core = coreAndPrerelease[:index]
		prerelease = coreAndPrerelease[index+1:]

		if err := validateIdentifierList(prerelease, true); err != nil {
			return result, fmt.Errorf("invalid prerelease: %w", err)
		}

		result.prerelease = strings.Split(prerelease, ".")
	}

	parts := strings.Split(core, ".")
	if len(parts) != 3 {
		return semanticVersion{}, errors.New(
			"version must have exactly three numeric components: major.minor.patch",
		)
	}

	for i, part := range parts {
		if !validCoreNumber(part) {
			return semanticVersion{}, fmt.Errorf(
				"invalid numeric component %q",
				part,
			)
		}

		switch i {
		case 0:
			result.major = part
		case 1:
			result.minor = part
		case 2:
			result.patch = part
		}
	}

	return result, nil
}

func validCoreNumber(value string) bool {
	if value == "" {
		return false
	}

	if len(value) > 1 && value[0] == '0' {
		return false
	}

	for _, ch := range value {
		if ch < '0' || ch > '9' {
			return false
		}
	}

	return true
}

// validateIdentifierList validates dot-separated prerelease or build
// identifiers. Numeric prerelease identifiers cannot contain leading zeros;
// build identifiers may contain them.
func validateIdentifierList(value string, prerelease bool) error {
	if value == "" {
		return errors.New("identifier list is empty")
	}

	identifiers := strings.Split(value, ".")

	for _, identifier := range identifiers {
		if identifier == "" {
			return errors.New("empty identifier")
		}

		numeric := true

		for _, ch := range identifier {
			switch {
			case ch >= '0' && ch <= '9':
			case ch >= 'A' && ch <= 'Z':
				numeric = false
			case ch >= 'a' && ch <= 'z':
				numeric = false
			case ch == '-':
				numeric = false
			default:
				return fmt.Errorf("invalid character in identifier %q", identifier)
			}
		}

		if prerelease && numeric &&
			len(identifier) > 1 &&
			identifier[0] == '0' {
			return fmt.Errorf(
				"numeric prerelease identifier %q has a leading zero",
				identifier,
			)
		}
	}

	return nil
}

func compareParsedSemver(a, b semanticVersion) int {
	if order := compareNumericIdentifiers(a.major, b.major); order != 0 {
		return order
	}
	if order := compareNumericIdentifiers(a.minor, b.minor); order != 0 {
		return order
	}
	if order := compareNumericIdentifiers(a.patch, b.patch); order != 0 {
		return order
	}

	// A release version has higher precedence than its prerelease.
	if len(a.prerelease) == 0 && len(b.prerelease) == 0 {
		return 0
	}
	if len(a.prerelease) == 0 {
		return 1
	}
	if len(b.prerelease) == 0 {
		return -1
	}

	limit := len(a.prerelease)
	if len(b.prerelease) < limit {
		limit = len(b.prerelease)
	}

	for i := 0; i < limit; i++ {
		left := a.prerelease[i]
		right := b.prerelease[i]

		leftNumeric := isNumericIdentifier(left)
		rightNumeric := isNumericIdentifier(right)

		switch {
		case leftNumeric && rightNumeric:
			if order := compareNumericIdentifiers(left, right); order != 0 {
				return order
			}

		case leftNumeric && !rightNumeric:
			// Numeric prerelease identifiers have lower precedence.
			return -1

		case !leftNumeric && rightNumeric:
			return 1

		default:
			if order := strings.Compare(left, right); order != 0 {
				return order
			}
		}
	}

	// If every shared identifier matches, the shorter prerelease list
	// has lower precedence.
	switch {
	case len(a.prerelease) < len(b.prerelease):
		return -1
	case len(a.prerelease) > len(b.prerelease):
		return 1
	default:
		return 0
	}
}

func isNumericIdentifier(value string) bool {
	if value == "" {
		return false
	}

	for _, ch := range value {
		if ch < '0' || ch > '9' {
			return false
		}
	}

	return true
}

// compareNumericIdentifiers compares non-negative decimal strings without
// converting them to machine integers. This avoids overflow for large,
// otherwise-valid SemVer numeric components.
func compareNumericIdentifiers(a, b string) int {
	a = strings.TrimLeft(a, "0")
	b = strings.TrimLeft(b, "0")

	if a == "" {
		a = "0"
	}
	if b == "" {
		b = "0"
	}

	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	default:
		return strings.Compare(a, b)
	}
}
