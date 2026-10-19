# USECT-SEED — Offline Child Factory

The importable implementation lives in `core_seed/`; this directory retains the feature's organ name. Seed Runner validates a signed Ed25519 license offline and honors its signed `offline_until` claim, capped to 30 days when issued by RevelaAI. It creates a declarative child bundle, not executable code, and never silently activates hardware or runs arbitrary Python.

Offline enforcement relies on the local wall clock and signed token; protection against a privileged user rolling back system time requires trusted hardware or a server recheck.
