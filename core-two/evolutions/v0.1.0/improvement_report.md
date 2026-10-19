# Core-Two Improvement Report — v0.1.1

## 1. Proposal Identity

- **Candidate ID:** `graph-indexed`
- **Proposal version:** `0.1.1`
- **Status:** Staged for explicit human review and merge approval.
- **Scope:** Core-Two graph-indexing optimization.
- **Protected components:** Core-One and Core-Zero remain untouched.
- **Activation:** Not authorized by this report.
- **Authority:** A human reviewer must approve any merge or activation.

This document records a sample performance result and its limitations. It does not certify production readiness or authorize automatic installation, execution, or merging.

## 2. Proposed Improvement

The selected mutation is `graph-indexed`, a proposal to improve graph traversal by indexing graph relationships and tracking visited nodes efficiently.

The candidate introduces graph-indexing capabilities, including:

- Breadth-first reachability traversal.
- An indexed representation of graph nodes and edges.
- Reverse-edge lookup for predecessor queries.
- Shortest-path discovery.
- Validation and bounded graph inputs.

These capabilities remain proposal-level until the implementation is reviewed, tested, and explicitly approved.

### Implementation consistency check

The originally supplied `Reachable` implementation already uses a map-backed visited-node set. Therefore, the description of the optimization as “replacing repeated linear membership scans” must be verified against the exact baseline implementation used in the benchmark.

Before accepting the performance claim, the reviewer should identify the baseline revision and confirm that the measured baseline and candidate correspond to the implementations being compared.

## 3. Benchmark Evidence

**Fixture:** `offline_vault`

| Measurement | Recorded value |
|---|---:|
| Synthetic graph nodes | 1,800 |
| Synthetic graph edges | 7,200 |
| Replay rounds | 5 |
| Baseline graph-phase time | 2,656,694 ns/round |
| Indexed candidate graph-phase time | 421,937 ns/round |
| Reported throughput ratio | 6.30× |

The recorded measurements show a substantially lower graph-phase time for the indexed candidate in one local run.

Based on the two recorded timings, the candidate's graph-phase time was approximately **84.1% lower** than the baseline in that run.

### What the result establishes

The result is evidence of a potential graph-phase performance improvement for this specific synthetic fixture and local execution.

### What the result does not establish

The result does not establish:

- A 6.30× improvement in end-to-end invention generation.
- A production-wide performance improvement.
- Performance across different graph sizes or topologies.
- Production reliability, correctness, or scalability.
- Financial savings or a verified cost reduction.
- A statistically stable speedup across repeated independent runs.

The reported ratio must remain associated with this fixture and local run.

## 4. Reproducibility Requirements

The following information was not supplied in the sample report and must not be assumed:

- Machine specifications and operating system.
- Go version and relevant build configuration.
- Exact baseline and candidate revisions or source hashes.
- Benchmark command and benchmark source.
- Warm-up and repetition methodology.
- Raw measurements across independent runs.
- Measurement variability or confidence intervals.

A future benchmark report should include these details where available, along with the raw output and an exact procedure for reproducing the comparison.

The recorded five replay rounds must not be interpreted as five independent benchmark runs unless the benchmark implementation confirms that they were independent.

## 5. Production Evidence and Unknowns

The inspected baseline contained **zero historical invention evidence records**.

Consequently, the following remain unknown or unverified:

| Evidence area | Status |
|---|---|
| Historical invention performance | Unknown |
| Production timing improvement | Unknown |
| KES bill-of-materials cost | Unknown |
| Human review and merge time | Unknown |
| Production-scale reliability | Unverified |
| Independent benchmark reproduction | Not supplied |

Missing evidence is not proof of either success or failure. These values must remain unknown until supported by actual measurements or records.

Synthetic benchmark data must not be presented as historical production evidence.

## 6. Guardian Review Gap

The inspected baseline did not contain:

`core-zero/guardian/rules.yaml`

This is a review finding about the inspected baseline, not a claim that the file is necessarily absent from every current working copy.

**Required action:** The responsible owner must review the Guardian configuration and determine the correct remediation before approving any dependent integration.

Until that review is complete, this finding remains unresolved. The report does not authorize bypassing Guardian checks or weakening existing safeguards.

## 7. RVX Security Boundary

RVX is proposed as an authenticated-encryption envelope using AES-GCM to provide confidentiality and integrity for protected data.

The security claim is limited to the properties of the implemented cryptographic mechanism and its correct use. It does not mean software is literally uncopyable, that source code cannot be inspected, or that a distributed application cannot be reverse-engineered.

Before any integration, review key derivation, key storage, nonce handling, authentication-failure behavior, compatibility, and relevant test coverage.

No claim of production security certification is made by this report.

## 8. Human Merge Gate

**Automatic installation, execution, and merging are prohibited by this proposal's approval boundary.**

Before a reviewer approves the mutation:

1. Read `AWAIT_MERGE.md` and follow its applicable review procedure.
2. Inspect the complete candidate diff and verify that Core-One and Core-Zero remain unchanged.
3. Confirm the benchmark source, baseline revision, candidate revision, and reported measurements.
4. Review tests, failure cases, graph-size limits, and compatibility with the target repository.
5. Resolve or explicitly accept the outstanding Guardian review finding.
6. Review the RVX security boundary separately from the graph-indexing performance claim.
7. Record the reviewer's identity, explicit decision, approved revision, and any conditions attached to approval.

A staged proposal is not an approved mutation. A benchmark result is not merge authorization.

If approval is denied or evidence is insufficient, retain the proposal in its staged state.

## 9. Final Assessment

`graph-indexed` has a promising local graph-phase measurement, but its production value remains unproven.

The next decision should depend on reproducible measurements, implementation consistency, repository tests, and explicit human review—not on the headline speedup alone.

**Final status:** Staged for review. No automatic activation authorized.
