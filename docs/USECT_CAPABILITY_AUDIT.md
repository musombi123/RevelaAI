# USECT Capability Coverage Audit

**Scope:** repository-level implementation and route/test evidence, based on the checked-in code.
**Status:** changes in this branch are not production-effective until PR #96 is merged and Render deploys the Blueprint in render.yaml. The RevelaCode-Backend Elimu compatibility work is in a separate PR.

This document separates a capability that has code and routes from one that has been verified live. Neither a route nor a passing unit test proves its production credentials, private-service reachability, supplier pricing, hardware safety, or regulatory conformity.

## Capability matrix

| Capability | Covered in code in this branch | Honest current boundary |
|---|---|---|
| **USECT-ZERO — Healer** | Private Go core, bounded API, read-only diagnostics, recovery proposals, scoped internal brain identity, admin approvals and audit logs. Canonical POST /v1/zero/heal connects the public platform contract to the core tool. | A recovery proposal is not proof that the supplied individual tool was fixed. Applying recovery remains a separately authorized, hash-checked human decision. |
| **USECT-ONE — Genesis** | Genesis service, Guardian policy, Core Mesh queue and canonical POST /v1/one/genesis for free-text demands. | A queue receipt is not a completed tool, endpoint, BOM or released artifact. Generation is still a proposal/review workflow. |
| **USECT-TWO — Infinite Mind** | Core-Two candidate assessment/evolution routes and POST /v1/two/improve/{tool_id} for an owned target. | Improvement is a proposal. No 10× result is claimed without comparable baseline and observed measurements. Source does not execute or merge automatically. |
| **USECT-ORCHESTRATOR** | POST /v1/orchestrator/run records sequential Zero diagnostics/recovery-proposal, Genesis queue, and Mind/Core-Two improvement-proposal results. | The pipeline reports partial/unavailable steps. It does not claim that a repair, tool birth, improvement or deployment completed merely because the HTTP request succeeded. |
| **USECT-LIVING-BRAIN** | Existing native chat, voice/vision and memory route families remain mounted. The capability inspector checks memory/chat route evidence. | Memory/provider reachability and user-session state must still be checked live; in-process data is not represented as durable unless stored by its own persistence service. |
| **USECT-BILLING / LICENSES** | Signed license verification, active-license ownership/expiry checks, plan entitlements, checkout intent, Stripe webhook settlement and 402-style license errors exist. The new readiness-report feature has an explicit entitlement. | Live billing needs valid deployed signing keys and payment-provider credentials. This branch does not claim M-Pesa is integrated; the listed checkout/webhook flow is Stripe-based. |
| **USECT-METER** | Existing usage summary plus middleware accounting for core/API operations: account, operation, country, latency and response success. | Estimated savings remains zero unless independently measured. Prompts and credentials are not copied into the operation meter. |
| **USECT-MARKETPLACE** | Published listings, safety screening, payment-backed purchase path, creator earnings and the recorded creator/platform fee split are implemented. | Listing is not proof of supplier availability, delivery, or independent tool security. Payout settlement depends on the configured payment/accounting process. |
| **USECT-FOUNDRY** | Free-text requirements can produce a bounded declarative factory/automation plan and manifest with a human-release gate. | BOMs, components and country guide entries are planning data; they are not live quotes, stock reservations, verified supply chains, executable production lines or physical deployment. |
| **USECT-SEED** | Signed seed/lease creation and offline verification exist; offline validity is bounded to the lease window (at most 30 days). | Expired/mismatched leases fail closed. This implementation does **not** silently wipe a device. Phoenix recovery remains key/signature controlled and must be tested against a real encrypted backup. |
| **USECT-AUDIT** | Hash-chained audit ledger and verify endpoint, plus stored PDF readiness reports with SHA-256 hashes and QR verification for CE/UL/ISO 9001/RoHS/FCC review scopes. | Generated PDFs are clearly labelled **draft readiness reports, not certificates**. Only the relevant authority/accredited lab and applicable test evidence can establish formal conformity. |
| **USECT-EVOLVE** | POST /v1/evolve/scan performs an on-demand lexical duplicate scan; this branch adds a scheduled scan every day at **02:17 UTC**, stores candidate evidence, and exposes GET /v1/evolve/scans/latest. The evolve endpoint creates evidence-targeted proposals. | Similarity is lexical-token Jaccard, not an embedding score. Candidates require human review. No automatic evolution/publication occurs and no 50× improvement is claimed. |
| **USECT-MIGRATE** | Explicit device enrollment, migration-plan and robot-blueprint routes exist. The plan carries declared hardware resources and verification gaps. | This is a proposal workflow—not stealth scanning, unattended workload migration, remote code execution, motor actuation or a deployed robot. Physical work requires explicit owner approval and qualified testing. |
| **USECT-UNCOPYABLE** | Code includes recipe startup verification, signed license checks, a software machine fingerprint, encrypted RVX dialect functions and founder-signed tool/DNA watermark helpers. | A software fingerprint is not TPM-backed hardware attestation. No automatic destructive wipe is enabled. Each lock only works where its verifier is enforced and provisioned in the actual deployment. |
| **USECT-INSPECTOR** | GET /v1/inspector/inspect checks source files, test files and real route registrations, including mounted ASGI sub-app routes; ELIMU is explicitly marked external. POST /v1/inspector/produce creates a licensed, watermark-signed, reviewable factory plan with unverified resource claims called out. | Inspector output is an evidence inventory and planning simulation. ready_for_production remains false until real deployment, provider, security, test, supply, compliance and hardware evidence has been checked. |
| **Worldwide BOM / localization / electrical guides** | Go helper profiles and worldwide hardware-guide code cover supported country/language data, basic nominal electrical references, BOM adaptations and integration plans. | Supplier leads are not quotes. Nominal voltage is not a design approval. DIN-rail compatibility, exact hardware revision, current stock, 110/120/230/240 V design, datasheets and applicable electrical standards need model-specific engineering review. |
| **Guardian / harm screening** | Genesis, publication and Foundry safety screens have explicit code and regression tests; risky operations require review/approval. | Deterministic screens reduce known risk but are not a guarantee that every arbitrary demand is safe. Hazardous or regulated use still needs domain-specific review. |
| **ELIMU Hub** | Source and regression tests exist in RevelaCode-Backend for authenticated hubs, progress persistence, completion-gated learning certificates, account profile PDF and signed public verification. The separate backend PR adds /api/elimu/* and /api/certificates/* compatibility aliases and fixes QR URLs. | It is an external service from the AI gateway's perspective. Verify the backend PR and deployment separately; account/learning certificates attest only to recorded platform participation/completion, not academic or government accreditation. |

## Canonical platform routes added or reinforced

| Route | Purpose |
|---|---|
| POST /v1/zero/heal | Submit a failure reference and request bounded recovery proposal |
| POST /v1/one/genesis | Queue a free-text Genesis demand |
| POST /v1/two/improve/{tool_id} | Request a licensed, owner-checked Core-Two improvement proposal |
| POST /v1/orchestrator/run | Run the ordered Zero → One → Two proposal pipeline |
| POST /v1/evolve/scan | On-demand twin-candidate scan |
| GET /v1/evolve/scans/latest | Retrieve the latest stored scan evidence |
| POST /v1/evolve/evolve | Build an evidence-targeted evolution proposal |
| GET /v1/inspector/inspect | Inspect code, test and route inventory |
| POST /v1/inspector/produce | Generate a reviewable production-plan simulation |
| POST /v1/auditor/reports/generate | Create a stored draft compliance-readiness PDF |
| GET /v1/auditor/reports/{report_id}/verify | Verify the stored report metadata and exact PDF hash |
| GET /v1/auditor/reports/{report_id}/pdf | Download the report, owner/reviewer gated |

## What must still be verified after deployment

1. Merge PR #96 and deploy/sync the Render Blueprint so the platform revenue gateway—not only the AI sub-app—is the entry point.
2. Merge the separate RevelaCode-Backend PR for Elimu aliases/QR URL fixes and deploy that backend.
3. Check live health for Core Zero, Genesis/Core One, and Infinite Mind/Core Two using the deployed services; structural route presence is not upstream health.
4. Verify deployed license signing/verification keys, payment provider configuration, database persistence, and private service links. No real secrets are stored in this repository as defaults.
5. Run a real authenticated end-to-end license/checkout/webhook/usage/marketplace cycle in a controlled environment.
6. Validate a real seed package/lease/restore; inspect a real migration plan against an explicitly enrolled device; benchmark candidate evolution with reproducible test evidence.
7. Obtain independent compliance and qualified hardware/electrical evidence before production, certification or actuation claims.

The Inspector deliberately returns ready_for_production: false; it will not turn missing live evidence into a green status.
