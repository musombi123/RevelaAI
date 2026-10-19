# Flask-to-FastAPI migration

## Current branch status

The ASGI entry point in `asgi.py` uses FastAPI and Uvicorn. The root-mounted
`WSGIMiddleware` is an intentional temporary compatibility bridge: it forwards
paths that have not yet been ported to the existing Flask app. This first phase
allows the ASGI runtime, OpenAPI documentation, and basic middleware to be
validated without changing the existing route contract in a single risky rewrite.

**This phase is not the completed Flask removal.** Do not remove Flask,
`flask-cors`, or the compatibility mount until the route groups below are
ported and parity-tested.

## Route inventory to migrate

The current gateway directly declares endpoints in `app.py` and registers these
Flask blueprints:

- Vision (`/api/vision`)
- Chat (`/api/chat`)
- Living Brain API (`/api/revelaai/v2`)
- Explain
- Memory (`/api/memory`)
- Research
- Users
- WhatsApp
- Hub
- Meta-Engineer (`/api/meta-engineer`)
- USECT-ZERO (`/api/usect-zero`)
- SCI (`/api/sci`)
- AGI (`/api/agi`)
- Automation Fabric (`/api/automation-fabric`)

The direct routes include chat/AI processing and streaming, generated image and
audio file serving, health/readiness, Core Mesh status/proposals, and Living
Brain learning/publication endpoints. This inventory must be kept current while
the route port is completed.

## Required conversion sequence

1. **Extract framework-independent service functions.** Provider calls,
   orchestration, persistence, capability execution, and security policy should
   not depend on Flask's `request`, `g`, `jsonify`, or application context.
2. **Port routes to FastAPI `APIRouter` modules.** Define Pydantic request models
   and explicit response/status behavior. Keep endpoint paths, HTTP methods,
   response envelopes, and error codes compatible with existing clients.
3. **Replace request lifecycle behavior.** Preserve trusted CORS origins,
   forwarded-proxy behavior, request IDs, response security headers, upload
   limits, JSON error contracts, request throttling, and shutdown/lifespan work.
4. **Preserve security invariants.** JWT validation must continue to require
   `sub`, `iat`, and `exp`; operator-only operations must remain operator-only;
   Core Mesh tokens stay server-side; user-specific memory stays isolated.
5. **Add route parity tests for every ported group.** Include unauthenticated,
   authenticated, forbidden, malformed input, missing resource, provider
   failure, and successful response cases as relevant.
6. **Remove the compatibility bridge only after parity passes.** Then remove
   Flask/`flask-cors`, make `asgi.py` import only FastAPI routers/services, and
   prove no production import or test depends on Flask.

## Deployment and verification

The Render blueprint now starts the gateway with:

```sh
uvicorn asgi:app --host 0.0.0.0 --port $PORT --workers 1
```

A single worker is retained to avoid changing the existing process-local session
memory behavior while migrating. The private Go Core-Zero, Genesis/Core-One,
and Infinite-Mind/Core-Two service wiring and their server-side credentials are
unchanged.

The added CI check covers the ASGI entry point, docs, security headers, and one
authenticated legacy route's unauthenticated response. It does **not** prove
that all routes have already been converted. Full completion requires per-route
parity tests and removal of Flask from runtime imports and dependencies.
