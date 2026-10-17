# Brain OS Recovery Policy Runbook

## Current mode

Recovery actions are **simulation-only**. The action registry may validate evidence, apply policy, record a bounded attempt, and decide whether a plan is ready for further review. It does not retry a provider, open a circuit breaker, refresh a cache, restart a service, patch code, change firewall/authentication, mutate a database, or operate hardware.

The route `POST /api/agi/brain-os/heal/actions/simulate` is administrator-gated. Do not expose the Python function directly to untrusted callers; its authority argument is an internal policy input, not an authentication mechanism.

## Policy fields

Each reviewed action declares:
- severity and risk class;
- allowlisted authority classes;
- exact categorical preconditions;
- cooldown window;
- maximum number of recorded attempts;
- whether verification is required;
- whether it is merely a future candidate for automatic execution.

Unknown action IDs, unapproved authority classes, unrecognized evidence keys, malformed identifiers and non-categorical evidence are rejected. Policy is registry-driven; free-form model output cannot define an executable action.

## Simulation decisions

- `preconditions_not_met`: required evidence does not match.
- `cooldown_active`: an earlier recorded attempt is still inside its cooldown.
- `retry_exhausted`: the bounded attempt budget has been used; escalate to an operator.
- `verification_passed_simulated`: a test fixture reports simulated verification success; this is not proof of a real recovery.
- `verification_failed_escalate` or `verification_unknown_escalate`: stop and escalate; do not retry blindly.
- `ready_for_approval_simulation`: policy preconditions passed in simulation. This is not approval to act.

Every result explicitly reports `executed: false` and `external_side_effects: false`. Audit persistence failure fails closed and the route returns an error.

## Operator response

1. Confirm the incident against independent service health metrics.
2. Review the incident reference, action, severity, preconditions, policy decision and attempt history.
3. For cooldown or exhausted retry decisions, do not manually loop the action. Escalate to the service owner.
4. For failed/unknown verification, inspect independent health checks and logs, preserve evidence and follow incident response.
5. Record any real recovery performed manually in the approved operational incident tracker, including approval and post-recovery health proof.

## Requirements before a real executor

A future executor must be a separate, explicitly reviewed adapter—not arbitrary commands. It needs signed/allowlisted action definitions, least-privilege credentials, durable atomic cooldown/idempotency storage, approval references, safe dry-run, timeout/circuit-breaker controls, independent pre/post health checks, verified rollback, tamper-resistant audit, alerts, kill switch and tested failure injection. Begin only with reversible low-risk operations in an isolated staging environment. Do not promote an action based solely on a model-generated recommendation.
