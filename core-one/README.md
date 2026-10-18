# REVELA GENESIS — USECT-ONE / CORE-ONE

**Purpose:** a standalone, model-optional invention engine for RevelaAI. Genesis observes research and repository signals, turns approved demands into staged software/hardware-tool proposals, forges reusable library contracts and model-family blueprints, documents interfaces, and leaves every invention awaiting owner review.

This module is deliberately additive. It does not modify `core-zero`, the existing RevelaAI brain, or frontend files. The Go module has no third-party Go dependencies.

## Core-One reliability upgrade — v0.2.0-alpha

This upgrade hardens the foundation before adding broader invention capabilities:

- Research adapters and the model adapter honor request cancellation; independent research sources run concurrently under a shared deadline.
- Model output may enrich bounded descriptive metadata, but cannot rename the invention, reclassify its industry/category, or remove a demand-derived hardware guide requirement.
- Guardian fails closed if the local policy file is missing, oversized, or missing mandatory protection categories. Research findings are now screened as well as individual source records.
- Queue records are atomically claimed, interrupted claims are recovered, cancellation returns active work to the pending queue, and persistence errors are surfaced through daemon events rather than silently discarded.
- The service exposes `GET /v1/genesis/status` for queue counts, invention totals, last research file, model/offline mode, and Guardian readiness.
- The SSE stream clears the server's normal write deadline so it can remain connected beyond the standard HTTP response timeout.
- A dedicated GitHub Actions workflow runs Go tests with the race detector, `go vet`, a CLI build, and offline generation/compile checks for emitted Go packages plus Python/JavaScript SDK syntax.

These checks raise confidence; they do not replace an integration review or a production deployment test.

## Module upgrade — Capability Graph + Requirement Planner (v0.3.0-alpha)

Genesis now builds a deterministic capability graph and requirement plan for every accepted invention before creating files. The graph maps demand-derived requirements to Core-One contract primitives, surfaces metadata-compatible reusable libraries as **unverified candidates**, records dependency edges, identifies unresolved capabilities, and generates explicit acceptance criteria and residual risks.

Every staged invention receives `capability_plan.json`; the invention response returns its plan path and coverage summary. The host API exposes `GET /v1/genesis/tools/{name}/capability_plan`. The generated tool OpenAPI proposal also includes a capability-plan route.

Important interpretation: “native contract available” means a reusable planning/guardrail contract exists, not that a domain-specific production implementation exists. Candidate library matching does not prove correctness, compatible licensing, or safe behavior. The plan's unresolved items must be assigned implementation and test work before release.

## What it does today

- **Eye:** research cycles query GitHub repository search, arXiv, NVD CVE search, and a Kenya-focused RSS query. Each evidence packet also contains direct research links for WIPO PATENTSCOPE, ISO, KEBS, Jumia Kenya, Mouser, and DigiKey. Direct links are leads, not verified prices, patent clearance, legal advice, standards compliance, or proof of market demand. Repository scanning fingerprints repeated TODO/FIXME/workaround lines without executing source code or copying whole source files into model prompts.
- **Capability Graph + Requirement Planner:** runs before file staging; extracts general and demand-specific requirements, ranks existing library metadata, draws requirement/dependency edges, lists uncovered capabilities, and adds acceptance checks. It is deterministic and works without a model. Every library reuse is labelled unverified until separately tested.
- **Genesis:** accepts arbitrary text demands and derives a bounded generic tool specification without a model. It creates reviewable Go scaffolds, tests, an OpenAPI proposal, hardware guide, evidence bundle, merge checklist, and Go/Python/JavaScript SDK proposals. Tool-specific production logic still requires validated requirements and implementation work; the engine does not pretend a generic template is a finished factory controller, medical device, or surveillance deployment.
- **Library Forge:** creates a reusable proposal-only Go contract library with driver, tests, and documentation.
- **Model Forge:** creates a YAML blueprint for a new tool family. A configured model endpoint can enrich metadata; source code emitted by a model is never executed or copied into runtime code files.
- **Expand:** records a deduplicated expansion plan and, for classified non-general domains, a starter industry taxonomy. When the configured file-count threshold is reached, new expansion plans are staged under `core-one/gen2/` rather than changing the running engine.
- **Guardian:** screens demands before research, and screens research/model metadata before generation. Prohibited demands are rejected before invention/library/model directories are created; blocked events are recorded in `guardian/blocked.log`. Pattern screening is a fail-closed safety layer, not a perfect semantic classifier.
- **Provider loop:** optional daily heartbeat to a configured RevelaCode provider. Inbound demands are queued through the local Guardian; inbound graph/law updates remain review proposals and cannot weaken local rules.
- **RVX:** a 20-keyword declarative DSL skeleton that compiles to bounded JSON intermediate representation. It does **not** compile to encrypted WASM in this revision.
- **Human ownership:** files are staged under `core-one/inventions/<name>/` with `AWAIT_MERGE.md`. Genesis never commits, merges, installs, executes, flashes hardware, or activates a new tool automatically.

## Architecture

```text
               optional existing model endpoint
                          │ specification only
                          ▼
Eye ──research/evidence──> Genesis ──> Library Forge ──> Model Forge
  ▲                           │                              │
  │                           ▼                              ▼
  └──── 60s scan/threshold ─ Expand proposals <──────── Guardian
                                   │                         ▲
                                   ▼                         │ re-check
                         Endpoint + SDK proposals ──────────┘
                                   │
                                   ▼
                       await owner review / merge
                                   │
                                   ▼
                   optional RevelaCode provider loop
```

Guardian also runs **before** research and again on research/model-derived input; the final stage in the drawing is not the only safety check. Tool-specific paths described by generated OpenAPI are proposals until an owner merges the files and explicitly registers an implementation with the host service.

## Standalone setup

Requires Go 1.23 or newer. From the repository root:

```powershell
cd core-one
go test -race ./...
$env:GENESIS_OFFLINE = "1"
go run ./cmd/genesis -mode invent -repo-root .. -demand "Create tool: offline file vault"
```

The offline run does not call the internet or require a model. It creates a package under `../core-one/inventions/offline_file_vault/`, a contract library, a model blueprint, and evidence/expansion records. Remove or review generated artifacts deliberately; the generator will not overwrite an existing invention directory.

Run the API and daemon locally (for the stricter acceptance pass, run `go test -race ./...` and `go vet ./...` first):

```powershell
cd core-one
$env:GENESIS_ADMIN_TOKEN = "replace-with-a-long-random-secret"
go run ./cmd/genesis -mode serve -repo-root .. -listen 127.0.0.1:8781 -interval 60s
```

The daemon scans immediately on startup and then every 60 seconds by default. A queued demand is processed on the next cycle; `POST /v1/genesis/invent` processes synchronously. The default listener binds to loopback. When a non-loopback client connects, the configured Genesis token is required (except for the minimal health check). Do not expose the service directly to the public internet without TLS, a trusted proxy, rate limits, and deployment review.

## Acceptance checks

1. **Automatic queue:** start the server with `-interval 1s`, then `POST /v1/genesis/queue` with `{"demand":"Create tool: offline file vault"}`. The daemon should research, create the library/model/tool proposal, and move the queue record to `await_merge` on the next scan.
2. **Demand-driven hardware proposal:** `POST /v1/genesis/invent` with `{"demand":"CCTV"}` produces `core-one/inventions/cctv_smart/` plus a generic, privacy-aware hardware integration guide. No CCTV invention is shipped in advance.
3. **Block harm:** `POST /v1/genesis/invent` with `{"demand":"weapon"}` returns HTTP 403, adds an audit line to `guardian/blocked.log`, and does not create an invention package or library.

## HTTP contract

The full local contract is in `openapi.yaml`:

- `GET /v1/genesis/health`
- `GET /v1/genesis/status` — queue, Guardian, research and invention snapshot
- `POST /v1/genesis/invent` — research and generate a single proposal now
- `POST /v1/genesis/queue` — durable demand queue for the daemon
- `GET /v1/genesis/tools`
- `GET /v1/genesis/tools/{name}`
- `GET /v1/genesis/tools/{name}/hardware_guide`
- `GET /v1/genesis/tools/{name}/capability_plan` — view graph, candidate libraries, gaps and acceptance checks
- `GET /v1/genesis/stream` — server-sent engineering events
- `GET|POST /v1/genesis/key` — provider-key request/status only; no bearer secret is minted or disclosed here
- `POST /v1/rvx/compile` — RVX to bounded JSON IR

## Optional existing-model adapter

Genesis runs without any model. To let it use an existing model service for **specification metadata only**, set:

- `GENESIS_MODEL_BASE_URL` — an OpenAI-compatible base URL or full `.../chat/completions` endpoint. If the base URL ends in `/v1`, Genesis appends `/chat/completions`; otherwise it appends `/v1/chat/completions`.
- `GENESIS_MODEL_NAME` — the model identifier accepted by that service.
- `GENESIS_MODEL_API_KEY` — optional server-side credential; never expose it in frontend settings or commit it.

The provider must speak the OpenAI-compatible chat-completions JSON format. If RevelaAI's currently deployed model route uses a different contract, add a small adapter under this module and configure its local endpoint; Genesis does not assume an undocumented existing URL. If the model is unavailable or returns malformed metadata, the deterministic model-free fallback remains available.

## Optional RevelaCode provider heartbeat

Set `REVELACODE_PROVIDER_URL` and, if required, `REVELACODE_PROVIDER_KEY`. Genesis sends a heartbeat to `<URL>/v1/genesis/provider/heartbeat` at startup and every 24 hours (override with `REVELACODE_PROVIDER_INTERVAL`). That host route is a documented integration contract, not claimed to exist in the current RevelaCode backend; the backend needs to implement it before provider synchronization can work. Standalone mode remains functional when the provider is absent.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `GENESIS_OFFLINE=1` | Skip online research and use recorded search links only | unset (online research attempts) |
| `GENESIS_ADMIN_TOKEN` | Required for remote API access and remote mutations | unset; local loopback only |
| `GENESIS_MODEL_BASE_URL` | Optional OpenAI-compatible model adapter | disabled |
| `GENESIS_MODEL_NAME` | Existing model id | `existing-revelaai-model` |
| `GENESIS_MODEL_API_KEY` | Server-side model token | empty |
| `GENESIS_SIGNING_KEY` | Optional HMAC-SHA256 integrity-manifest signing key | unsigned SHA-256 manifest |
| `GENESIS_WORKAROUND_THRESHOLD` | Identical repository workarounds before auto-proposal | `6` |
| `GENESIS_DEMAND_THRESHOLD` | Repeated evidence-topic hits before auto-proposal | `5` |
| `GENESIS_MAX_CORE_FILES` | File-count threshold that routes expansion into `gen2/` | `5000` |
| `REVELACODE_PROVIDER_URL` | Optional provider service base URL | disabled |
| `REVELACODE_PROVIDER_INTERVAL` | Optional heartbeat interval | `24h` |

## Security and truthful limits

Software cannot be made literally uncopyable or untouchable once someone can read or run it. This module supports least-privilege service access, audit logs, review gates, SHA-256 artifact manifests, and optional HMAC integrity checks; these are tamper-evidence and access controls, not a promise of copy prevention. A signed WASM compiler, licensing service, threat-model review, and deployment-specific controls remain future work.

The engine can research, compare, derive a generic specification, compose reusable contracts, generate SDK/API/hardware-guide proposals, and detect simple repository signals without a model. A genuinely novel arbitrary invention still requires correct requirements, trusted domain evidence, implementation-specific algorithms, validation, and human review. No deterministic tool can truthfully guarantee every possible invention from a one-line demand alone.
