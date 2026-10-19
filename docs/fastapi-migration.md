# Flask-to-FastAPI migration

## Current branch status

The migration branch uses FastAPI/Uvicorn as the public ASGI entry point. Native
FastAPI routers are registered before a temporary root-mounted
`starlette.middleware.wsgi.WSGIMiddleware` adapter, which currently preserves
remaining legacy Flask endpoints. The public Render blueprint targets
`uvicorn asgi:app` while this branch is under review; it has not been merged
into `main`.

**This is not yet a full Flask removal.** Do not merge/deploy as a finished
migration while the WSGI adapter and the Flask application import remain.

## Native FastAPI route groups now registered

- System endpoints: `GET /`, `GET /capabilities`, `GET /health`,
  `GET /ready`, `POST /chat`, generated image delivery, and generated audio
  delivery.
- Primary authenticated chat: `POST /api/chat` and `POST /api/chat/`.
- Live Vision: `POST /api/vision/analyze`.
- Local Living Brain: `/api/revelaai/v2/brain/chat`,
  `/api/revelaai/v2/vision/describe`, and `/api/revelaai/v2/health`.
- Hub persona engine: `/api/revelaai/hubs/` and
  `/api/revelaai/hubs/respond`.
- Explainability: `POST /`.
- Smart Memory: `POST /api/memory/chat`, `GET /api/memory/{user_id}`,
  `POST /api/memory/ideas`, `POST /api/memory/ideas/{idea_id}/implementation`,
  `GET /api/memory/ideas/{user_id}`, `DELETE /api/memory/useless/{user_id}`,
  and `GET /api/memory/{user_id}/history`.
- Core Mesh: dashboard, Genesis invention proposal, Infinite Mind evolution
  proposal, unknown-topic teaching, known-topic list, and operator-only
  knowledge publication.
- WhatsApp webhook verification and message notifications.

Smart Memory's data-access/filtering helpers now live in
`services/memory_store.py`, without Flask imports. Native chat and Vision use
FastAPI-compatible authentication helpers rather than invoking Flask's request
global. The database remains the separate `revelai` database; signed identity
and the protected RevelaCode user-verification check are retained.

## Remaining Flask bridge inventory

The following paths or router families still use the WSGI compatibility app:

- Main multimodal processing endpoints: `POST /ai`, `POST /ai/stream`, and
  `POST /voice`. These are large handlers involving file/audio parsing,
  session state, AI orchestration, streaming responses, and action handling.
- Meta-Engineer (`/api/meta-engineer`).
- USECT-ZERO (`/api/usect-zero`).
- SCI (`/api/sci`).
- AGI (`/api/agi`).
- Automation Fabric (`/api/automation-fabric`).
- Remaining memory/research/user legacy blueprint declarations and other
  unported endpoints. The older memory handlers remain available in the Flask
  application, but the registered paths listed above are intercepted by the
  native FastAPI router first.
- The legacy Flask application is still imported during ASGI startup to provide
  existing configuration, in-memory session state, feature registries, and
  the fallback adapter. Therefore Flask and `flask-cors` must remain installed.

## Compatibility and security rules

1. Preserve endpoint paths, HTTP methods, status codes, response envelopes, and
   error codes unless an existing collision/bug is explicitly documented and
   deliberately fixed.
2. Preserve trusted CORS origins, credentials behavior, request IDs, baseline
   security headers, upload bounds, and the reversible SCI throttle policy.
3. JWT authentication must remain fail-closed. Core Mesh invention/evolution
   and knowledge publication remain restricted to configured operator user IDs.
   Core tokens must remain server-side.
4. Smart Memory must continue to verify the signed user and the authoritative
   RevelaCode user record, isolate records by user ID, and never query
   `revelacode.users` directly.
5. Vision frames are validated, bounded, processed ephemerally, and not persisted
   by the Vision endpoint.
6. Submitted code and proposals are records for review; they must not be
   executed or automatically merged/deployed by this migration.

## CI and deployment

The branch's migration workflow installs the dependencies, compiles the ASGI
entry point and migration test suite, and runs endpoint/auth/CORS regression
checks. Checks for the newest branch head must pass before the draft PR is made
ready. The tests in this phase do not prove every remaining Flask endpoint has
been migrated.

Render starts the gateway with:

```sh
uvicorn asgi:app --host 0.0.0.0 --port $PORT --workers 1
```

A single worker avoids changing process-local session memory during this
migration. The private Go Core-Zero, Genesis/Core-One, and Infinite-Mind/Core-Two
service wiring and server-side credentials remain unchanged.

## Exit criteria for declaring the migration complete

- Port every remaining direct handler and blueprint to FastAPI routers or
  framework-independent services.
- Eliminate URL collisions and test each endpoint's happy path, malformed input,
  authentication/authorization, provider failure, and response schema.
- Move session/state/configuration dependencies out of `app.py` and remove the
  compatibility bridge.
- Remove all production imports of Flask/Flask-CORS and remove those packages
  from `requirements.txt`.
- Run the full Python test suite and CI, validate the OpenAPI inventory, then
  deploy the finished branch and verify health/readiness, chat, vision, memory,
  Core Mesh, and the three private Go cores.
