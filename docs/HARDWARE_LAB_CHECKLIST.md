# Hardware Lab and Sandbox Connector Checklist

## Before connecting
- [ ] Written owner approval and defined test scope.
- [ ] Device/API is owned or explicitly authorized for testing.
- [ ] Lab network is isolated from production and the public internet where feasible.
- [ ] Read-only credentials and synthetic/non-sensitive data are used first.
- [ ] Adapter manifest, supported schema, rate limit and timeouts are reviewed.
- [ ] Emergency stop, manual override and safe fallback are identified.
- [ ] Logging avoids credentials, personal data and unnecessary facility details.

## Contract tests
- [ ] Unknown connector ID is denied.
- [ ] Undeclared capability, permission, device or action is denied.
- [ ] Authentication failure and malformed response fail closed.
- [ ] Slow response reaches a timeout without unbounded waiting.
- [ ] Only safe idempotent reads are retried, with a bounded retry count.
- [ ] Repeated idempotency key does not duplicate a simulated/approved operation.
- [ ] Audit records capture actor class, approval reference, action, target alias, outcome and timestamp.
- [ ] Secret values and sensitive telemetry do not appear in logs or alerts.
- [ ] Connector disconnect and process restart recover to a safe state.
- [ ] Physical action tests, if separately authorized, are first performed in a manufacturer-supported test mode under human supervision.

## Release criteria
- [ ] Security and safety owner sign-off.
- [ ] Failure injection and rollback/recovery drill pass.
- [ ] Monitoring and alert delivery are tested end to end.
- [ ] Rollout scope, expiry, revocation procedure and incident owner are documented.
- [ ] No model-generated code can grant itself permissions or bypass policy.
