# USECT-AUDITOR — Audit and Evidence Integrity

Canonical package: `core_auditor/ledger.py`; the hyphenated directory gives the organ its requested name.

The ledger appends JSONL events with SHA-256 chaining, fsyncs each write, and can identify changed, missing, reordered, or truncated entries. Local chain hashes are tamper-evident—not immutable against an administrator rewriting every record. Export periodic signed checkpoints to storage under separate administrative control for stronger evidence.

Run local verification:

    python -m core_auditor.cli --path ~/.revelaai/audit/events.jsonl

API: `GET /v1/auditor/events` and reviewer-only `GET /v1/auditor/verify`.
