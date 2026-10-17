# Connector Threat Model Template and Hardware Lab Checklist

Complete this document for each proposed API, security appliance or hardware connector before staging access is granted.

## Threat model template

- **Connector/vendor and version:**
- **Business owner and technical owner:**
- **Authorized asset scope:**
- **Data classifications exposed:**
- **Network origin/destination and protocol:**
- **Authentication and secret reference (never paste the secret):**
- **Declared capabilities and permissions:**
- **Read-only operations:**
- **Potential physical or administrative actions:**
- **Action/device allowlist:**
- **Idempotency and replay protection:**
- **Timeout, retry, rate-limit and circuit-breaker behavior:**
- **Audit event fields and retention:**
- **Human override / emergency stop:**
- **Safe behavior when disconnected:**
- **Expected false positives and failure modes:**
- **Rollback or disable procedure:**
- **Approval owner and review date:**

## Required abuse cases

- Unauthorized connector ID or capability registration.
- Caller attempts an undeclared action or a device outside the allowlist.
- Stolen/expired credential, token replay or privilege escalation.
- Malformed, oversized or adversarial API/device response.
- SSRF, DNS rebinding, redirect to an unapproved host or unexpected protocol.
- Timeout, duplicate request, partial completion and uncertain action status.
- Repeated transient failures causing retry storms.
- Spoofed telemetry, false alarms or missing audit persistence.
- Loss of connectivity while a physical action is in progress.
- Model prompt injection attempting to grant itself new permissions.

## Hardware lab/simulator checklist

- [ ] Begin with a simulator or disconnected lab device; no production network route.
- [ ] Confirm the device identity and firmware/software version.
- [ ] Use a dedicated test credential with the minimum read-only scope.
- [ ] Verify only explicitly allowlisted endpoints, commands and device IDs are reachable.
- [ ] Test malformed responses, timeout, retry exhaustion, duplicate idempotency key and reconnect.
- [ ] Confirm unauthorized actions are rejected and logged.
- [ ] Confirm the AI cannot modify connector manifests or permissions.
- [ ] Test operator override and safe state under network loss.
- [ ] Verify audit records contain no secrets or unnecessary personal data.
- [ ] Run a tabletop incident and document disable/credential-revocation steps.
- [ ] Obtain separate written authorization before any real actuation test.

## Release decision

Do not enable real actuation if any checklist item is incomplete, audit storage is unavailable, the safe state is uncertain, or the operator override is untested. Record residual risk and the named approver.
