# RevelaAI USB Field Engine — architecture and integration contract

**Target:** USB Edition 0.3
**Native runtime:** Go 1.23+ source, standard-library-only Field Engine
**Decision model:** Guardian-first, read-only by default, proposal-first repairs
**Offline requirement:** Core inspection and synthetic detection validation must work without Ollama or an internet connection.

## 1. Why this direction is industry-relevant

Revela should combine local system inspection, exposure assessment, threat-informed defence validation, forensic evidence handling and human-governed recovery. The product should not be described as a general-purpose exploit framework.

The design aligns to:
- MITRE ATT&CK as a shared vocabulary for adversary behaviour and defensive detection coverage.
- NIST Cybersecurity Framework functions: Govern, Identify, Protect, Detect, Respond and Recover.
- Controlled adversary simulation to test whether controls, telemetry, incident response and recovery processes work.

Keep framework mappings versioned. The current ATT&CK catalogue as of 2026-10-31 is v20.0. Do not imply every ATT&CK technique has a safe simulator or that a synthetic event validates a production detector.

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
  |     +-- Loopback-only ZERO / ONE / TWO supervisor
  |
  +-- Existing USECT core binaries + matching source/policies
  |     +-- Core-ZERO: diagnostics, evidence, proposal-first recovery
  |     +-- Core-ONE: Genesis proposals and Guardian
  |     +-- Core-TWO: observation, coordination and human-feedback ledger
  |
  +-- Meta Engineer (Python/FastAPI in current repository)
        +-- validates imported finding contract
        +-- persists awaiting-approval review records
        +-- requires candidate tests and human approval
        +-- no automatic execution or deployment
```

The Field Engine does not reimplement the USECT cores. Its finding contract is the integration seam. Core-TWO remains the existing coordination/observation layer, and Meta Engineer remains the review workflow. A binary being present or a loopback health endpoint responding is not proof of package-level cross-core correctness.

## 3. Guardian and adversary emulation

Guardian must learn attacker tradecraft without learning to bypass its own policy. It can:
- describe a technique at a defensive level;
- run deterministic, harmless synthetic scenarios in an isolated lab;
- map scenarios to a versioned ATT&CK technique label where appropriate;
- verify whether expected detections fire in the test harness;
- record evidence and missing telemetry;
- generate a remediation proposal.

Guardian must deny:
- remote exploitation and arbitrary target scanning;
- VPN/proxy circumvention and identity deanonymisation;
- credential dumping, phishing, token theft and exfiltration;
- stealth/evasion, disabling security controls and audit deletion;
- unapproved payload execution or destructive host changes.

The initial Go simulator includes only synthetic authentication-burst, startup-entry and VPN-visibility events. It does not manipulate the real OS. These fixtures validate the simulator/reporting path; they do not claim that an EDR/SIEM detects a real-world attack. The VPN exercise explicitly tests the reporting boundary: tunnel presence is not a maliciousness verdict.

## 4. Versioned finding contract and Meta Engineer hand-off

The canonical JSON Schema is `portable/contracts/finding.schema.json`. Every finding states:
- schema version, source, ID and observed timestamp;
- target, scope, severity, category and summary;
- evidence references and optional SHA-256 values;
- recommendation;
- whether the record is synthetic;
- optional framework and technique labels.

Meta Engineer validates the contract via `meta_engineer/fieldkit_adapter.py`. The authenticated route `POST /api/meta-engineer/fieldkit/findings` creates an `awaiting_approval` record in the existing `revelai.ideas` collection and appends an audit event. It streams/caps request bodies and deduplicates by finding ID. The authenticated endpoint requires the existing RevelaCode administrator bearer verification and the configured existing MongoDB store. A valid hand-off means the finding entered the review queue; it does not confirm an incident or execute a repair.

The USB `sync` command sends only the structured finding JSON. It requires an existing administrator bearer session in the `REVELA_ADMIN_BEARER` environment variable, uses HTTPS for remote hosts, accepts HTTP only on loopback for local development, and rejects redirects. Do not put the session token on the USB or into case evidence.

## 5. Local core supervision

The release bundle contains prebuilt Windows/Linux x64 executables and the matching `runtime-source/` core modules and Guardian policy files. The supervisor:
- verifies the expected source and policy files are present;
- generates temporary service tokens at launch;
- launches ZERO, Genesis and Mind on `127.0.0.1` only;
- supplies a minimal process environment and excludes provider/model/Mongo credentials;
- disables Mind auto-evolution;
- writes logs and ZERO runtime state under the USB `data/` directory;
- checks each service health endpoint and stops children when the operator exits.

Health probes are reachability checks, not proof of complete internal correctness. The release CI must test the Go modules, run the existing stack composition, cross-compile the USB binaries, and smoke-test the bundled Field Engine supervisor.

## 6. Repair lifecycle

1. Inspect the explicitly selected local target.
2. Preserve evidence and source hashes.
3. Generate a remediation plan with exact resources and prerequisites.
4. Validate the plan with Guardian and candidate tests.
5. Bind approval to the target, action, artifact digest and expiry.
6. Apply only through a separately registered, allowlisted repair adapter.
7. Verify the result and record a rollback outcome.

The 0.3 foundation provides read-only inventory, synthetic exercises, a review hand-off and loopback core supervision. It does not yet ship general Windows/Linux repair adapters. Do not claim that a proposal has been applied or that a device has been healed until the operation has run and its postconditions have been verified.

## 7. Release engineering

The USB release must contain precompiled executables for supported OS/architecture pairs. Do not require Go or a model runtime on the target workstation. The Go source remains in the repository; binaries are built in CI and tested against the source revision. Keep the original Python Field Kit as the evidence/documentation companion until native parity is demonstrated.

The existing source modules have separate Go module boundaries:
- `core-zero/go.mod`
- `core-one/go.mod`
- `core-two/go.mod`
- `lib/worldwide/go.mod`

Core-TWO uses local module replacements for Core-ONE, Core-ZERO and the worldwide library. Preserve that dependency graph and test it in CI. Do not merge module source trees or create a duplicate core.

## 8. Known gaps before calling USB Edition production-ready

- Precompiled Go core binaries must pass the updated Windows/Linux package workflow and target-device smoke tests.
- Meta Engineer ingest is connected, but it does not yet build or execute repair adapters.
- Offline vulnerability feed import, signature verification, provenance and freshness reporting are not implemented.
- OS-specific remediation adapters, backups, approval binding, rollback and post-repair verification are not implemented.
- Real EDR/SIEM connectors and detection coverage must be evaluated against customer-approved telemetry.
- Adversary-emulation scenarios are synthetic fixtures, not operational exploit modules or live attack validation.
- A health endpoint or passing unit test does not establish complete production readiness.

## 9. Acceptance rule

A release is not "fully working" until source tests, race tests where applicable, static analysis, cross-platform builds, USB package smoke tests, core health checks, Guardian-negative tests and Meta Engineer hand-off tests all pass. Each result must be tied to a commit SHA and platform.
