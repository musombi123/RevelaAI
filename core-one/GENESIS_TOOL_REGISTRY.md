# Genesis signed tool registry and sandbox policy

This document describes the USECT-One / Genesis proposal-to-tool lifecycle. Creating an invention is not the same as testing, signing, activating, or executing it.

## Lifecycle

1. Guardian screens the incoming demand before research and generation. Research evidence, model-suggested metadata, and the generated manifest are screened before artifact publication. If policy cannot be loaded or any relevant review blocks the request, the process fails closed.
2. Each new invention contains `tool_manifest.json`, validated against `genesis/tool_manifest.schema.json`. Manifest risk tier is derived from permissions: hardware means Tier 2; network, filesystem, or secrets mean at least Tier 1; no such capabilities means Tier 0. A manifest cannot lower its tier.
3. The publish endpoint stages a copy of the candidate and runs its build/tests in a constrained sandbox. Docker is preferred; Bubblewrap is a fallback only when its namespaces and limits can be established. If neither runner can enforce the requested constraints, publish fails and no signature is created.
4. Only passing evidence bound to the exact manifest and candidate content hash is eligible for signing. Signed versions are append-only. The registry verifies the Ed25519 signature, content hash and evidence on reads and before activation/invocation.
5. Tier 0 may be activated automatically only after a passing sandbox run and successful signature. Tier 1 and Tier 2 require an explicit gateway owner action; the owner approval must match the exact artifact hash. Tier 2 additionally requires a one-use confirmation tied to that exact artifact and exact arguments at invocation time.
6. Deactivation only changes the active pointer. Rollback points to a prior verified signed version; it does not delete or rewrite version history.

## Sandbox boundary and limitations

The runner requests no network, a read-only root filesystem and candidate mount, a bounded temporary filesystem, non-root execution, dropped capabilities, no-new-privileges, CPU/memory/PID/time limits, and a stripped environment. Build/test logs, pass/fail state, artifact/manifest hashes and the requested isolation level are retained as evidence.

Isolation evidence uses names such as `docker_constraints_requested_host_enforcement_unverified` or `bubblewrap_constraints_requested_host_enforcement_unverified`. These names intentionally do not claim independently audited OS-level isolation. Container image availability, host kernel behavior and successful namespace enforcement still need to be verified on the actual deployment host.

At present, the runtime remains more restrictive than the manifest: invocations use no network, a read-only artifact mount, no passed host secrets and no direct hardware passthrough. The permission declarations drive approval tiers; they do not automatically grant unrestricted host access. A tool that genuinely needs network, writable filesystem, secrets or physical hardware requires an explicitly reviewed capability broker/runtime extension before it can perform those capabilities.

## Deployment environment variable names

Set these only as server-side Render environment variables. Do not place values in the repository, client bundle, logs or issue comments.

| Variable | Service | Purpose |
| --- | --- | --- |
| `GENESIS_ADMIN_TOKEN` | Genesis and gateway (gateway references Genesis service) | Server-to-server API authentication |
| `GENESIS_SIGNING_KEY` | Genesis | Base64-encoded Ed25519 32-byte seed or 64-byte private key |
| `GENESIS_REGISTRY_DIR` | Genesis | Persistent signed registry root; Render mounts the Genesis data disk here |
| `GENESIS_OWNER_APPROVAL_TOKEN` | Genesis and gateway | Separate owner-approval credential for Tier 1–2 activation/rollback |
| `GENESIS_ACTION_APPROVAL_TOKEN` | Genesis and gateway | Separate action-approval credential for Tier 2 confirmation |
| `GENESIS_OWNER_USER_IDS` | Gateway | Comma-separated identity allowlist of owners permitted to approve Tier 1–2 activation/rollback |
| `GENESIS_OFFLINE` | Genesis | Set to true for offline research fallback and operation |
| `GENESIS_MODEL_BASE_URL` | Genesis | Optional OpenAI-compatible model endpoint; blank disables model assistance |
| `GENESIS_MODEL_NAME` | Genesis | Optional model name for the existing Genesis adapter |
| `GENESIS_MODEL_API_KEY` | Genesis | Optional model credential; never exposed to candidates or gateway responses |
| `GENESIS_TRUST_PROXY_TLS` | Genesis | Explicit trust that Render terminates public TLS at its proxy |
| `GENESIS_BASE_URL` | Gateway and any existing authorized server-side consumers | Genesis service base URL |

The gateway's existing provider order remains Gemini, Hugging Face and MVI. The optional Genesis model adapter is not a new RevelaAI text provider. Empty `GENESIS_MODEL_BASE_URL` disables that adapter; Genesis remains deterministic/model-free. Render's Blueprint defines a persistent disk for the registry, but persistence and signing must be verified after the Blueprint is applied.

## Genesis API routes

All registry mutation routes require the Genesis server-to-server token; Tier 1–2 activation and rollback additionally require `X-Genesis-Owner-Approval`. Tier 2 confirmation additionally requires `X-Genesis-Action-Approval`.

- `GET /v1/genesis/registry/tools` — list verified versions and active pointers.
- `GET /v1/genesis/registry/tools/{name}` — list the tool's signed versions.
- `POST /v1/genesis/registry/tools/{name}/publish` — sandbox, then publish only if the candidate passes.
- `GET /v1/genesis/registry/tools/{name}/{version}/{artifact_hash}` — retrieve/verify one signed version.
- `POST /v1/genesis/registry/tools/{name}/{version}/{artifact_hash}/activate` — activate a verified version with required owner review.
- `POST /v1/genesis/registry/tools/{name}/{version}/{artifact_hash}/confirm` — issue a short-lived, one-use Tier 2 confirmation bound to the exact arguments.
- `POST /v1/genesis/registry/tools/{name}/{version}/{artifact_hash}/invoke` — execute only the active signed artifact through the sandbox runner.
- `POST /v1/genesis/registry/tools/{name}/deactivate` — deactivate without deleting historical versions.
- `POST /v1/genesis/registry/tools/{name}/rollback` — repoint to a verified earlier version; Tier 1–2 requires the exact hash approval.
- `GET /v1/genesis/telemetry/tool-calls` — bounded content-free invocation telemetry.

Telemetry records only time, tool, artifact hash, success/failure, latency and error class; it must not include user prompts, arguments, results or credentials. The endpoint is exposed for authorized consumption. Automatic Core-Two ingestion and a deployment-level telemetry retention policy remain separate integration work.

## Verification commands

Run from a clean repository checkout:

```sh
cd core-one
go test -race ./...
go vet ./...
go build ./cmd/genesis
```

Render's Blueprint builds from the repository root with:

```sh
go -C core-one build -o ./genesis-server ./cmd/genesis
```

CI verifies the root-checkout module replacement is available in its checkout. A live Render health check, persistent-disk behavior, owner credential setup, Docker/Bubblewrap availability, and host-level isolation are not implied by a passing CI run and must be verified on the actual service after deployment.


## RevelaAI FastAPI gateway contract

The public FastAPI service uses the following authenticated routes to call Genesis through server-to-server credentials. These are gateway paths, not direct Core-One paths:

- `GET /api/core-mesh/genesis/status`
- `GET /api/core-mesh/genesis/proposals`
- `GET /api/core-mesh/genesis/proposals/{name}` — returns a sanitized proposal summary and research counts; raw saved research snippets/findings are not forwarded.
- `GET /api/core-mesh/genesis/tools/{name}/hardware-guide?country=KE&lang=sw`
- `GET /api/core-mesh/genesis/tools/{name}/capability-plan`
- `POST /api/core-mesh/genesis/queue`
- `GET /api/core-mesh/genesis/key` and `POST /api/core-mesh/genesis/key/request` — request/approval status only; no credential is minted by the request endpoint.
- `POST /api/core-mesh/genesis/rvx/compile` — operator restricted.
- `GET /api/core-mesh/genesis/events?limit=100` — authenticated, bounded server-sent events.
- `GET /api/core-mesh/tools?provider=gemini|hf|mvi` — exposes active signed tool contracts in native Gemini function-declaration form or a provider-neutral prompt catalogue.
- `GET /api/core-mesh/tools/registry` — operator restricted, verified signed versions.
- `POST /api/core-mesh/tools/execute` — executes only the exact active signed version in Genesis; generated code never runs in the Python gateway.
- `POST /api/core-mesh/tools/{name}/publish` — operator restricted.
- `POST /api/core-mesh/tools/{name}/{version}/{artifact_hash}/activate` — operator restricted; Tier 1–2 also requires the signed-in user ID to appear in `GENESIS_OWNER_USER_IDS`.
- `POST /api/core-mesh/tools/{name}/{version}/{artifact_hash}/confirm` — operator and configured Genesis owner required; returns a one-use Tier 2 confirmation token only after server-side action approval and exact artifact/argument binding.
- `POST /api/core-mesh/tools/{name}/deactivate` and `POST /api/core-mesh/tools/{name}/rollback` — operator restricted; rollback of Tier 1–2 requires owner identity and the separate owner credential.

The Python gateway never connects directly to registry files or databases. It authenticates the user, performs operator/owner checks where needed, then calls the Core-One HTTP API using server-only credentials. Browser clients must not receive `GENESIS_ADMIN_TOKEN`, `GENESIS_OWNER_APPROVAL_TOKEN`, `GENESIS_ACTION_APPROVAL_TOKEN`, or `GENESIS_SIGNING_KEY`.
