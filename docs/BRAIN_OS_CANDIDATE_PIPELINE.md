# Meta-Engineer Candidate Pipeline and Release Gate

## Current implemented pipeline

Workflow: `.github/workflows/brain-os-candidate-validation.yml`

- Automatically validates each pull request targeting `main`, and also supports manual validation of a selected branch, tag or commit on a disposable GitHub-hosted runner.
- Uses read-only repository permissions and disables persisted checkout credentials.
- Does not receive RevelaCode, production database, deployment or provider secrets.
- Applies a 15-minute job timeout, compiles the candidate, runs the Meta-Engineer/Sci-Core/Brain OS test suite and checks the candidate diff.
- Publishes test logs, candidate commit, base commit, full diff summary, requested ref and test outcome as a 14-day artifact even when tests fail.

Candidate code is untrusted input. The runner is ephemeral, but it is not a fully network-isolated sandbox; do not give this workflow secrets or permission to write to the repository. Pull-request runs have read-only repository permissions, disable persistent checkout credentials, and receive no production or deployment secrets. This automation improves test coverage and evidence collection; it does not by itself approve or deploy candidate code.

## Approval and rollback policy

`meta_engineer/release_gate.py` currently implements a **simulation-only** release decision state machine. Tests prove:
- missing approval blocks promotion;
- unknown health evidence blocks promotion;
- a simulated failed post-deploy health check restores the last-known-good release identifier;
- no external deployment is performed.

This is policy simulation, not proof that an actual staging service was deployed or rolled back.

## Required before real staging or production

1. Configure a protected GitHub environment for staging with required reviewers and environment-scoped secrets.
2. Implement a reviewed release adapter that accepts a known artifact digest, deployment target and idempotency key. Do not execute arbitrary model-generated shell commands.
3. Deploy only a signed/identified artifact to an isolated staging target; run health and smoke checks.
4. Test rollback to a recorded last-known-good artifact and verify the restored revision is healthy.
5. Add deployment provenance, audit events, alerting and a manual emergency stop.
6. Keep production write/deploy disabled until security review, authorization policy and an observed rollback drill are complete.

No production secrets are supplied to the candidate-validation workflow. Real staging remains unavailable until an authorized staging target and release adapter are explicitly configured.
