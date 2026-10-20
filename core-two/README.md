# USECT-TWO — Infinite Mind (Core-Two)

Core-Two is an additive, model-free improvement engine for the existing Core-One Genesis engine. It imports Core-One's `genesis` package and Core-Zero's offline RV Lang compiler and benchmark comparator; it does not clone, overwrite, or auto-merge either core.

## Honest capability boundary

- Observes Core-One invention evidence/state and Core-Zero audit/healing evidence read-only. Runtime metrics are written only beneath `core-two/`.
- Builds ten proposal-only library mutations, runs deterministic in-process benchmarks, and compiles/tests each fixed candidate in a disposable offline Go module with bounded process time. The `offline_vault` graph benchmark is a synthetic fallback when no historical inventions exist.
- Applies Core-Two's fail-closed rules plus Core-One's existing Guardian. The repository includes `core-zero/guardian/rules.yaml` and `core-zero/guardian/worldwide_rules.yaml`; deployments must verify both policy files are present, valid, and enforced. If a ZERO policy file is missing or invalid, evolution fails closed. If a ZERO policy file is present but invalid, evolution fails closed.
- Emits evidence and `AWAIT_MERGE.md`; it never writes to Core-One libraries/inventions or Core-Zero code, executes repository-sourced invention code, merges code, or actuates hardware. Its ten fixed, import-allowlisted candidate templates run `go test` in temporary offline subprocesses. This is bounded process isolation, not an OS-level sandbox.
- RVX protection proposals use AES-GCM with an external key supplied at runtime. This improves confidentiality and tamper detection for protected artifacts; no software can truthfully guarantee that readable source or binaries are literally “uncopyable forever.” Existing Core-One RVX is not changed by this module.
- Real BOM cost, human merge time, and historical time-to-invent remain `null` until the source evidence actually records them. Fixture results are labeled as synthetic and must not be presented as verified market prices or production improvements.

## Run

Go 1.23+ is required. From repository root, use `go -C core-two test ./...` and `go -C core-two vet ./...`.

Run Mind independently (default loopback listener):

```powershell
go -C core-two run ./cmd/revela-mind --daemon -repo-root .. -listen 127.0.0.1:8782
```

Build the composition launcher and start ZERO + ONE + TWO together:

```powershell
go -C core-two build -o ./revela ./cmd/revela
go -C core-two build -o ./revela-mind ./cmd/revela-mind
./core-two/revela --daemon -repo-root .
```

The combined launcher builds/starts the existing binaries without editing their source. Defaults are ZERO `127.0.0.1:8780`, ONE `127.0.0.1:8781`, and TWO `127.0.0.1:8782`. Set `USECT_ZERO_ADMIN_TOKEN`, `GENESIS_ADMIN_TOKEN`, and `MIND_ADMIN_TOKEN` in the runtime environment. Mind API mutations fail closed until `MIND_ADMIN_TOKEN` is configured; the combined launcher refuses to bind Mind outside loopback without it. Keep all listeners on loopback unless TLS, authentication, rate limiting, and a deployment review are in place.

The provider mesh reuses `REVELACODE_PROVIDER_URL` and `REVELACODE_PROVIDER_KEY`, the same provider credential names used by Core-One. `/v1/mind/key` only reports/queues a human-reviewed key request; it never returns or mints a provider secret.

## Recursive improvement and operational mirror

The Mirror maintains byte cursors for Core-Zero audit events and Core-One event/Guardian logs, summarizes new events without exposing raw log lines, and probes the existing ZERO/ONE health endpoints read-only. Core-Two request telemetry counts tool routes without recording query strings, headers, bodies, or client IPs. The learning ledger accepts explicit, authenticated owner feedback (`merged`, `rejected`, `reverted`, or `needs_work`); the latest decision per evolution adjusts future deterministic ranking, but can never bypass tests/Guardian or trigger a merge. A `merged` outcome requires an evidence reference and remains a human attestation, not an independently verified Git event.

## Endpoints

- `GET /v1/mind/health`
- `POST /v1/mind/evolve`
- `GET /v1/mind/metrics`
- `GET /v1/mind/evolutions`
- `GET /v1/mind/learning` — deterministic human-feedback ledger
- `POST /v1/mind/feedback` — record a reviewed merged/rejected/reverted/needs-work result; Mind token required
- `GET /v1/mind/tools/{name}/improvement`
- `GET /v1/mind/stream` (SSE)
- `GET|POST /v1/mind/key`
- `/v1/genesis/*` is proxied to the existing Core-One service; `/v1/zero/*` is a namespaced proxy to the existing Core-Zero service. Proxy writes require Mind's own auth gate in addition to the upstream service's normal controls.

`openapi.yaml` is a Core-Two merged gateway contract. It records the existing Core-One and Core-Zero route families, preserves Core-Zero's original `/v1/*` contract as upstream, and adds the Mind endpoints and `/v1/zero/*` aliases. The original OpenAPI documents remain untouched.

## Self-model and integration directions

```text
                    RevelaCode provider
                 shared URL + key environment
                    ▲                 │
                    │                 ▼
┌───────────────────┴───────────────────────────────────────┐
│                    REVELACODE ECOSYSTEM                    │
│                                                            │
│  Core-Zero (BODY)  ◄──── safety/evidence ────► Core-One    │
│  healing + audit                            (WOMB)         │
│        ▲                                  Genesis invents  │
│        │                                     proposals      │
│        │                                         │          │
│        └──────── audit/health observation ──────┤          │
│                                                  ▼          │
│                                        Core-Two (MIND)     │
│                                  Mirror → Mutator → Judge   │
│                                   │                │       │
│                                   └─ evidence ──────┘       │
│                                            │               │
│                                AWAIT_MERGE only             │
│                                            │               │
│                               human owner review ──────────┘
└────────────────────────────────────────────────────────────┘
```

Core-Two imports Core-One's `genesis` library and Core-Zero's `mind` and `radar` libraries using Go module replacements to the sibling modules. It reads existing evidence only; all new state and candidate artifacts are written beneath `core-two/`. It does not duplicate the Genesis engine, Eye, or Library Forge.

## Current evidence boundary

The inspected baseline main commit contained `core-one/inventions/README.md` but no historical invention `evidence.json`, and the repository now includes `core-zero/guardian/rules.yaml` plus `core-zero/guardian/worldwide_rules.yaml`. Accordingly `research_evidence.json` reports zero observed production inventions and `null` production averages. The committed `offline_vault` result is a synthetic acceptance fixture; it reports only graph-traversal-phase timings and is not a claim about end-to-end invention time or real BOM savings. A dedicated Core-Zero Guardian policy is still a deployment/review gap.

The provider route `/v1/mind/provider/heartbeat` is a contract for the configured RevelaCode provider. Core-One and Core-Two reuse `REVELACODE_PROVIDER_URL` and `REVELACODE_PROVIDER_KEY`; the inspected code does not establish that this Mind-specific provider route already exists in a deployed provider. Provider notifications are best-effort metadata only, and the request never transmits secrets, full source files, or user prompts. HTTP telemetry records only route/method/status/duration and matched tool name; it excludes request headers, body, query strings and client IP. Explicit human feedback, not automated assumptions, informs future deterministic ranking. Non-loopback provider URLs must use HTTPS.

## Acceptance evidence

See [`ACCEPTANCE_REPORT.md`](ACCEPTANCE_REPORT.md) for the test matrix, source-tree findings, synthetic benchmark scope, and the outstanding real-module/Guardian-policy verification limits.
