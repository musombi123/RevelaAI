# AWAIT_MERGE — Core-Two v0.1.0 Sample Evolution

## 1. Proposal Status

- **Proposal:** `graph-indexed`
- **Version:** `v0.1.0`
- **Evidence fixture:** `offline-vault-graph-replay-v1`
- **Status:** `await_merge`
- **Approval state:** Pending explicit human approval
- **Activation state:** Not activated
- **Protected components:** Core-One and Core-Zero

This document defines the review requirements for the sample Core-Two evolution proposal.

Staging, benchmarking, generating candidate files, or passing candidate-template tests does not constitute authorization to install, execute, or merge the mutation.

Core-Two must not modify Core-One or Core-Zero automatically. Any eventual integration requires a separately reviewed change and explicit owner approval.

## 2. Required Review

### 2.1 Source and mutation review

Review the following artifacts line by line:

- `new_library.go`
- `rvx_protection.go`
- All candidate source files associated with `graph-indexed`
- The evolution-evidence record and benchmark fixture
- Candidate tests and generated artifacts
- Relevant configuration, dependency declarations, and integration points

Verify that the proposed mutation matches the recorded objective and that its source, tests, and evidence describe the same implementation.

Confirm that the changes do not bypass Guardian controls, silently change existing interfaces, introduce unauthorized dependencies, or modify protected Core-One/Core-Zero files.

Record the exact revisions reviewed. Do not approve a different revision based on an earlier review.

### 2.2 Isolated testing

Re-run the applicable tests in isolated CI using:

- A pinned Go version and documented build configuration
- No production credentials or production secrets
- An isolated working directory and temporary test data
- The repository's relevant unit, integration, and regression tests
- Explicit checks for malformed input, resource limits, failure handling, and compatibility

Record the actual commands, environment, test results, and reviewed source revision.

Candidate-template tests alone do not prove that repository-sourced code was executed correctly. Do not describe tests as passed unless their results have been observed and recorded.

The sample proposal does not establish that an operating-system-level sandbox exists. Do not claim sandbox isolation unless the CI configuration demonstrates it.

### 2.3 Historical replay

When sufficient historical receipts become available, replay at least five real historical inventions against a documented baseline and the reviewed candidate.

For each replay, record:

- A stable receipt or evidence identifier
- The baseline and candidate revisions
- Input and output validation results
- Timing methodology and measured results
- Failures, behavioral differences, and regression findings

Do not manufacture historical receipts or represent synthetic fixtures as historical inventions.

The inspected Core-One inventions directory contained no recorded historical invention evidence for this sample. Therefore, the required historical replay has not been established by the current evidence.

### 2.4 Benchmark verification

The reported fixture contains:

| Metric | Recorded value |
|---|---:|
| Nodes | 1,800 |
| Edges | 7,200 |
| Replay rounds | 5 |
| Baseline traversal time | 2,656,694 ns/round |
| Candidate traversal time | 421,937 ns/round |
| Reported improvement ratio | 6.30× |
| Reported speedup | 529.64% |

These figures represent one reported local synthetic graph-phase measurement. They are not a production benchmark.

Before accepting the result, verify the precise baseline implementation. The originally supplied `Reachable` implementation already uses a map-backed visited-node set, so the assertion that the mutation replaces repeated linear membership scans must be reconciled with the actual benchmark source.

Preserve raw benchmark output and the exact command used. Document the machine, Go version, source revisions, and repetition methodology when available.

Do not claim an end-to-end invention-time improvement, production-wide speedup, or statistically stable performance gain based on these fixture measurements alone.

### 2.5 BOM and supplier verification

No real currency prices are established by the synthetic graph fixture.

Before claiming savings in Kenyan shillings (KES), obtain verifiable, dated bills of materials and supplier quotations for the relevant products or components.

Record quantities, unit prices, currency, quotation dates, supplier identity, applicable taxes and delivery costs where relevant, and the assumptions used in the comparison.

Keep unverified values unknown. Do not turn missing prices into zero-cost estimates or present hypothetical savings as measured savings.

### 2.6 Guardian and compliance review

The inspected baseline reportedly lacked:

`core-zero/guardian/rules.yaml`

The Core-Zero maintainer must review this finding and determine the appropriate policy configuration and remediation. Verify the actual current repository state before concluding that the file remains absent.

Do not bypass existing Guardian controls or weaken safeguards to allow the candidate to pass.

Before making legal or regulatory compliance claims, obtain appropriately qualified review of the applicable Kenyan legal framework, relevant Kenya Bureau of Standards (KEBS) requirements, and data-protection obligations.

A configuration review, passing test, or successful local demonstration does not independently establish legal or regulatory compliance.

Record the scope, reviewer qualifications, findings, and unresolved conditions. Do not claim formal approval where none has been documented.

### 2.7 RVX security review

Review the RVX encryption proposal independently from the graph-indexing benchmark.

The stated proposal uses AES-256-GCM with an external key. Review at least:

- Key generation, custody, storage, and access controls
- Key rotation and versioning
- Backup, recovery, and loss-of-key behavior
- Nonce generation and uniqueness requirements
- Authentication-failure handling
- Compatibility and migration between envelope versions
- Tamper-detection tests and their actual coverage
- Error handling, logging, and exposure of sensitive material

Encryption can provide confidentiality and integrity when implemented and operated correctly. It does not guarantee that software, source code, or all plaintext outputs are impossible to copy or reverse-engineer.

Do not issue a numeric security score or claim production security certification without a defined, supported assessment.

## 3. Evidence Boundary

The `offline_vault` fixture is a synthetic graph with 1,800 nodes and 7,200 edges, measuring the graph traversal phase only.

The benchmark is machine-dependent and does not demonstrate end-to-end invention performance.

The inspected baseline contained zero historical Core-One invention evidence records for this sample. The following values therefore remain unknown unless supported by new evidence:

- Historical production invention timing
- Production average invention time
- Verified KES bill-of-materials cost
- Verified cost savings
- Human review and merge time
- Production-scale performance and reliability

Synthetic results must remain labelled as synthetic. Missing production evidence is not proof of improvement or regression.

## 4. Explicit Merge Gate

The mutation must remain staged until the following conditions have been reviewed and resolved or explicitly accepted by the authorized owner:

1. Source and candidate-diff review is complete.
2. Relevant tests have been run in isolated CI, and results are recorded.
3. The benchmark methodology and baseline implementation have been verified.
4. Historical replay has been completed when the required receipts exist, or its absence is explicitly documented as an outstanding condition.
5. BOM and supplier claims are supported by verifiable prices before any savings claim is made.
6. The Core-Zero Guardian finding has been reviewed by its maintainer.
7. Applicable legal, standards, and data-protection reviews have been obtained before compliance claims are made.
8. RVX key-management and compatibility risks have been reviewed.
9. The final candidate revision and all associated evidence are identifiable.
10. The authorized owner has recorded an explicit decision.

Approval must identify the approved revision, reviewer, decision, date, conditions, and any required follow-up.

Approval of one revision does not automatically authorize a different revision.

**Forbidden without separate explicit authorization:**

- Automatic installation
- Automatic execution of staged candidate code
- Automatic merge into Core-One
- Automatic modification of Core-Zero
- Implicit approval based only on test or benchmark success

If a required condition remains unresolved, keep the candidate staged and record the blocker rather than silently treating it as approved.

## 5. Human Decision Record

Complete this section only after the review has actually occurred.

- **Reviewed candidate revision:** Not recorded
- **Reviewer identity:** Not recorded
- **Review date:** Not recorded
- **CI run and results:** Not recorded
- **Benchmark verification:** Pending
- **Historical replay:** Not established
- **BOM verification:** Pending
- **Guardian review:** Pending
- **RVX security review:** Pending
- **Owner decision:** Pending
- **Decision reference:** Not recorded
- **Conditions or follow-up actions:** Not recorded

Permitted decision values:

- `pending`
- `approved`
- `approved_with_conditions`
- `rejected`
- `deferred`

Only an authorized human reviewer may record the actual decision. Do not change the decision to an approval value simply because the proposal is complete or its sample tests pass.

## 6. Final Status

**Current status: `await_merge`**

The `graph-indexed` proposal remains a review artifact. The available sample benchmark may justify further investigation, but production benefit has not been demonstrated by this evidence.

Core-One and Core-Zero remain outside the mutation's activation scope until a separately reviewed and explicitly approved integration takes place.
