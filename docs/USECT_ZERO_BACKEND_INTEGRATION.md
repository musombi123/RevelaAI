# USECT-ZERO backend integration

The Flask backend exposes the model-free Go core through a bounded gateway. The core remains an independent service: the adapter does not execute candidate code, auto-deploy changes, operate hardware, or substitute a paid AI model.

## Safe-by-default configuration

The adapter is disabled unless `USECT_ZERO_ENABLED=true`. Until the Go service is built and reachable, existing backend behavior remains unchanged.

For local development, build and start the core from the repository root:

```sh
go -C core-zero test ./...
go -C core-zero vet ./...
go -C core-zero build -o core-zero/usect-zero ./cmd/usect-zero

# Use the same long, random value for both processes. Do not commit it.
export USECT_ZERO_ADMIN_TOKEN='replace-with-a-long-random-secret'
./core-zero/usect-zero -mode serve -root . -listen 127.0.0.1:8780
```

Set these variables in the Flask backend environment:

```text
USECT_ZERO_ENABLED=true
USECT_ZERO_URL=http://127.0.0.1:8780
USECT_ZERO_ADMIN_TOKEN=<same secret configured for the Go core>
USECT_ZERO_TIMEOUT_SECONDS=5
```

The HTTP URL above is suitable only when both processes share the same host/network namespace. For production, run the Go core as a private internal service and set `USECT_ZERO_URL` to its private HTTP(S) address. Do not expose the Go admin endpoints directly to the public internet. If the service crosses an untrusted network, use TLS and network access controls.

The backend's `USECT_ZERO_ADMIN_TOKEN` must match the Go core secret. The Flask route only sends it after the existing authoritative platform-admin check succeeds. Do not send this token from the browser. Never forward the frontend's bearer JWT to the Go service.

## Backend routes

Mounted under `/api/usect-zero`:

| Backend route | Core route | Access boundary |
|---|---|---|
| `GET /health` | `GET /v1/health` | Public; absolute repository path is removed |
| `POST /keys/request` | `POST /v1/keys/request` | Public intake; request stays pending, no key issued |
| `GET /keys/requests` | `GET /v1/keys/requests` | Existing authoritative platform-admin check |
| `POST /keys/requests/{id}/approve` | Core approval route | Platform admin + server-side admin token + explicit `ISSUE_KEY` confirmation |
| `POST /keys/issued/{id}/revoke` | Core revocation route | Platform admin + server-side admin token + explicit `REVOKE_KEY` confirmation |
| `GET /scan` | `GET /v1/scan` | Go core validates the external developer key and `scan:read` scope |
| `POST /heal/baseline` | Core baseline route | Platform admin + server-side admin token |
| `POST /heal/proposals` | `POST /v1/heal/proposals` | Go core validates `heal:propose` scope |
| `POST /heal/proposals/{id}/approve` | Core restore approval route | Platform admin + server-side admin token and core confirmation rules |
| `POST /assemble` | `POST /v1/assemble` | Go core validates `assemble:propose` scope |
| `POST /radar/compare` | `POST /v1/radar/compare` | Go core validates `radar:compare` scope |
| `POST /bridge/plan` | `POST /v1/bridge/plan` | Go core validates `bridge:propose` scope |
| `POST /mind/compile` | `POST /v1/mind/compile` | Go core validates `mind:compile` scope |

Requests and responses are bounded; only known `/v1/` paths are allowed; redirects are not followed; HTTP calls have short timeouts. The adapter forwards only `X-API-Key` for external developer operations. Admin operations use a separately configured server-side token and do not forward user Authorization headers.

## What this first backend pass does not do

- It does not start or compile the Go process inside the Flask worker.
- It does not create a Render service or change deployment infrastructure automatically.
- It does not integrate a frontend dashboard.
- It does not make the existing Meta-Engineer or Brain OS routes depend on USECT-ZERO.

Deploy and test the Go core as a private service first, then enable the Flask adapter with the environment variables above. Keep the feature flag off until the private core service and secret are configured.
