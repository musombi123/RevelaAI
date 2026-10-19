# USECT-SEED — Offline Child Factory

Canonical importable implementation: `core_seed/seed_runner.py`; the hyphenated path wrapper is for the named organ directory.

Seed validates the signed Ed25519 platform entitlement offline and honors its signed `offline_until` claim, capped to 30 days by the issuer. A child bundle stores the signed token in a local file restricted to owner permissions, binds its JSON manifest with SHA-256, and can be verified offline:

    python -m core_seed.cli --seed-id seed_<24 hex characters>

Set `REVELA_SEED_ROOT` to the seeded child directory and configure the license public key. The current seed is a declarative workflow plan: it never imports or executes customer-supplied Python, activates hardware, or silently deploys. System-clock rollback cannot be fully prevented without trusted hardware. The hosted API also checks the current server-side license record, while the offline CLI uses the signed entitlement and bounded lease.
