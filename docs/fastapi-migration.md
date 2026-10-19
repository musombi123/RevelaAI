# Flask-to-FastAPI migration

## Current branch status

The migration branch boots through FastAPI/Uvicorn and registers native
`APIRouter` modules before a temporary `a2wsgi.WSGIMiddleware` compatibility
mount. Flask remains present only as the fallback for endpoints that have not
yet been ported, plus legacy configuration/state used by some adapters.

**This is not yet a full Flask removal.** Keep the compatibility bridge and
Flask dependencies until the main multimodal endpoints are ported, imports no
longer depend on Flask state, and the full regression suite passes.

## Native FastAPI route groups

- **System:** `GET /`, `GET /capabilities`, `GET /health`,
  `GET /ready`, dynamic-feature `POST /chat`, safe generated image serving,
  and generated audio serving.
- **Main multimodal AI:** `POST /ai`, including JSON and multipart document
  uploads, context/hub routing, image-generation requests, and the existing
  response schema. The provider/orchestration service remains shared with the
  legacy application while HTTP parsing and response handling are native.
- **AI streaming:** `POST /ai/stream`, native Server-Sent Events for text and
  image requests with explicit message/metadata/done/error events.
- **Voice:** `POST /voice`, bounded audio uploads, transcription, conversation
  processing, image requests and optional speech synthesis. `/voice/audio/*`
  serves generated audio through the native system router.
- **Primary authenticated AI chat:** `POST /api/chat` and `POST /api/chat/`.
- **Live Vision:** `POST /api/vision/analyze`; validates MIME type, decoded size,
  actual image format and pixel count, and does not persist frame bytes.
- **Local Living Brain:** `/api/revelaai/v2/brain/chat`,
  `/api/revelaai/v2/vision/describe`, and `/api/revelaai/v2/health`.
- **Hub persona engine:** `/api/revelaai/hubs/` and
  `/api/revelaai/hubs/respond`.
- **Explainability:** `POST /`, retaining the current root handler contract.
- **Smart Memory:** `POST /api/memory/chat`, `GET /api/memory/{user_id}`,
  `POST /api/memory/ideas`, `POST /api/memory/ideas/{idea_id}/implementation`,
  `GET /api/memory/ideas/{user_id}`, `DELETE /api/memory/useless/{user_id}`,
  and `GET /api/memory/{user_id}/history`. Persistence and filtering functions
  now live in `services/memory_store.py` with the separate `revelai` database.
- **Core Mesh and user-taught learning:** dashboard, Genesis proposal, Mind
  evolution proposal, unknown-topic teaching, reviewed shared knowledge list
  and operator-only publication.
- **AGI manifest and Brain OS:** `/api/agi/manifest`, `/api/agi/status`,
  plus all seven administrator-protected Brain OS status/outcome/routing/
  recovery/guardrail endpoints.
- **Sci-Core:** dashboard, shield status and scan, defensive research, disaster
  simulation, and safe hardware/software prototype proposal. All endpoints
  retain current platform-admin verification and safe, non-executing behavior.
- **USECT-ZERO:** health, activity, developer-key request/list/approval/revoke,
  diagnostics, scan, healing baseline/proposals/approval, assembly boards and
  templates, assembly, radar comparison, bridge plan, and Mind plan compilation.
  A caller's bearer token is never sent to the Go core; administrator commands
  use separate server-side credentials.
- **Meta-Engineer:** health, scan, propose, approve, idea status, audit list and
  pruning audit. Current platform administrator role is checked at the
  RevelaCode backend. Proposals remain review-only; this API does not auto-deploy
  or execute generated candidate code.
- **Automation Fabric:** hosted health, tools, consent grant/revoke, planning,
  plan status, explicitly approved execution and audit listing. Workspace paths
  remain isolated by a hash of the verified account ID.
- **WhatsApp:** webhook verification and incoming message handler.
- **Research:** `POST /api/research` searches a bounded set of configured RSS feeds; it does not fetch arbitrary user-supplied URLs.
- **Prototype users directory:** `POST /api/users` and `GET /api/users/{user_id}`. This remains an in-memory demo store, is disabled by default with `REVELAAI_ENABLE_PROTOTYPE_USERS_API=false`, and is not the authoritative RevelaCode account database.

The ASGI middleware retains the same trusted-origin CORS allowlist, credential
behavior, request IDs, security headers and reversible SCI throttle for native
routes. An unauthenticated request is not promoted to a verified user or admin.

## Remaining Flask bridge inventory

The main AI, streaming and voice HTTP endpoints are now registered natively.
Their provider orchestration, image generation, transcription and TTS helpers
still reuse selected functions from `app.py`; this is intentional transitional
service reuse, not evidence that Flask has been fully removed.

Remaining work is the legacy route inventory outside those native routers:
- Sector-specific legacy route handlers and older compatibility APIs remain on
  the Flask fallback intentionally. Their business logic is left untouched for
  the manual sector pass. The newly ported research/users APIs are native FastAPI
  routes under `/api/research` and `/api/users`; ambiguous legacy root paths are
  not treated as their public endpoints.
- Legacy request hooks, error handlers, and duplicated after-request logic.
- Service/configuration helpers that still import Flask globals (`request`,
  `g`, `current_app`) even where native adapters pass explicit request
  metadata. Move these to framework-neutral modules before deleting Flask.
- Resolve root-level legacy route collisions by comparing actual Flask route
  maps and preserving public endpoint contracts.

The legacy module is still imported by native system/chat modules for feature
registries, provider helpers and process-local session state. Those imports
must be moved to framework-neutral service/configuration modules before the
bridge can be removed.

## Migration requirements

1. Preserve endpoint paths, methods, status codes, response envelopes and error
   codes unless a known collision is intentionally fixed and documented.
2. Keep CORS origins, request IDs, forwarded-proxy behavior, error handling,
   body/upload limits, and security headers equivalent.
3. Keep JWT validation fail-closed. Admin-only routes must validate the current
   role through the authoritative RevelaCode backend rather than trusting a
   frontend role claim.
4. Keep Smart Memory isolated by verified user ID in the separate `revelai`
   database. Never access `revelacode.users` directly from RevelaAI.
5. Never forward end-user bearer tokens to private cores. Core credentials
   remain server-side; proposals and hardware/recovery actions remain
   human-gated.
6. Run endpoint tests for success, malformed payloads, unauthenticated and
   unauthorized requests, missing resources, and upstream failures.

## Deployment and verification

Render on this branch starts the gateway with:

```sh
uvicorn asgi:app --host 0.0.0.0 --port $PORT --workers 1
```

A single worker is intentional while process-local conversation state remains.
The private Core-Zero, Genesis/Core-One and Infinite-Mind/Core-Two service
definitions and credentials have not been redesigned by this migration.

The migration CI currently checks syntax/importability, docs/OpenAPI route
inventory, CORS, authentication boundaries, major native route contracts and
the legacy fallback route. CI must pass on the latest branch head before the
draft PR is marked ready. Existing project-specific tests also need to remain
green.

## Exit criteria for declaring the migration complete

- Manually port the remaining sector-specific Flask handlers and compatibility
  blueprints, preserving endpoint paths and methods.
- Verify native `/ai`, `/ai/stream`, and `/voice` contracts against the
  frontend, including multipart uploads, SSE event shapes, audio playback and
  image URLs.
- Resolve the root-route overlap and document the intended public endpoint.
- Move application config, session state, feature registry and service logic
  out of `app.py` into framework-neutral modules.
- Convert all remaining blueprints to FastAPI routers or delete genuinely
  unused route modules after proving they are not part of the public contract.
- Remove the `a2wsgi` mount, Flask imports, Flask middleware, and Flask/`flask-cors`
  dependencies only after the manual sector pass and parity tests prove the whole gateway is native.
- Run the full Python tests, validate the OpenAPI document, then deploy and
  smoke-test chat, voice, vision, memory, administrator functions and all three
  private Go cores.
