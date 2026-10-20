# USECT-EVOLVE + USECT-MIGRATE

Python-native organs for evidence-driven improvement and authorized movement of RevelaAI capabilities. The active runtime is **FastAPI-only**; this package does not reintroduce Flask or a WSGI compatibility layer.

## What is implemented

### Evolver
- Typed, bounded evolution requests and persisted proposals.
- Recursive proposals with a maximum generation depth of three.
- Objective/metric-driven evaluations using supplied benchmark observations.
- Explicit evidence, test, and security-review requirements before a proposal is eligible for human review.
- No generated code is executed and no live source is modified by the proposal engine.

### Migrator
- Persistent inventory of explicitly enrolled devices and verified hardware resources.
- Capability matching and dry-run migration plans tied to a SHA-256 artifact digest.
- Owner authorization checks and an explicit approval identifier requirement for non-dry-run planning.
- Robot resource blueprints that identify missing components and safety controls.
- No network port scanning, silent enrollment, remote shell execution, or physical robot actuation.

## API

All administrative routes require the header X-Organ-Admin-Token, matched against REVELA_ORGAN_ADMIN_TOKEN. The service fails closed with HTTP 503 if the secret is not configured and HTTP 401 if the supplied token is invalid. Use a strong secret from the deployment secret manager; never commit it.

- GET /api/usect/evolve/health
- POST /api/usect/evolve/proposals
- POST /api/usect/evolve/proposals/{proposal_id}/children
- POST /api/usect/evolve/proposals/{proposal_id}/evaluate
- GET /api/usect/migrate/devices
- POST /api/usect/migrate/devices/enroll
- POST /api/usect/migrate/plans
- POST /api/usect/migrate/robot-blueprints

The routes appear in the live FastAPI schema at /openapi.json.

## Persistence

- Evolver: REVELA_EVOLVE_STORE (default .revela/evolve)
- Migrator: REVELA_MIGRATE_STORE (default .revela/migrate)

Use persistent encrypted storage and appropriate filesystem permissions in production. These JSON stores are a simple first-stage implementation; multi-worker deployments should move them to the platform's transactional database with concurrency control.

## Safety and deployment contract

A passing evaluation means **candidate for human review**, not approval to install. A migration plan does not perform deployment. A future enrolled device agent must authenticate its device identity, verify the artifact digest/signature, enforce license scope, support rollback, and report a signed deployment receipt before deployment can be considered complete.

Robot blueprints are planning artifacts only. Physical movement requires verified hardware, independent safety controls, an emergency stop, operator takeover, and a separately authorized actuator service.

“50× smarter” is not hard-coded as a promise. Performance improvements must be demonstrated against a named baseline with reproducible benchmark data, including quality, latency, reliability, cost, and compliance impact. RVX encryption alone is not a substitute for code signing, safe execution, or device identity.
