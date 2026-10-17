# External API and Hardware Connector Threat Model

**Status:** design and simulator stage. No real device is connected by this contract.

## Assets and safety objectives

- Availability and integrity of RevelaAI and connected company security systems.
- Confidentiality of API credentials, telemetry, facility layouts, device identifiers and incident data.
- Physical safety of people and property.
- Integrity of authorization, audit events, release approvals and device configuration.

## Trust boundaries

1. Model-generated plans and code are untrusted proposals.
2. Connector registry and policy are the authorization boundary; the model must not edit or bypass them.
3. Third-party APIs, devices, firmware, vendor SDKs and network responses are untrusted inputs.
4. Simulators and CI are not equivalent to a physical hardware lab or production environment.
5. Alert/webhook endpoints are external systems and must authenticate requests and validate payloads.

## Threats and controls

| Threat | Required controls |
|---|---|
| Prompt injection asks model to enable a device or leak secrets | Treat content as data; never derive permissions from model output; enforce policy in deterministic code |
| Rogue or compromised connector | Explicit connector allowlist, signed/reviewed adapter, version pinning, least privilege, isolated network |
| Credential exposure | Secret manager/environment injection, scoped short-lived credentials where possible, redaction, rotation plan |
| Unauthorized actuation | Default read-only; action and device allowlists; independent human approval; two-person approval for high impact; emergency stop |
| Replay/duplicate command | Idempotency key, expiry, replay store, signed command envelope and device-side deduplication |
| Malformed or oversized telemetry | Typed schema validation, strict size limits, parser isolation and rate limits |
| Slow/unavailable API or device | Per-operation timeout, bounded retries only for safe idempotent reads, circuit breaker, clear degraded state |
| Network pivot from AI host | Egress allowlist, separate management VLAN, no direct public access to device networks, gateway/proxy mediation |
| Audit tampering | Append-only external audit sink, synchronized timestamps, integrity checks and restricted write access |
| Unsafe automatic remediation | Recommendation-first, staged dry run, explicit approval, narrow rollback plan and post-action verification |
| False sense of security from simulator | Mark all simulation output, run contract tests and separately execute hardware-in-the-loop test plans |

## Permission model

Permissions are granted by deployment configuration and reviewed adapter manifests, never by a language model. A connector may request no more than its pre-approved manifest. Unknown capability, action, device or schema must fail closed.

## Future rollout gates

1. Mock connector contract tests.
2. Read-only sandbox API and synthetic fixtures.
3. Independent security review and abuse-case testing.
4. Authenticated staging adapter with non-production credentials.
5. Hardware lab test with physical emergency stop and vendor-approved test procedures.
6. Explicit rollout approval, monitoring, manual override and rollback/recovery drill.
7. Production enablement only for a narrowly defined, reviewed use case.

Do not connect a door lock, alarm, camera, vehicle, industrial controller, medical device or other safety-critical system until its specific safety, legal, privacy and vendor requirements have been reviewed.
