# RevelaAI Evolver — Architecture and Operational Contract

**Status:** Phase 1 implementation
**Contract version:** 1.0
**Owner:** RevelaAI platform
**Primary services:** USECT-EVOLVE, Genesis/Core-One, Brain OS, Sci-Core, Guardian/Sci Defender, signed Genesis tool registry

## Purpose

The Evolver is RevelaAI's governed improvement director. It coordinates repeated cycles of problem discovery, invention, evaluation, learning and candidate improvement across software tools, AI capabilities and hardware designs.

It is not a second model, a replacement for Genesis, or an unrestricted process that rewrites the live production service. It uses the existing model router and tool-building services to propose changes, then measures and records their outcomes.

## Existing systems and ownership

| Responsibility | Existing owner | Evolver relationship |
| --- | --- | --- |
| Understand a demand, research it and create an invention package | Genesis / Core-One | Calls the existing Genesis invention API |
| Generate tool manifests, run Guardian and sandbox checks, sign immutable artifacts | Genesis tool registry | Requests publication; never signs artifacts itself |
| Offer and execute verified tools to the model | `ai/tool_registry.py` and Genesis runtime | Uses the existing signed-tool execution path |
| Workflow planning, permission scopes, consent and one-shot execution | Automation Fabric | Reuses its policy/plan contracts; does not add shell execution |
| Record delivery, quality, feedback and service outcomes | Brain OS | Supplies outcome signals to the Evolver |
| Threat screening and recovery controls | Sci-Core / Guardian / Sci Defender | Remain independent gates; Evolver cannot waive them |
| Candidate hypotheses, metric comparisons and bounded recursive proposals | USECT-EVOLVE | Coordinates improvement cycles |
| Durable improvement evidence | Existing Sci-Core MongoDB connection | Uses `revelai.evolution_runs`; no second Mongo client |

## Evolution lifecycle

1. **Observe:** Read approved feedback, service outcome telemetry, incident summaries and benchmark results. Do not treat a successful HTTP response as proof that a tool solved its task.
2. **Diagnose:** Identify a measurable weakness or unmet capability. Record a baseline, quality dimensions, constraints and an explicit objective.
3. **Design:** Create a candidate hypothesis and capability plan. For new tools, ask Genesis to research and produce the invention package. For an existing tool, create a bounded child proposal tied to its parent and system scope.
4. **Build:** Generate candidate artifacts in the Genesis staging area. The initial factory may create software scaffolds and hardware design packages; domain-complete implementation still requires validation against real acceptance criteria.
5. **Verify:** Run Guardian checks, static analysis, deterministic tests and the isolated Genesis sandbox. Record exact evidence references and artifact hashes.
6. **Compare:** Evaluate the candidate against the same baseline using named metrics for task quality, accuracy, latency, reliability, resource use, cost and applicable safety constraints.
7. **Publish:** Ask Genesis to sign and append the validated artifact to its immutable registry. A published artifact is not automatically a production deployment.
8. **Activate:** Reuse Genesis activation controls. Tier 1 and Tier 2 artifacts require owner approval bound to the exact artifact digest; Tier 2 actions require separate action approval. Existing Tier 0 activation rules remain in force.
9. **Learn:** Record privacy-minimized proposal and evaluation evidence in MongoDB. The next proposal can retrieve a bounded history of verified metric outcomes and (when a Brain OS category is explicitly supplied) aggregate Brain OS delivery, task-quality, latency and feedback signals. Delivery success is never treated as task-quality success. Temporary local cache is never accepted as durable learning.
10. **Improve again:** Create a new generation, preserving parentage, evidence, rollback target and the active version. Stop when evidence is insufficient, a safety gate fails, a metric regresses, or the generation budget is exhausted.

## Durable learning record

The canonical database remains the existing `revelai` MongoDB database reached through `revelai.sci_core.storage.collection`. The new `evolution_runs` collection is both the durable proposal-state store and append-oriented evidence ledger. Production does not depend on a local filesystem copy for proposal retrieval.

The ledger records:
- the privacy-minimized proposal state needed to resume evaluation after a process restart, plus proposal and parent IDs, system ID and generation;
- an optional declared Brain OS category, allowing domain-specific delivery, task-quality, latency and feedback aggregates to inform the next candidate;
- a SHA-256 fingerprint of the objective, not the raw objective text;
- metric names, directions, baselines, observations, targets and pass results;
- test/security gate booleans and evidence-reference hashes;
- Genesis tool name/version, risk tier, artifact digest and sandbox result;
- event timestamps and schema version.

The original objective is stored only as a SHA-256 fingerprint; the proposal state stores a redacted fingerprint placeholder so evaluation can resume without the original text. The ledger does not store user prompts, generated source, credentials, full uploaded documents or personal account identifiers. Approved knowledge ingestion is a separate governed learning pathway.

If MongoDB is missing or unreachable, Evolver proposal/evaluation operations fail closed. The bounded Sci-Core local cache remains useful for temporary diagnostics only and must never be presented as durable learning.

## Software, AI and hardware capability domains

### Software and AI tools
The current Genesis manifest/runtime ABI supports Go and Python artifacts with a constrained `action` / `inputs` / `consent` contract, fixed input/output schemas, bounded time and memory, permission-derived risk tiers and signed publication. A new invention must fit that contract or be proposed as a separately reviewed runtime extension. It must not silently bypass the ABI.

### Hardware and robotics
Hardware inventions begin as engineering proposals: requirements, block diagrams, interface specifications, circuit concepts, bill of materials, firmware plan, simulation cases, hazards, component ratings, datasheet evidence, verification procedure and service/maintenance plan.

A hardware blueprint is not proof that a device is safe or buildable. Before any physical actuation, require verified component inventory, electrical/mechanical review, independent safety controls, an emergency stop, operator override, authenticated device enrollment, firmware/artifact integrity verification and explicit owner/operator authorization. No generated tool can grant itself hardware permissions.

## Authority and isolation boundaries

- The model can suggest; policy code decides whether an operation is permitted.
- Genesis generates and sandboxes candidates; candidate source is never imported into the RevelaAI gateway.
- The signed registry is append-only; activation is a separate operation.
- The Evolver can create proposals and child proposals but cannot edit the live system, merge its own PR, alter auth/licensing/Guardian controls, or issue its own owner approval.
- A candidate cannot change its own evaluation criteria after the baseline is fixed. Criteria changes create a new versioned experiment.
- External research and tool output are untrusted inputs. They do not become trusted memory without validation and explicit knowledge governance.
- Any rollback must point to a previously verified, signed artifact and preserve its audit trail.

## Growth model

The system should be ready to activate additional capacity without changing its contracts:
- model/provider adapters behind the existing router;
- isolated local or remote workers behind a standard execution adapter;
- domain-specific evaluators for code, scientific models, finance, robotics and hardware;
- distributed experiment queues and parallel candidate archives;
- tenant-aware quota, cost and policy controls;
- signed device agents and attested hardware environments;
- capability registry entries with version, dependencies, risk tier, lifecycle state, health evidence and activation policy.

These are extension points, not claims that distributed execution, universal hardware creation, autonomous production deployment or arbitrary self-rewriting are operational today.

## Readiness vocabulary

Use evidence-backed states only:
- `implemented`: code and contract exist.
- `tested`: the required automated tests have passed on the recorded commit.
- `available`: required services and configuration are reachable now.
- `experimental`: limited evaluation; not production dependable.
- `planned`: contract or design exists but implementation is incomplete.
- `blocked`: required dependency, evidence or approval is missing.
- `disabled`: intentionally unavailable by policy or configuration.

A feature flag alone does not make a capability available.

## Phase 1 acceptance criteria

- Evolver proposal and evaluation history is durably written to MongoDB using the existing Sci-Core storage connection.
- MongoDB fallback to `LocalCollection` is rejected for learning operations.
- Subsequent proposals can include bounded historical metric signals from prior evaluations and optional Brain OS category-level outcomes; delivery and task-quality evidence remain separate.
- Creating an invention calls the existing Genesis invention pipeline.
- Existing Evolver proposals can be submitted to the existing Infinite Mind/Core-Two review path using an objective fingerprint check; no raw objective text is persisted.
- Publishing a tool calls the existing Guardian, sandbox and signed Genesis registry path.
- New routes use the existing organ-admin and enterprise-evolve entitlement checks.
- No new route executes generated code in the RevelaAI Python process.
- Tests prove no raw objective/source material is written to the evolution ledger, fallback is rejected, learning context is reused and candidate evidence is required.
- CI passes before this branch is considered merge-ready.

## Capability contract

The machine-readable inventory lives in `core_evolve/capabilities.py` under schema `revela.factory-capability.v1`. It is not a second executable tool registry: Genesis owns signed tool manifests and versions. Each capability records its owner, domain, dependencies, lifecycle, runtime-probe type, approval policy and execution boundary. The inventory never turns source presence into runtime readiness; external services remain `not_probed` until a real health probe is available.

## API surface introduced by Phase 1

All endpoints below are under `/api/usect` and use the existing `X-Organ-Admin-Token` plus `X-Revela-License` gates.

| Method | Route | Effect |
| --- | --- | --- |
| GET | `/evolve/capabilities` | Read the versioned capability inventory without claiming unprobed dependencies are online |
| GET | `/evolve/learning/{system_id}` | Read MongoDB-backed evaluation signals |
| POST | `/evolve/tools` | Create an invention proposal through Genesis; no publication |
| POST | `/evolve/tools/{name}/publish` | Guardian + sandbox + signed registry publication; no gateway execution |
| POST | `/evolve/proposals` | Create a bounded metric-driven evolution proposal |
| POST | `/evolve/proposals/{proposal_id}/children` | Create a bounded child proposal |
| POST | `/evolve/proposals/{proposal_id}/evaluate` | Evaluate candidate measurements and persist results |
| POST | `/evolve/proposals/{proposal_id}/mind-review` | Ask existing Infinite Mind/Core-Two to review a proposal after objective fingerprint verification and active Genesis artifact verification |

Existing Genesis/Core Mesh endpoints remain the activation, rollback and execution control plane. Do not implement parallel endpoints that duplicate them.
