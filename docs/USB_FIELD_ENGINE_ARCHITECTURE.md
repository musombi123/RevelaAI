# RevelaAI USB Field Engine — architecture and integration contract

**Target:** USB Edition 0.3  
**Native runtime:** Go 1.23+ source, standard-library-only Field Engine  
**Decision model:** Guardian-first, read-only by default, proposal-first repairs  
**Offline requirement:** Core inspection and synthetic detection validation must work without Ollama or an internet connection.

## 1. Why this direction is industry-relevant

Revela should combine local system inspection, exposure assessment, threat-informed defence validation, forensic evidence handling and human-governed recovery. The product should not be described as a general-purpose exploit framework.

The design aligns to:
- MITRE ATT&CK for a shared vocabulary of observed adversary behaviour and detection coverage.
- NIST Cybersecurity Framework functions: Govern, Identify, Protect, Detect, Respond and Recover.
- Adversary simulation as a controlled way to test whether controls and response processes work.

Keep framework mappings versioned. The current ATT&CK catalogue as of 2026-10-31 is v20.0; do not hard-code unverified technique details or imply every ATT&CK technique has a safe simulator.

## 2. Core architecture

```text
USB / Local Host
  |
  +-- Revela Field Engine (Go, deterministic CLI)
  |     +-- Guardian policy gate
  |     +-- Host and network metadata inventory
  |     +-- Bounded file hashing and evidence references
  |     +-- Synthetic adversary-emulation scenarios
  |     +-- Versioned Field Finding JSON contract
  |
  +-- Existing USECT core binaries (separately built from source)
  |     +-- Core-ZERO: diagnostics, evidence, proposal-first recovery
  |     +-- Core-ONE: Genesis proposals and Guardian
  |     +-- Core-TWO: observation, coordination and human-feedback ledger
  |
  +-- Meta Engineer (Python/FastAPI in current repository)
        +-- validates imported finding contract
        +-- creates awaiting-approval review records
        +-- requires candidate tests and human approval
        +-- no automatic execution or deployment
```

The Field Engine does not reimplement the USECT cores. Its finding contract is the integration seam. Core-TWO remains the existing composition/observation layer, and Meta Engineer remains the review workflow. A binary being present or a loopback health endpoint responding is not proof of cross-core integration.

## 3. Guardian and adversary emulation

Guardian must learn attacker tradecraft without learning to bypass its own policy. It can:
- describe a technique at a defensive level;
- run deterministic, harmless synthetic scenarios in an isolated lab;
- verify that expected detections are produced;
- record evidence and missing telemetry;
- generate a remediation proposal.

Guardian must deny:
- remote exploitation and arbitrary target scanning;
- VPN/proxy circumvention and identity deanonymisation;
- credential dumping, phishing, token theft and exfiltration;
- stealth/evasion, disabling security controls and audit deletion;
- unapproved payload execution or destructive host changes.

The initial Go simulator includes only synthetic authentication-burst, startup-entry and VPN-visibility events. It does not manipulate the real OS. The VPN exercise explicitly tests the reporting boundary: tunnel presence is not a maliciousness verdict.

## 4. Versioned finding contract

The canonical JSON Schema is `portable/contracts/finding.schema.json`. Every finding states:
- schema version, source, ID and observed timestamp;
- target, scope, severity, category and summary;
- evidence references and optional SHA-256 values;
- recommendation;
- whether the record is synthetic;
- optional framework and technique labels.

Meta Engineer validates the contract via `meta_engineer/fieldkit_adapter.py`. A valid finding becomes a review record with `status=awaiting_approval`. This adapter does not persist it or execute its recommendation. A future authenticated FastAPI ingest route can persist it through the existing Meta Engineer store after the route and admin tests are added.

## 5. Repair lifecycle

1. Inspect the explicitly selected local target.
2. Preserve evidence and source hashes.
3. Generate a remediation plan with exact resources and prerequisites.
4. Validate the plan with Guardian and candidate tests.
5. Bind approval to the target, action, artifact digest and expiry.
6. Apply only through a separately registered, allowlisted repair adapter.
7. Verify the result and record a rollback outcome.

The 0.3 foundation provides read-only inventory, synthetic exercises and review-record preparation. It does not yet ship general Windows/Linux repair adapters. Do not claim that a proposal has been applied or that a device has been healed until the operation has run and its postconditions have been verified.

## 6. Release engineering

The USB release must contain precompiled executables for supported OS/architecture pairs. Do not require Go or a model runtime on the target workstation. The Go source remains in the repository; binaries are built in CI and tested against the source revision. Keep the original Python Field Kit as the evidence/documentation companion until native parity is demonstrated.

The existing source modules have separate Go module boundaries:
- `core-zero/go.mod`
- `core-one/go.mod`
- `core-two/go.mod`
- `lib/worldwide/go.mod`

Core-TWO uses local module replacements for Core-ONE, Core-ZERO and the worldwide library. Preserve that dependency graph and test it from CI. Do not merge module source trees or create a duplicate core.

## 7. Known gaps before calling USB Edition production-ready

- Precompiled Go core binaries must be built, bundled and smoke-tested on each supported OS.
- Full cross-core startup and authenticated health checks must be exercised on Windows and Linux.
- Meta Engineer needs an authenticated ingest endpoint for Field Engine findings; current adapter provides contract validation only.
- Offline vulnerability feed import, signature verification, provenance and freshness reporting are not yet implemented.
- OS-specific remediation adapters, backups, approval binding, rollback and post-repair verification are not yet implemented.
- Real EDR/SIEM connectors and detection coverage must be evaluated against customer-approved telemetry.
- A health endpoint or passing unit test does not establish complete production readiness.

## 8. Acceptance rule

A release is not "fully working" until source tests, race tests where applicable, static analysis, cross-platform builds, USB package smoke tests, core health checks, Guardian-negative tests and Meta Engineer hand-off tests all pass. Each result must be tied to a commit SHA and platform.
