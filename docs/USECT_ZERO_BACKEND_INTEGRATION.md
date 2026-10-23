# USECT-ZERO backend integration

The Flask backend exposes the model-free Go core through a bounded gateway. The core remains an independent service: the adapter does not execute candidate code, auto-deploy changes, operate hardware, or substitute a paid AI model.

## Safe-by-default configuration

The gateway has a code-owned integration path. Availability comes from the real Go core health response; the legacy `USECT_ZERO_ENABLED` flag no longer controls it. If the core address is missing or the service cannot be reached, the gateway returns a configuration/unavailable status instead of pretending the integration is disabled.

For local development, build and start the core from the repository root:

```sh
go -C core-zero test ./...
go -C core-zero vet ./...
go -C core-zero build -o core-zero/usect-zero ./cmd/usect-zero

# Use the same long, random value for both processes. Do not commit it.
export USECT_ZERO_ADMIN_TOKEN='replace-with-a-long-random-secret'
./core-zero/usect-zero -mode serve -root . -listen 127.0.0.1:8780
```

For local development, set the core URL and the matching server-side admin token for the two local processes. If testing the RevelaAI brain tools locally, set the same random `USECT_ZERO_BRAIN_TOKEN` in both processes. Production does not require manually creating that brain token: the Render Blueprint generates it on the private core and links it to RevelaAI. The HTTP client uses a fixed 10-second connect/read timeout.

For a private Render service, `USECT_ZERO_URL` may instead be the internal `host:port` value supplied by a Blueprint `fromService.property: hostport` reference. The adapter validates that host/port value and adds the internal HTTP scheme. Keep the Go core private; do not point this variable at a public URL unless you have deliberately reviewed and secured that exposure.

## Render Blueprint

The repository's `render.yaml` now describes two services: the public Flask gateway (`revelaai-backend`) and private Go service (`usect-zero-core`). The backend receives the core's private host/port and the same server-side admin token through Render service references. The Go service stores runtime state under `/var/data/usect-zero`, backed by a persistent disk, so key requests, issued-key records, approvals, evidence and audit logs survive routine restarts/redeployments.

- Both services must be in the same Render workspace and region for private networking.
- The private Go service and persistent disk use paid Render resources (`starter` plan and 1 GB disk in this Blueprint). Review the current cost/plan in Render before syncing the Blueprint.
- After syncing and deploying, verify `GET /api/usect-zero/health` returns HTTP 200, then reload the admin key-request and issued-key views.
- The new persistent store starts empty. Records that existed only in a previous ephemeral or unreachable core instance are not automatically migrated; preserve/export them from that instance first if it is still available.


The local HTTP URL above is suitable only when both processes share the same host/network namespace. In production, the Render Blueprint supplies `USECT_ZERO_URL` through the private-service reference; Do not expose the Go admin endpoints directly to the public internet. If the service crosses an untrusted network, use TLS and network access controls.

The backend's `USECT_ZERO_ADMIN_TOKEN` must match the Go core secret. The Flask route only sends it after the existing authoritative platform-admin check succeeds. Do not send this token from the browser. Never forward the frontend's bearer JWT to the Go service.

## Production readiness checklist

- Put the Go service on a private network. Do not publish its admin-token endpoints directly.
- Configure gateway/ingress rate limits for the public `POST /api/usect-zero/keys/request` route before accepting external traffic. The adapter bounds payloads but does not implement a shared, multi-instance rate limiter.
- The current Go core persists key requests, issued-key hashes, baseline, evidence and audit events as files under `core-zero/state/`, `core-zero/evidence/` and `core-zero/audit_log/`. On a host with ephemeral storage, those records can be lost on restart/redeploy. Use persistent storage with restricted permissions and backups, or move the storage layer to a durable database before production key issuance.
- Sync the Render Blueprint so the private service address and generated credentials are linked. Do not add a manual enable flag or timeout override. Keep the admin token separate from the generated brain token.

## Backend routes

Mounted under `/api/usect-zero`:

| Backend route | Core route | Access boundary |
|---|---|---|
| `GET /health` | `GET /v1/health` | Public; absolute repository path is removed |
| `POST /keys/request` | `POST /v1/keys/request` | Public intake; request stays pending, no key issued |
| `GET /keys/requests` | `GET /v1/keys/requests` | Existing authoritative platform-admin check |
| `GET /keys/issued?status=active` (also `revoked` or `expired`) | `GET /v1/keys/issued` | Platform admin + server-side admin token; metadata only, no key hashes or raw secrets |
| `POST /keys/requests/{id}/approve` | Core approval route | Platform admin + server-side admin token + explicit `ISSUE_KEY` confirmation |
| `POST /keys/issued/{id}/revoke` | Core revocation route | Platform admin + server-side admin token + explicit `REVOKE_KEY` confirmation |
| `GET /scan` | `GET /v1/scan` | Go core validates the external developer key and `scan:read` scope |
| `GET /diagnostics` | `GET /v1/diagnostics` | Go core validates `scan:read`; bounded runtime, storage and baseline-drift report; no repository mutation |
| `POST /heal/baseline` | Core baseline route | Platform admin + server-side admin token |
| `POST /heal/proposals` | `POST /v1/heal/proposals` | Go core validates `heal:propose` scope |
| `POST /heal/proposals/{id}/approve` | Core restore approval route | Platform admin + server-side admin token and core confirmation rules |
| `GET /assemble/templates` | `GET /v1/assemble/templates` | Go core validates `scan:read`; read-only versioned catalog and template validation status |
| `GET /assemble/boards` | `GET /v1/assemble/boards` | Go core validates `scan:read`; generic board-family profiles, voltage metadata and explicit unverified pin-map status |
| `POST /assemble` | `POST /v1/assemble` | Go core validates `assemble:propose`; optional exact `template_version`, registry/BOM/wiring validation and review-only manifest |
| `POST /radar/compare` | `POST /v1/radar/compare` | Go core validates `radar:compare` scope |
| `POST /bridge/plan` | `POST /v1/bridge/plan` | Go core validates `bridge:propose` scope |
| `POST /mind/compile` | `POST /v1/mind/compile` | Go core validates `mind:compile` scope |

The diagnostics report samples at most 50 paths per drift category while retaining full counts, omits absolute repository roots, and only probes USECT-ZERO data directories with temporary files that are removed immediately. Drift is informational and is never automatically repaired. Assembly is driven by the versioned in-code curated registry; invalid or unregistered target/version pairs are rejected, BOM wire quantities are checked against connection count, pin endpoints and connection references are validated, and the generated manifest records that hardware has not been verified. Board profiles are generic family-level references rather than exact manufacturer pin maps. If a template includes manufacturer-backed supply and logic limits, declared voltage conflicts block generation; missing limits or datasheet review are marked for human verification. These checks do not certify hardware compatibility. Existing files are not overwritten. Requests and responses are bounded; the Flask blueprint exposes an explicit set of routes mapped to `/v1/` endpoints, and the client rejects non-versioned or traversal paths; redirects are not followed; HTTP calls have short timeouts. The adapter forwards only `X-API-Key` for external developer operations. Admin operations use a separately configured server-side token and do not forward user Authorization headers.

## What this first backend pass does not do

- It does not start or compile the Go process inside the Flask worker.
- It does not create a Render service or change deployment infrastructure automatically.
- The React admin console consumes the Flask gateway; the core service itself does not serve a separate admin dashboard.
- It does not make the existing Meta-Engineer or Brain OS routes depend on USECT-ZERO.

Deploy the Go core as a private service and sync the Render Blueprint. The Blueprint supplies the private service address and links generated service credentials automatically. The integration has no manual enable flag, manual brain-key, or timeout override; missing wiring is reported as a real configuration error.


## Deployment wiring (automatic)

The Render Blueprint is the source of truth for the RevelaAI-to-USECT-ZERO connection. Syncing
`render.yaml` links the private core address and its generated credentials automatically; no
manually created `USECT_ZERO_BRAIN_API_KEY`, enable flag, or timeout variable is required.

The generated `USECT_ZERO_BRAIN_TOKEN` is a separate machine identity, not an admin token or a
human-issued developer key. The Go API accepts it only for `scan:read`, `heal:propose`,
`assemble:propose`, `radar:compare`, `bridge:propose`, and `mind:compile`, with per-scope
rate limiting. It cannot approve key requests, apply recovery, perform admin actions, or authorize
hardware actuation. The admin token remains separate and is linked from the core service by the
Blueprint. Health is determined by the real `/v1/health` response; a missing service address or an
unreachable core remains an explicit error rather than a synthetic healthy status.

The HTTP client uses a fixed 10-second connect/read timeout. The legacy `USECT_ZERO_ENABLED` and
`USECT_ZERO_TIMEOUT_SECONDS` variables no longer control runtime behavior.
