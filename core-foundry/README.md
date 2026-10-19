# USECT-FOUNDRY — Python-Native Factory Builder

The canonical importable implementation is in `core_foundry/factory/foundry_builder.py`; Python package identifiers cannot contain hyphens. `core-foundry/factory/foundry_builder.py` provides the requested organ path as a compatibility wrapper.

Foundry takes bounded declarations and reusable adapter identifiers and produces a deterministic JSON workflow/manifest. It does not execute generated code, actuate hardware, flash firmware, or deploy to production. Builds start at `await_merge`; only an authenticated reviewer can approve them. The manifest carries a SHA-256 integrity field and consequential actions are logged to the database audit table and, when writable, the JSONL hash-chain ledger.

API: `POST /v1/foundry/build`, `GET /v1/foundry/builds/{build_id}`, `POST /v1/foundry/builds/{build_id}/review`.
