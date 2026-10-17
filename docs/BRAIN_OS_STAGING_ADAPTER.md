# Staging Release Adapter Contract

## Current status

`meta_engineer/staging_adapter.py` defines a typed deployment-adapter contract and a deterministic simulator. It is designed for an immutable commit SHA, a pull-request approval reference, deployment health evidence and rollback verification. The shipped implementation has no deployment credentials and makes no external infrastructure changes.

## Contract sequence

1. Validate full immutable candidate and last-known-good commit SHAs.
2. Require an explicit approval reference in the format `GH-PR-N`.
3. Simulate deployment of the candidate.
4. Check candidate health.
5. If unhealthy, simulate rollback to the previous immutable SHA.
6. Independently check the restored release; escalate if rollback or restored health cannot be verified.

Unknown health must never be represented as healthy. A failed or unverified rollback yields `rollback_failed_escalate` and no active SHA is claimed.

## Before connecting a real adapter

- Configure a protected GitHub `staging` environment with required reviewers.
- Provide a separately reviewed adapter endpoint and environment-scoped credentials with staging-only permissions.
- Make operations idempotent and accept only immutable artifact/commit identities.
- Use strict endpoint allowlists, TLS, authentication, bounded timeouts, durable audit, and explicit approval references.
- Keep production secrets and production write permissions out of candidate-validation jobs.
- Test failure injection, duplicate requests, deployment timeout, health timeout, rollback timeout and emergency stop.
- Perform a live staging drill, record the run URL and deployment identifiers, and verify last-known-good health before considering production rollout.

The simulator's passing tests prove policy behavior only. They do not prove that a real staging system deployed or rolled back.
