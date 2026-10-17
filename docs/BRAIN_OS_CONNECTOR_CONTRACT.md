# RevelaAI API and Future Hardware Connector Contract

## Current implementation

The typed contract lives in `revelai/sci_core/connector_contract.py`. It defines:
- A versioned connector manifest with connector type, declared capabilities, permissions, target scope, authentication scheme, timeouts, idempotency support and action/device allowlists.
- A configured connector-ID allowlist; unknown connectors cannot be registered.
- Bounded read retries for explicitly transient telemetry failures.
- Explicit operation timeouts, normalized errors and a simulator.
- Idempotency keys for simulated actions; keys are hashed in returned metadata.
- No real hardware actuator and no live action execution method.

## Manifest rules

- Start with `connector_type=api` or `hardware_simulator`.
- Start with read-only capabilities and least-privilege permissions.
- Credential fields are references to environment/secret-manager names, never secret values.
- Use short timeouts, bounded retries and stable idempotency keys.
- Declare exact action IDs and device IDs before any future action-capable integration.
- `action_mode=approval_gated` is a declaration of future policy requirements only; this registry will still refuse to execute real actuation.
- Model-generated text may request an operation, but it cannot register a connector, add permissions, change an allowlist or grant itself authority.

## Integration sequence

1. Mock connector and contract tests.
2. Read-only sandbox API integration using synthetic/test credentials.
3. Authenticated staging adapter with network egress restrictions and scoped secrets.
4. Threat model and security review for the specific vendor, protocol and device.
5. Separate approval to enable narrowly scoped real actions, if the risk review allows it.
6. Observed failure, timeout, idempotency, emergency-stop and rollback drills.
7. Controlled rollout with monitoring, operator override and documented revocation procedure.

## Error and retry contract

- Timeouts are explicit and surfaced as `ConnectorTimeout`.
- Only declared transient read failures are retried; at most one retry is performed by this registry.
- Physical actions must not be blindly retried. Any future action adapter needs idempotency, precondition checks, result verification and an operator-approved retry policy.
- Audit event records should identify connector, action ID, idempotency-key hash, authority, result, timestamp and verification state without logging secrets or raw prompts.

## Security requirements for real integrations

- Mutual TLS or short-lived scoped tokens where supported.
- Secret storage outside source code, logs, prompt context and artifacts.
- Egress allowlists, DNS/TLS validation and endpoint allowlists to prevent SSRF.
- Request/response schema validation and payload size limits.
- Rate limits, circuit breakers, replay protection and request signing where appropriate.
- Audit logging and retention policy.
- Fail-safe behavior on network loss, timeout, invalid telemetry or uncertain action state.
- Physical override and safe local fallback for hardware.
