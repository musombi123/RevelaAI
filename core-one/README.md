# Revela Genesis — USECT-One / Core-One

**Version:** `0.3.0-alpha`  
**Module:** `revela-genesis.local/core-one`  
**Requirements:** Go 1.23 or newer  
**Operating model:** Standalone, model-optional, proposal-first invention engine

## 1. Overview

Revela Genesis Core-One is a standalone invention engine for RevelaAI. It observes research and repository signals, accepts demands, derives structured tool specifications, builds capability and requirement plans, and generates reviewable software and hardware-integration proposals.

Genesis is designed to support a broad range of tool concepts rather than depend exclusively on a fixed catalogue of prebuilt domain-specific tools. The first release focuses on generating safe, reviewable scaffolds; a generic generated scaffold is not a finished production implementation for every possible demand.

The engine can operate without an AI model or an active provider connection. Research, planning, artifact generation, and expansion management use deterministic processing where available. An optional model adapter can enrich bounded descriptive metadata without taking control of deterministic safety requirements.

**Core operating principle:** generate on demand, preserve evidence, validate requirements, and require human approval before integration or activation.

## 2. Core Principles

- **Standalone operation:** Genesis can operate without a configured model endpoint or provider service.
- **Model optionality:** a configured model may enrich specification metadata, but deterministic fallback behavior remains available.
- **Safety-first processing:** Guardian screens demands before research and screens relevant research and model-derived content before generation.
- **Capability transparency:** every accepted invention receives a capability plan that identifies reusable candidates, unresolved requirements, and proposed acceptance checks.
- **Reviewable generation:** source scaffolds, tests, documentation, API contracts, SDK proposals, and supporting evidence are staged for review.
- **Controlled expansion:** new capabilities, reusable libraries, and model-family blueprints are recorded as proposals rather than imported automatically into the running core.
- **Human ownership:** Genesis does not automatically commit, merge, deploy, flash firmware, execute generated source code, or activate new tools.

## 3. Reliability Foundation — v0.2.0-alpha

The reliability upgrade hardens the foundation before broader invention capabilities are added.

It includes:

- Research adapters and the optional model adapter that honor request cancellation.
- Concurrent research collection under a shared deadline, with results assembled in a stable order.
- Bounded model-assisted metadata enrichment that cannot rename an invention, reclassify deterministic category or industry fields, or remove a demand-derived hardware-guide requirement.
- Guardian fail-closed behavior when policy is unavailable or required controls are missing.
- Screening of research findings in addition to source titles and descriptions.
- Queue processing designed to claim records atomically, recover interrupted claims, return cancelled work to the pending queue, and surface persistence errors through events.
- `GET /v1/genesis/status` for queue, invention, research, mode, and Guardian information.
- An event stream designed for long-lived Server-Sent Events connections.
- A dedicated GitHub Actions workflow for Go tests, race detection, `go vet`, CLI builds, and offline generation and compile checks.

These controls improve confidence but do not replace integration review, hardware testing, or deployment-specific security validation.

## 4. Capability Graph and Requirement Planner — v0.3.0-alpha

Genesis builds a deterministic capability graph and requirement plan before staging invention artifacts.

The planner:

1. Extracts general and demand-specific requirements.
2. Maps requirements to available Core-One contract and planning primitives.
3. Searches library metadata for potentially reusable implementations.
4. Records dependency relationships and requirement edges.
5. Identifies missing capabilities and unresolved requirements.
6. Defines acceptance checks and residual risks.
7. Exposes the generated plan through the invention response and the capability-plan API.

Every staged invention receives `capability_plan.json`. Where supported, the invention response also contains the plan path and coverage summary.

### How to interpret capability coverage

A **native contract available** result means a planning or guardrail contract exists. It does not prove that a domain-specific production implementation is complete.

A **reusable library candidate** is an unverified match based on available metadata. It does not prove correctness, licensing compatibility, security, or suitability.

An **unresolved capability** identifies work that still needs an owner, implementation, and appropriate tests before release.

## 5. Current Capabilities

### Eye — Research and Repository Signals

Eye gathers evidence from public research sources and identifies potential areas for invention or expansion.

Online research collectors include:

- GitHub repository search
- arXiv research-paper discovery
- NVD CVE lookup for defensive vulnerability awareness
- Kenya-focused technology-demand news through RSS

Evidence bundles also include research links for WIPO PATENTSCOPE, ISO, KEBS, Jumia Kenya, Mouser, and DigiKey.

These links are research leads. They do not establish verified prices, inventory, patent clearance, legal compliance, standards conformity, supplier endorsement, or actual market demand.

Repository scanning fingerprints repeated TODO, FIXME, and workaround patterns without executing source code or copying entire source files into model prompts.

### Genesis — Demand-to-Proposal Generation

Genesis accepts text demands and derives a bounded generic tool specification without requiring a model.

The generation workflow can produce:

- Go source scaffolds and reusable contracts
- Test scaffolds
- OpenAPI specifications
- Hardware integration guides
- Research evidence
- Capability and implementation plans
- Acceptance matrices
- Dependency and security review artifacts
- Worldwide context
- Go, Python, and JavaScript SDK proposals
- Merge checklists and artifact integrity manifests

The exact outputs depend on the demand and the generator implementation.

A generic template is a starting point for implementation, not proof that a requested system is production-ready. A factory controller, medical device, financial service, or other domain-specific tool needs validated requirements, correct implementation, appropriate testing, and any required specialist review.

### Library Forge — Reusable Contract Proposals

Library Forge creates reusable Go contract-library proposals containing a driver, tests, and documentation.

Potential library matches remain unverified candidates until the actual source, API, dependencies, licensing, tests, and intended integration are reviewed.

Generated libraries are not dynamically imported into the running engine.

### Model Forge — Tool-Family Blueprints

Model Forge generates YAML blueprints describing new tool families and their expected inputs, outputs, constraints, and review gates.

A configured model service can suggest bounded specification metadata. Model-generated source code is not executed or copied into runtime code files.

Blueprint settings document intended controls; application code must enforce any setting that affects actual runtime behavior.

### Expand — Controlled Growth

Expand records deduplicated proposals for:

- Capability additions
- Industry taxonomy changes
- Model-family extensions
- Reusable-library extraction
- Platform and infrastructure improvements

Expansion plans and review information are persisted. When the configured file-count threshold is reached, new plans are staged under `core-one/gen2/` rather than changing the running engine.

### Guardian — Safety and Policy

Guardian screens demands before research and screens relevant research and model-derived information before generation.

Its responsibilities include:

- Enforcing the configured policy-readiness checks
- Blocking inputs that match configured prohibited patterns
- Screening research and model metadata
- Recording blocked-request audit information
- Preserving the deterministic safety boundary during generation

Prohibited demands are intended to be rejected before invention, library, or model artifacts are created. Blocked events are recorded in `guardian/blocked.log`.

Pattern screening is a safety layer, not a perfect semantic classifier. A keyword match can block benign educational or defensive discussion, and passing a pattern check does not prove a request is safe.

### Provider Loop — Optional Synchronization

The provider loop can send a heartbeat to a configured RevelaCode provider at startup and at a configured interval.

Inbound demands are submitted through the local queue and its Guardian checks. Incoming graph and law documents remain external proposals and cannot automatically weaken local policy.

The corresponding provider heartbeat route is an integration contract. The RevelaCode backend must implement that route before synchronization can work.

### RVX — Declarative Intermediate Representation

RVX provides a small declarative language with 20 keywords. It parses supported instructions into a bounded JSON intermediate representation.

This revision does **not** generate encrypted WASM, compile RVX into native executable code, or execute the resulting instructions.

## 6. Architecture

```text
                 Optional existing model endpoint
                          │
                          │ bounded specification metadata
                          ▼
Eye ── research/evidence ──> Genesis ──> Library Forge
  ▲                            │               │
  │                            ▼               ▼
  │                    Capability Planner   Model Forge
  │                            │               │
  │                            ▼               ▼
  └──── periodic scan ── Expand proposals ─ Guardian
                               │                 ▲
                               ▼                 │ re-check
                    API / SDK / hardware guide ─┘
                               │
                               ▼
                     await owner review
                               │
                               ▼
                   approved, controlled integration

                   Optional RevelaCode provider
```

Guardian checks occur before research and again on applicable research- and model-derived inputs. The diagram is conceptual; it does not mean every generated proposal automatically passes every review gate.

Tool-specific API paths described in generated OpenAPI files remain proposals until the owner merges the relevant changes and explicitly registers the implementation with the host service.

## 7. Repository Layout

The following illustrates the principal parts of Core-One. Some artifacts are generated on demand and therefore may not exist until a relevant workflow runs.

```text
core-one/
├── cmd/
│   └── genesis/
├── genesis/
│   ├── engine.go
│   ├── guardian.go
│   ├── eye.go
│   ├── capability_graph.go
│   ├── expansion.go
│   ├── forge.go
│   ├── server.go
│   └── ...
├── endpoint/
├── hardware/
├── guardian/
│   └── rules.yaml
├── inventions/
├── libraries/
│   └── created/
├── models/
├── research/
├── expand/
├── state/
├── rvx/
├── openapi.yaml
├── go.mod
└── README.md
```

Core-One uses the local worldwide library through the Go module replacement configured in `go.mod`. The module intentionally avoids third-party Go dependencies.

## 8. Standalone Setup

### Requirements

- Go 1.23 or newer
- The Core-One source directory
- The adjacent `lib/worldwide` module required by the local module replacement

### Run tests

From the repository root:

```powershell
cd core-one
go test -race ./...
go vet ./...
```

### Generate a proposal offline

```powershell
cd core-one
$env:GENESIS_OFFLINE = "1"
go run ./cmd/genesis -mode invent -repo-root .. -demand "Create tool: offline file vault"
```

Offline mode skips online retrieval and uses the research links and deterministic fallback behavior available to the engine. It does not require a configured model.

The generated package is staged under:

```text
core-one/inventions/offline_file_vault/
```

Depending on the current implementation, generation can also create associated library, model-blueprint, research, and expansion records.

**Important:** inspect the actual generated files rather than assuming every documented artifact will always be emitted. Existing invention directories are not intended to be silently overwritten.

## 9. Run the Local API and Daemon

For local development:

```powershell
cd core-one
$env:GENESIS_ADMIN_TOKEN = "replace-with-a-long-random-secret"
go run ./cmd/genesis -mode serve -repo-root .. -listen 127.0.0.1:8781 -interval 60s
```

The daemon scans immediately on startup and then processes the queue at the configured interval. A queued demand is processed on a later cycle. `POST /v1/genesis/invent` is the synchronous generation path.

The default listener is loopback-only. Remote access requires the configured Genesis token, except for the minimal public health check. A deployment exposed beyond loopback needs appropriate TLS, trusted-proxy configuration where applicable, access controls, rate limiting, and deployment review.

Do not expose the service directly to the public internet without verifying the listener, transport security, authentication, request limits, and hosting configuration.

## 10. Acceptance Checks

The following scenarios define important behavior to verify in integration tests.

### A. Automatic queue processing

Start the server with a short interval, such as `-interval 1s`, and submit:

```json
{
  "demand": "Create tool: offline file vault"
}
```

using `POST /v1/genesis/queue`.

Expected behavior:

- The demand is persisted.
- Local Guardian and queue validation remain active.
- The daemon processes the demand on a subsequent cycle.
- A successful generation remains a reviewable proposal with `await_merge` status.

### B. Demand-driven hardware proposal

Submit a request such as `CCTV` to `POST /v1/genesis/invent`.

Expected behavior:

- Guardian evaluates the demand.
- If accepted, Genesis derives the specification and creates a proposal.
- A relevant hardware guide includes privacy and integration-review caveats.
- No preinstalled CCTV invention is assumed.
- No physical device is activated automatically.

The exact normalized invention name and artifact inventory should be verified against the current generator's behavior.

### C. Block prohibited demand

Submit `weapon` to `POST /v1/genesis/invent`.

Expected behavior under the configured Guardian policy:

- The request is blocked before invention generation.
- The API returns HTTP 403.
- The blocked event is audited.
- No invention proposal is created for the blocked demand.

Test that rejection behavior using an isolated test root so an existing proposal or prior audit record cannot affect the result.

## 11. HTTP API Contract

The local OpenAPI contract is documented in `openapi.yaml`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/v1/genesis/health` | Basic health and execution-mode information |
| `GET` | `/v1/genesis/status` | Queue, invention, research, and Guardian snapshot |
| `POST` | `/v1/genesis/invent` | Research and generate one proposal synchronously |
| `POST` | `/v1/genesis/queue` | Persist a demand for daemon processing |
| `GET` | `/v1/genesis/tools` | List staged invention proposals |
| `GET` | `/v1/genesis/tools/{name}` | Read proposal evidence |
| `GET` | `/v1/genesis/tools/{name}/hardware_guide` | Retrieve a country-aware hardware guide |
| `GET` | `/v1/genesis/tools/{name}/capability_plan` | Read requirements, candidate libraries, gaps, and acceptance criteria |
| `GET` | `/v1/genesis/stream` | Stream engineering events using SSE |
| `GET` / `POST` | `/v1/genesis/key` | Read key-request instructions or submit a request for human approval |
| `POST` | `/v1/rvx/compile` | Compile RVX into bounded JSON IR |

The generated OpenAPI for an individual invention can describe additional tool-specific paths. Those paths do not become active endpoints merely because they appear in a generated contract.

## 12. Optional Model Adapter

Genesis can run without a model. To use an existing OpenAI-compatible model service for specification metadata, configure the following server-side variables.

| Variable | Purpose |
|---|---|
| `GENESIS_MODEL_BASE_URL` | Base URL or full chat-completions endpoint |
| `GENESIS_MODEL_NAME` | Model identifier accepted by the service |
| `GENESIS_MODEL_API_KEY` | Optional server-side credential |

If the base URL ends in `/v1`, the adapter appends `/chat/completions`; otherwise, it appends `/v1/chat/completions`.

The model service must support the OpenAI-compatible chat-completions JSON format used by the adapter. If RevelaAI's deployed model endpoint uses a different request or response contract, a dedicated adapter must be implemented rather than assuming an undocumented route exists.

Model output remains untrusted metadata. If the model is unavailable or returns malformed content, the deterministic fallback remains available.

**Never expose `GENESIS_MODEL_API_KEY` in frontend settings, public API responses, or committed source code.**

## 13. Optional RevelaCode Provider

Configure the provider integration using:

- `REVELACODE_PROVIDER_URL`
- `REVELACODE_PROVIDER_KEY`, where required
- `REVELACODE_PROVIDER_INTERVAL`, when a non-default heartbeat interval is needed

Genesis sends a heartbeat to:

```text
<REVELACODE_PROVIDER_URL>/v1/genesis/provider/heartbeat
```

The default interval is 24 hours; a valid configured interval can override it.

The endpoint is a documented integration contract, not a claim that the current RevelaCode backend already implements it. The backend must provide compatible behavior for heartbeat synchronization to work. Standalone operation remains available when no provider is configured.

## 14. Configuration Reference

| Variable | Purpose | Default or behavior |
|---|---|---|
| `GENESIS_OFFLINE` | Skip online research | Unset means online retrieval is attempted |
| `GENESIS_ADMIN_TOKEN` | Protect remote access and mutations | Unset allows the server's configured loopback-only behavior |
| `GENESIS_MODEL_BASE_URL` | Enable an optional model adapter | Disabled |
| `GENESIS_MODEL_NAME` | Model identifier | `existing-revelaai-model` |
| `GENESIS_MODEL_API_KEY` | Server-side model credential | Empty |
| `GENESIS_SIGNING_KEY` | Optional HMAC-SHA-256 signing key for artifact manifests | Manifest may contain hashes without an HMAC |
| `GENESIS_WORKAROUND_THRESHOLD` | Repeated workaround signals before an automatic proposal trigger | `6` |
| `GENESIS_DEMAND_THRESHOLD` | Repeated evidence-topic hits before an automatic proposal trigger | `5` |
| `GENESIS_MAX_CORE_FILES` | File-count threshold for routing expansion plans to `gen2/` | `5000` |
| `REVELACODE_PROVIDER_URL` | Optional provider base URL | Disabled |
| `REVELACODE_PROVIDER_KEY` | Optional provider credential | Empty |
| `REVELACODE_PROVIDER_INTERVAL` | Provider heartbeat interval | `24h` |

An environment variable only has an operational effect when the current code reads and enforces it. Configuration documentation should be kept aligned with the implemented behavior.

## 15. Security, Safety, and Truthful Limits

Genesis supports policy checks, bounded inputs, audit records, controlled file generation, proposal-only execution, and explicit review gates. These measures improve safety and traceability, but they do not make arbitrary generated software automatically secure.

Important limitations:

- Pattern-based Guardian screening is not a complete semantic classifier.
- Retrieved sources and model responses may be incomplete, outdated, misleading, or malicious.
- A research link does not establish patent clearance, legal compliance, verified pricing, stock availability, or market demand.
- A candidate library match does not prove correctness, licensing compatibility, or safety.
- A successful build or generated test file does not prove that an implementation is production-ready.
- Hardware guides require exact-part datasheets, compatibility checks, appropriate engineering tests, and qualified review where applicable.
- A SHA-256 manifest provides integrity evidence; an HMAC can provide keyed integrity verification when used correctly. Neither makes readable software uncopyable.
- The first-release RVX compiler produces declarative JSON IR; encrypted WASM compilation is not implemented in this revision.
- A generic generated scaffold cannot guarantee a correct implementation for every possible invention from an arbitrary one-line demand.

Software that can be read or run cannot be guaranteed to be literally uncopyable or untouchable. Access controls, integrity checks, licensing, and deployment-specific protections have distinct purposes and limitations.

## 16. Human Ownership and Release Policy

All generated inventions remain staged until the repository owner reviews and approves them.

Before integration, review the demand, evidence, capability plan, generated source, dependencies, tests, API contract, security requirements, and applicable hardware considerations.

After approval, implementation and release must proceed through a controlled development workflow with the required validation and deployment approvals.

**Genesis proposes. Humans review. Controlled changes integrate. Verified releases activate.**
