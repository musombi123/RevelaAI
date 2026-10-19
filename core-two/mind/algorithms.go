package mind

import (
	"context"
	"fmt"
	"net/url"
	"runtime"
	"sort"
	"strings"
	"time"

	"revela-mind.local/core-two/rvx"
	"usect-zero.local/core-zero/radar"
)

const (
	minGraphBenchmarkRounds = 5
	maxGraphBenchmarkRounds = 25

	fixtureGraphNodes  = 1800
	fixtureGraphDegree = 4

	pathFixtureEntries      = 20000
	pathLookupBatch          = 20
	pathLookupBenchmarkRounds = 5
)

type graphBenchmark struct {
	FixtureID      string  `json:"fixture_id"`
	FixtureOnly    bool    `json:"fixture_only"`
	ReplayRounds   int     `json:"replay_rounds"`
	NodeCount      int     `json:"node_count"`
	EdgeCount      int     `json:"edge_count"`
	BaselineNS     int64   `json:"baseline_ns_per_round"`
	CandidateNS    int64   `json:"candidate_ns_per_round"`
	SpeedupPercent float64 `json:"speedup_percent"`
	Improvement    float64 `json:"improvement_ratio"`
	RadarDecision  string  `json:"zero_radar_decision"`
	Measurement    string  `json:"measurement_scope"`
}

type fixtureGraph map[int][]int

// makeFixtureGraph builds a deterministic synthetic directed graph.
// It does not access repositories, production data, or external services.
func makeFixtureGraph(nodes, degree int) fixtureGraph {
	g := make(fixtureGraph, nodes)

	if nodes < 1 || degree < 0 {
		return g
	}

	for n := 0; n < nodes; n++ {
		neighbors := make([]int, 0, degree)

		for e := 1; e <= degree; e++ {
			next := (n + e*37 + e*e + e) % nodes
			neighbors = append(neighbors, next)
		}

		g[n] = neighbors
	}

	return g
}

// traversalReference deliberately uses linear membership scanning.
// It serves as a benchmark reference, not necessarily the repository's
// historical or production traversal implementation.
func traversalReference(g fixtureGraph, start int) []int {
	q := []int{start}
	seen := []int{start}
	out := make([]int, 0, len(g))

	for head := 0; head < len(q); head++ {
		node := q[head]
		out = append(out, node)

		for _, next := range g[node] {
			found := false

			for _, old := range seen {
				if old == next {
					found = true
					break
				}
			}

			if !found {
				seen = append(seen, next)
				q = append(q, next)
			}
		}
	}

	return out
}

// traversalIndexed uses a map-backed visited set.
// Neighbor order is preserved so results can be compared with the reference.
func traversalIndexed(g fixtureGraph, start int) []int {
	q := []int{start}
	seen := map[int]struct{}{
		start: {},
	}
	out := make([]int, 0, len(g))

	for head := 0; head < len(q); head++ {
		node := q[head]
		out = append(out, node)

		for _, next := range g[node] {
			if _, exists := seen[next]; exists {
				continue
			}

			seen[next] = struct{}{}
			q = append(q, next)
		}
	}

	return out
}

// benchmarkOfflineVault compares the reference and indexed algorithms using
// warmed, alternating-order repetitions and median measured traversal times.
//
// This is a synthetic microbenchmark. It does not measure invention generation.
func benchmarkOfflineVault(
	ctx context.Context,
	rounds int,
) (graphBenchmark, error) {
	if ctx == nil {
		return graphBenchmark{}, fmt.Errorf("benchmark context must not be nil")
	}

	if err := ctx.Err(); err != nil {
		return graphBenchmark{}, err
	}

	if rounds < minGraphBenchmarkRounds {
		rounds = minGraphBenchmarkRounds
	}

	if rounds > maxGraphBenchmarkRounds {
		return graphBenchmark{}, fmt.Errorf(
			"benchmark rounds %d exceed limit %d",
			rounds,
			maxGraphBenchmarkRounds,
		)
	}

	g := makeFixtureGraph(fixtureGraphNodes, fixtureGraphDegree)

	// Warm both implementations and confirm that their traversal order agrees.
	for i := 0; i < 2; i++ {
		if err := ctx.Err(); err != nil {
			return graphBenchmark{}, err
		}

		reference := traversalReference(g, 0)
		indexed := traversalIndexed(g, 0)

		if !sameTraversal(reference, indexed) {
			return graphBenchmark{}, fmt.Errorf(
				"warm-up replay mismatch on iteration %d",
				i+1,
			)
		}
	}

	baselineSamples := make([]time.Duration, 0, rounds)
	candidateSamples := make([]time.Duration, 0, rounds)

	for i := 0; i < rounds; i++ {
		if err := ctx.Err(); err != nil {
			return graphBenchmark{}, err
		}

		// Keep garbage collection outside the timed region. The order of the
		// implementations alternates to reduce systematic ordering bias.
		runtime.GC()

		var referenceResult []int
		var indexedResult []int

		if i%2 == 0 {
			start := time.Now()
			referenceResult = traversalReference(g, 0)
			baselineSamples = append(
				baselineSamples,
				time.Since(start),
			)

			start = time.Now()
			indexedResult = traversalIndexed(g, 0)
			candidateSamples = append(
				candidateSamples,
				time.Since(start),
			)
		} else {
			start := time.Now()
			indexedResult = traversalIndexed(g, 0)
			candidateSamples = append(
				candidateSamples,
				time.Since(start),
			)

			start = time.Now()
			referenceResult = traversalReference(g, 0)
			baselineSamples = append(
				baselineSamples,
				time.Since(start),
			)
		}

		if !sameTraversal(referenceResult, indexedResult) {
			return graphBenchmark{}, fmt.Errorf(
				"traversal mismatch on replay round %d",
				i+1,
			)
		}
	}

	baselineNS := medianDuration(baselineSamples).Nanoseconds()
	candidateNS := medianDuration(candidateSamples).Nanoseconds()

	if baselineNS <= 0 || candidateNS <= 0 {
		return graphBenchmark{}, fmt.Errorf(
			"benchmark duration is too small to measure reliably",
		)
	}

	// Radar receives throughput values derived from the measured times.
	comparison, err := radar.Compare(
		radar.Evidence{
			Name:       "offline_vault_graph_traversal",
			Version:    "v0.1.0",
			Benchmark:  1e9 / float64(baselineNS),
			Source:     "synthetic fixture",
			EvidenceID: "offline-vault-baseline",
		},
		radar.Evidence{
			Name:       "offline_vault_graph_traversal",
			Version:    "v0.2.0",
			Benchmark:  1e9 / float64(candidateNS),
			Source:     "synthetic fixture",
			EvidenceID: "offline-vault-candidate",
		},
	)
	if err != nil {
		return graphBenchmark{}, fmt.Errorf(
			"compare graph benchmark evidence: %w",
			err,
		)
	}

	ratio := float64(baselineNS) / float64(candidateNS)

	edgeCount := 0
	for _, neighbors := range g {
		edgeCount += len(neighbors)
	}

	return graphBenchmark{
		FixtureID:      "offline-vault-graph-replay-v1",
		FixtureOnly:    true,
		ReplayRounds:   rounds,
		NodeCount:      len(g),
		EdgeCount:      edgeCount,
		BaselineNS:     baselineNS,
		CandidateNS:    candidateNS,
		SpeedupPercent: (ratio - 1) * 100,
		Improvement:    ratio,
		RadarDecision:  comparison.Recommendation,
		Measurement: "median of warmed, alternating-order repetitions; " +
			"synthetic graph traversal phase only; not end-to-end " +
			"invention time, verified BOM cost, or production performance",
	}, nil
}

func sameTraversal(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}

	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}

	return true
}

func medianDuration(values []time.Duration) time.Duration {
	if len(values) == 0 {
		return 0
	}

	sorted := append([]time.Duration(nil), values...)

	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i] < sorted[j]
	})

	return sorted[len(sorted)/2]
}

func evaluateCatalog(
	ctx context.Context,
) ([]CandidateEvaluation, graphBenchmark, error) {
	if ctx == nil {
		return nil, graphBenchmark{}, fmt.Errorf(
			"catalog evaluation context must not be nil",
		)
	}

	if err := ctx.Err(); err != nil {
		return nil, graphBenchmark{}, err
	}

	bench, err := benchmarkOfflineVault(ctx, minGraphBenchmarkRounds)
	if err != nil {
		return nil, graphBenchmark{}, err
	}

	protect, rvxNote := rvx.Probe()
	if !protect {
		return nil, bench, fmt.Errorf(
			"RVX artifact-protection probe failed: %s",
			rvxNote,
		)
	}

	// Synthetic comparison values only. These are not real supplier quotes,
	// verified market prices, or prices denominated in Kenyan shillings.
	quotes := []struct {
		supplier  string
		parts     float64
		transport float64
		stock     bool
	}{
		{
			supplier:  "fixture-supplier-a",
			parts:     1000,
			transport: 250,
			stock:     true,
		},
		{
			supplier:  "fixture-supplier-b",
			parts:     900,
			transport: 100,
			stock:     true,
		},
	}

	baselineCost := quotes[0].parts + quotes[0].transport
	bestCost := 0.0
	bestSupplier := ""

	for _, quote := range quotes {
		if !quote.stock {
			continue
		}

		cost := quote.parts + quote.transport
		if bestSupplier == "" || cost < bestCost {
			bestCost = cost
			bestSupplier = quote.supplier
		}
	}

	if bestSupplier == "" || baselineCost <= 0 {
		return nil, bench, fmt.Errorf(
			"synthetic BOM fixture has no valid stocked comparison",
		)
	}

	bomReductionPct := (baselineCost - bestCost) / baselineCost * 100

	sections := []string{
		"Prerequisites",
		"Parts",
		"Steps",
		"Verification",
		"Stop conditions",
	}

	shared := sharedStrings(
		[]string{"offline", "identity", "audit"},
		[]string{"offline", "audit", "agriculture", "education"},
	)

	dedupRows := []string{
		"source-a",
		"source-a",
		"source-b",
		"source-c",
		"source-c",
	}
	dedupCount := len(uniqueHashStrings(dedupRows))

	repeatedSpecs := []string{
		"spec-1",
		"spec-1",
		"spec-1",
		"spec-1",
		"spec-1",
	}
	cachedCount := len(uniqueStrings(repeatedSpecs))

	lookup := benchmarkPathLookup(ctx)
	if err := ctx.Err(); err != nil {
		return nil, bench, err
	}
	if !lookup.Passed {
		return nil, bench, fmt.Errorf(
			"path-index sandbox fixture failed",
		)
	}

	chainOK := auditChainProbe()
	boundedOK := boundedInputProbe()

	// ImprovementPct reports relative percentage changes only when the
	// baseline is positive. A zero baseline makes relative improvement
	// undefined; those controls retain a zero percentage and document
	// their absolute rubric result in Evidence and Note.
	evaluations := []CandidateEvaluation{
		{
			ID:              "graph-indexed",
			Category:        "graph_traversal",
			ImprovementType: "measured_speed",
			BaselineValue:   float64(bench.BaselineNS),
			CandidateValue:  float64(bench.CandidateNS),
			ImprovementPct:  bench.SpeedupPercent,
			Passed:          bench.Improvement > 1.30,
			MeasurementSource: "Synthetic offline_vault graph fixture; " +
				"five warmed measurement rounds",
			Evidence: map[string]any{
				"fixture_id":            bench.FixtureID,
				"fixture_only":          true,
				"baseline_ns_per_round": bench.BaselineNS,
				"candidate_ns_per_round": bench.CandidateNS,
				"throughput_ratio":      bench.Improvement,
				"production_speedup_verified": false,
			},
			Note: "Traversal microbenchmark only. Compare the exact " +
				"baseline revision before attributing this result to a " +
				"repository-level optimization.",
		},
		{
			ID:              "bom-cost-ranked",
			Category:        "bom_search",
			ImprovementType: "fixture_cost_reduction",
			BaselineValue:   baselineCost,
			CandidateValue:  bestCost,
			ImprovementPct:  bomReductionPct,
			Passed:          bomReductionPct > 0,
			MeasurementSource: "Synthetic fixture cost units; not KES " +
				"or verified supplier prices",
			Evidence: map[string]any{
				"currency":         "fixture_cost_units",
				"baseline_supplier": quotes[0].supplier,
				"candidate_supplier": bestSupplier,
				"baseline_cost":     baselineCost,
				"candidate_cost":    bestCost,
				"prices_verified":   false,
				"production_savings_verified": false,
			},
			Note: "Fixture arithmetic only. This is not a verified BOM " +
				"savings claim or evidence of a cheaper real supplier.",
		},
		{
			ID:              "hardware-guide-structured",
			Category:        "hardware_guide",
			ImprovementType: "safety_checklist_coverage",
			BaselineValue:   20,
			CandidateValue:  float64(len(sections)) / 5 * 100,
			// 20 -> 100 is a 400% relative increase, equivalent to an
			// 80-percentage-point increase on this synthetic score scale.
			ImprovementPct: 400,
			Passed:         len(sections) == 5,
			MeasurementSource: "Synthetic required-section checklist " +
				"fixture",
			Evidence: map[string]any{
				"required_sections": sections,
				"score_scale":       "fixture percentage",
				"checklist_is_compliance_certification": false,
			},
			Note: "Checklist-coverage fixture only; it does not establish " +
				"hardware safety certification or legal compliance.",
		},
		{
			ID:              "rvx-aead-envelope",
			Category:        "rvx_protection",
			ImprovementType: "artifact_protection_controls",
			BaselineValue:   0,
			CandidateValue:  40,
			ImprovementPct:  0,
			Passed:          protect,
			MeasurementSource: "RVX round-trip and tamper-detection probe; " +
				"scope depends on rvx.Probe implementation",
			Evidence: map[string]any{
				"probe": rvxNote,
				"candidate_score": 40,
				"score_unit": "rubric_points",
				"relative_improvement_from_zero_defined": false,
				"security_score_is_not_cryptographic_strength": true,
				"uncopyable_forever_claim": false,
			},
			Note: "Candidate score is 40 rubric points. Relative percentage " +
				"improvement from a zero baseline is undefined; this probe " +
				"does not certify production security.",
		},
		{
			ID:              "cross-industry-pollination",
			Category:        "pollination",
			ImprovementType: "cross_domain_reuse_count",
			BaselineValue:   1,
			CandidateValue:  float64(len(shared)),
			ImprovementPct:  float64(len(shared)-1) * 100,
			Passed:          len(shared) > 1,
			MeasurementSource: "Synthetic capability-set intersection " +
				"fixture",
			Evidence: map[string]any{
				"shared_capabilities": shared,
				"no_automatic_integration": true,
			},
			Note: "Counts overlap between two synthetic capability sets. " +
				"It does not demonstrate a successful real integration.",
		},
		{
			ID:              "evidence-hash-dedup",
			Category:        "evidence",
			ImprovementType: "duplicate_evidence_reduction",
			BaselineValue:   float64(len(dedupRows)),
			CandidateValue:  float64(dedupCount),
			ImprovementPct: float64(len(dedupRows)-dedupCount) /
				float64(len(dedupRows)) * 100,
			Passed: dedupCount == 3,
			MeasurementSource: "Five-row synthetic content-hash " +
				"deduplication fixture",
			Evidence: map[string]any{
				"input_records":  len(dedupRows),
				"unique_hashes":  dedupCount,
				"fixture_only":   true,
			},
			Note: "Uses hashes of synthetic strings. It does not establish " +
				"the quality or completeness of production evidence deduplication.",
		},
		{
			ID:              "canonical-spec-cache",
			Category:        "spec_cache",
			ImprovementType: "redundant_builds_avoided",
			BaselineValue:   float64(len(repeatedSpecs)),
			CandidateValue:  float64(cachedCount),
			ImprovementPct: float64(len(repeatedSpecs)-cachedCount) /
				float64(len(repeatedSpecs)) * 100,
			Passed: cachedCount == 1,
			MeasurementSource: "Repeated immutable-spec identifier fixture",
			Evidence: map[string]any{
				"input_specs":  len(repeatedSpecs),
				"unique_specs": cachedCount,
				"actual_builds_skipped_measured": false,
			},
			Note: "Measures unique identifiers in a fixture, not actual " +
				"build-cache performance or avoided production work.",
		},
		{
			ID:              "repository-path-index",
			Category:        "path_index",
			ImprovementType: "measured_lookup_speed",
			BaselineValue:   float64(lookup.BaselineNS),
			CandidateValue:  float64(lookup.CandidateNS),
			ImprovementPct:  lookup.ImprovementPct,
			Passed:          lookup.Passed && lookup.ImprovementPct > 0,
			MeasurementSource: "Synthetic lookup-only fixture with " +
				"20,000 prebuilt path entries",
			Evidence: map[string]any{
				"lookup_fixture_size": pathFixtureEntries,
				"lookups_per_round":   pathLookupBatch,
				"index_build_time_included": false,
			},
			Note: "Measures lookup time using an index built before timing. " +
				"It does not measure repository indexing or end-to-end costs.",
		},
		{
			ID:              "tamper-evident-audit-chain",
			Category:        "audit_integrity",
			ImprovementType: "tamper_detection",
			BaselineValue:   0,
			CandidateValue:  1,
			ImprovementPct:  0,
			Passed:          chainOK,
			MeasurementSource: "Synthetic audit-chain integrity fixture",
			Evidence: map[string]any{
				"tamper_detection_passed": chainOK,
				"relative_improvement_from_zero_defined": false,
			},
			Note: "Boolean integrity probe only. It is not a percentage " +
				"performance gain or proof of production audit security.",
		},
		{
			ID:              "bounded-input-guard",
			Category:        "input_safety",
			ImprovementType: "unsafe_input_rejection",
			BaselineValue:   0,
			CandidateValue:  1,
			ImprovementPct:  0,
			Passed:          boundedOK,
			MeasurementSource: "Synthetic oversized-input and path-traversal fixture",
			Evidence: map[string]any{
				"probe_passed": boundedOK,
				"candidate_code_execution": false,
				"relative_improvement_from_zero_defined": false,
			},
			Note: "Bounded-input regression probe only. This does not replace " +
				"canonical path resolution, authorization, or filesystem safeguards.",
		},
	}

	for i := range evaluations {
		if err := ctx.Err(); err != nil {
			return nil, bench, err
		}

		spec, ok := sourceFor(evaluations[i].ID)
		if !ok {
			return nil, bench, fmt.Errorf(
				"missing candidate template for %s",
				evaluations[i].ID,
			)
		}

		if err := validateCandidateSource(spec); err != nil {
			evaluations[i].Passed = false
			evaluations[i].Note = "candidate source validation failed: " +
				err.Error()
			continue
		}

		// SECURITY CONTRACT:
		// runCandidateTest must test only the authorized, isolated offline
		// candidate-template test harness. It must not execute generated
		// candidate payloads, access production credentials, or modify
		// Core-One/Core-Zero. Verify that helper's implementation separately.
		if err := runCandidateTest(ctx, spec); err != nil {
			evaluations[i].Passed = false
			evaluations[i].Note = "isolated candidate-template test failed: " +
				err.Error()
		}
	}

	if err := ctx.Err(); err != nil {
		return nil, bench, err
	}

	return evaluations, bench, nil
}

type lookupBenchmark struct {
	BaselineNS    int64
	CandidateNS   int64
	ImprovementPct float64
	Passed        bool
}

// benchmarkPathLookup measures repeated lookups after paths and the index
// have been built. Index construction is deliberately outside the timed scope.
func benchmarkPathLookup(ctx context.Context) lookupBenchmark {
	if ctx == nil || ctx.Err() != nil {
		return lookupBenchmark{}
	}

	paths := make([]string, pathFixtureEntries)
	index := make(map[string]int, pathFixtureEntries)

	for i := range paths {
		paths[i] = fmt.Sprintf("repo/module/file-%05d.go", i)
		index[paths[i]] = i
	}

	target := paths[len(paths)-1]

	baselineSamples := make([]time.Duration, 0, pathLookupBenchmarkRounds)
	candidateSamples := make([]time.Duration, 0, pathLookupBenchmarkRounds)

	expected := (pathFixtureEntries - 1) * pathLookupBatch

	for round := 0; round < pathLookupBenchmarkRounds; round++ {
		if err := ctx.Err(); err != nil {
			return lookupBenchmark{}
		}

		runtime.GC()

		var baselineChecksum int
		var candidateChecksum int

		if round%2 == 0 {
			start := time.Now()
			for attempt := 0; attempt < pathLookupBatch; attempt++ {
				baselineChecksum += linearPathLookup(paths, target)
			}
			baselineSamples = append(
				baselineSamples,
				time.Since(start),
			)

			start = time.Now()
			for attempt := 0; attempt < pathLookupBatch; attempt++ {
				candidateChecksum += indexedPathLookup(index, target)
			}
			candidateSamples = append(
				candidateSamples,
				time.Since(start),
			)
		} else {
			start := time.Now()
			for attempt := 0; attempt < pathLookupBatch; attempt++ {
				candidateChecksum += indexedPathLookup(index, target)
			}
			candidateSamples = append(
				candidateSamples,
				time.Since(start),
			)

			start = time.Now()
			for attempt := 0; attempt < pathLookupBatch; attempt++ {
				baselineChecksum += linearPathLookup(paths, target)
			}
			baselineSamples = append(
				baselineSamples,
				time.Since(start),
			)
		}

		if baselineChecksum != expected ||
			candidateChecksum != expected {
			return lookupBenchmark{}
		}
	}

	// Report median time per lookup, rather than timing a single map access.
	baselineNS := (medianDuration(baselineSamples) /
		time.Duration(pathLookupBatch)).Nanoseconds()
	candidateNS := (medianDuration(candidateSamples) /
		time.Duration(pathLookupBatch)).Nanoseconds()

	if baselineNS <= 0 || candidateNS <= 0 {
		return lookupBenchmark{}
	}

	return lookupBenchmark{
		BaselineNS:     baselineNS,
		CandidateNS:    candidateNS,
		ImprovementPct: (float64(baselineNS)/float64(candidateNS) - 1) * 100,
		Passed:         true,
	}
}

func linearPathLookup(paths []string, target string) int {
	for i, value := range paths {
		if value == target {
			return i
		}
	}

	return -1
}

func indexedPathLookup(index map[string]int, target string) int {
	value, ok := index[target]
	if !ok {
		return -1
	}

	return value
}

func sharedStrings(a, b []string) []string {
	set := make(map[string]bool, len(a))

	for _, value := range a {
		set[value] = true
	}

	out := make([]string, 0)
	seen := make(map[string]bool)

	for _, value := range b {
		if set[value] && !seen[value] {
			seen[value] = true
			out = append(out, value)
		}
	}

	sort.Strings(out)
	return out
}

func uniqueStrings(values []string) []string {
	seen := make(map[string]bool, len(values))
	out := make([]string, 0, len(values))

	for _, value := range values {
		value = strings.TrimSpace(value)

		if value == "" || seen[value] {
			continue
		}

		seen[value] = true
		out = append(out, value)
	}

	return out
}

// uniqueHashStrings deduplicates synthetic record content by hash rather
// than treating record IDs as if they were already content hashes.
func uniqueHashStrings(values []string) []string {
	seen := make(map[string]bool, len(values))
	out := make([]string, 0, len(values))

	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}

		hash := hashString(value)
		if seen[hash] {
			continue
		}

		seen[hash] = true
		out = append(out, hash)
	}

	return out
}

func auditChainProbe() bool {
	events := []string{
		"proposed",
		"tested",
		"await_merge",
	}

	hashes := make([]string, 0, len(events))
	previous := ""

	for _, entry := range events {
		previous = hashString(previous + "\n" + entry)
		hashes = append(hashes, previous)
	}

	return verifyHashChain(events, hashes) &&
		!verifyHashChain(
			[]string{"proposed", "tampered", "await_merge"},
			hashes,
		)
}

func boundedInputProbe() bool {
	return validBoundedInput("offline_vault") &&
		!validBoundedInput("../outside") &&
		!validBoundedInput("folder/%2e%2e/outside") &&
		!validBoundedInput("folder/%252e%252e/outside") &&
		!validBoundedInput(strings.Repeat("x", 4097))
}

// validBoundedInput is a bounded path-like input check. It is not a substitute
// for resolving paths against an allowed root and enforcing filesystem access.
func validBoundedInput(value string) bool {
	if value == "" ||
		len(value) > 4096 ||
		strings.TrimSpace(value) != value ||
		strings.ContainsRune(value, 0) {
		return false
	}

	clean := strings.ReplaceAll(value, "\\", "/")

	// Decode up to two layers to catch common encoded traversal attempts.
	// Malformed escapes fail closed.
	for i := 0; i < 2; i++ {
		decoded, err := url.PathUnescape(clean)
		if err != nil {
			return false
		}

		if decoded == clean {
			break
		}

		clean = strings.ReplaceAll(decoded, "\\", "/")

		if len(clean) > 4096 || strings.ContainsRune(clean, 0) {
			return false
		}
	}

	if strings.HasPrefix(clean, "/") ||
		(len(clean) >= 2 && clean[1] == ':') {
		return false
	}

	for _, part := range strings.Split(clean, "/") {
		if part == "." || part == ".." {
			return false
		}
	}

	return true
}

func verifyHashChain(events, hashes []string) bool {
	if len(events) != len(hashes) {
		return false
	}

	previous := ""

	for i, event := range events {
		previous = hashString(previous + "\n" + event)

		if hashes[i] != previous {
			return false
		}
	}

	return true
}
