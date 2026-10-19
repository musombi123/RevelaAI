# Native FastAPI migration

## Runtime contract

RevelaAI now starts from a native FastAPI application. `app.py` exports the
same FastAPI instance as `asgi.py`; Render starts it with Uvicorn.

- No Flask application is constructed by the active runtime.
- No WSGI compatibility application is mounted.
- `requirements.txt` contains no `Flask`, `flask-cors`, or `a2wsgi`.
- Request IDs, trusted-origin CORS, response security headers, request-size
  checks, 404/405 error envelopes, and the reversible SCI cooldown run in ASGI
  middleware and FastAPI exception handlers.
- CORS configuration is in `services/http_config.py`; SCI shared throttle state
  is in `services/security_state.py`.
- Conversation/session storage, optional feature registry, image generation,
  document ingestion, and audio utilities are framework-neutral services.

## Native FastAPI route groups

All of these are registered directly on the ASGI app; none is served through
Flask or WSGI.

- **System:** `GET /`, `GET /capabilities`, `GET /health`, `GET /ready`,
  dynamic-feature `POST /chat`, safe generated image serving and generated audio serving.
- **Main multimodal AI:** `POST /ai`, including JSON and multipart document
  uploads, context/hub routing, image generation, and the existing response schema.
- **AI streaming:** `POST /ai/stream`, native Server-Sent Events.
- **Voice:** `POST /voice`; generated speech is served by `/voice/audio/{filename}`.
- **Primary authenticated chat:** `POST /api/chat` and `POST /api/chat/`.
- **Live Vision:** `POST /api/vision/analyze`; validates image data and avoids
  retaining submitted camera frames.
- **Local Living Brain:** `/api/revelaai/v2/brain/chat`,
  `/api/revelaai/v2/vision/describe`, and `/api/revelaai/v2/health`.
- **Hub persona engine:** `/api/revelaai/hubs/` and `/api/revelaai/hubs/respond`.
- **Explainability:** `POST /` (root POST only; `GET /` remains the system status route).
- **Smart Memory:** chat, ideas, implementation, per-user history and cleanup under
  `/api/memory`; verified identity and isolated memory storage remain enforced.
- **Core Mesh and user-taught learning:** dashboard, Genesis proposal, Mind
  evolution proposal, teaching, knowledge listing and operator-only publication.
- **AGI manifest and Brain OS:** `/api/agi/manifest`, `/api/agi/status`, and
  administrator-protected status/outcome/routing/recovery/guardrail endpoints.
- **Sci-Core:** shield dashboard/status/scan, defensive research, disaster
  simulation and safe prototype proposals.
- **USECT-ZERO:** health, activity, developer-key workflow, diagnostics, scan,
  healing, assembly, radar, bridge planning and Mind compilation.
- **Meta-Engineer:** health, scan, proposal, approval, audit and pruning audit.
  Proposals stay review-only; no automatic deployment or generated-code execution.
- **Automation Fabric:** health, tools, consent, planning, explicitly approved
  execution and audit.
- **WhatsApp:** native webhook verification and incoming-message handlers.
- **Research:** `POST /api/research` uses bounded configured RSS feeds and does
  not fetch arbitrary user-supplied URLs.
- **Prototype users:** `POST /api/users` and `GET /api/users/{user_id}`; this
  in-memory demo API is disabled by default and is not the authoritative
  RevelaCode account store.

## Deliberately untouched sector source files

As requested, the remaining older blueprint files under `routes/` and some
older `revelai/routers/` modules are not rewritten in this pass. They are not
imported or registered by `asgi.py`, and are not part of the active request
path. Convert or retire those source files manually when reviewing their
sector-specific logic. Do not re-add them to the active app as Flask blueprints.

The current FastAPI routers are the public runtime contract. If a path in one of
the dormant source modules is not represented in `fastapi_routes/`, it is not
automatically exposed; add a native router endpoint when bringing that sector
online. This avoids quietly reintroducing Flask as a fallback.

## Dependency and security notes

`requirements.txt` excludes Flask, `flask-cors`, and `a2wsgi`. Werkzeug
remains an explicit dependency because existing security/service helpers use
its HTTP exception type; it does not start a Flask application.

JWT identity checks remain fail-closed. Privileged endpoints verify current
authority through the existing server-side verification boundary; browser role
hints are not authority. User bearer tokens are not forwarded to private Go
cores, and core credentials remain server-side. Proposals/recovery/hardware
workflows remain human-gated.

## Deployment and verification

Render starts the application with:

```sh
uvicorn asgi:app --host 0.0.0.0 --port $PORT --workers 1
```

One worker remains intentional while conversation/session state is process-local.
The migration workflow compiles `app.py` and `asgi.py`, asserts that Flask/WSGI
runtime dependencies and the compatibility mount are absent, and runs the
FastAPI route regression tests.

The gateway suite must pass on the latest branch head before PR #70 is marked
ready. The separate Go Core-Zero/Core-Two CI suites currently have independent
failures unrelated to this FastAPI gateway change.

## Remaining work

- Manually verify each sector route's public endpoint path and response contract
  against its FastAPI router.
- Port or retire unused blueprint-only source modules after confirming they do
  not expose a unique public endpoint.
- Run the complete Python suite and native endpoint tests against a deployment
  environment before declaring the migration finished.
