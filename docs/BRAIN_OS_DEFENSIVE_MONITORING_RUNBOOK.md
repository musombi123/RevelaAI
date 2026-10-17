# Brain OS Defensive Monitoring Runbook

## Scope and operating mode

The scheduled runner monitors the checked-out RevelaAI repository and the runtime environment available to the runner. It is not a universal malware detector and does not automatically block IPs, edit firewall rules, restart services, patch production, or actuate hardware.

The current checks are:
- Static pattern scan over Python files beneath `revelai/`.
- Authentication-log pattern scan, if the configured log file exists and is available to the runner.
- Dependency advisory queries through the OSV API for packages listed in `requirements.txt`.

Static pattern matches can be false positives and can miss real attacks. A successful scan means these checks ran; it does not mean the system is attack-proof.

## Runtime health checks

The scheduled workflow can also probe deployed health endpoints. Set the following repository configuration:
- `REVELAAI_MONITOR_TARGETS_JSON` — JSON array of 1–25 targets, for example `[{"id":"revelaai-api","url":"https://YOUR-OWN-HTTPS-HOST/health","expected_statuses":[200]}]`.
- `REVELAAI_MONITOR_ALLOWED_HOSTS` — comma-separated exact hostnames that are owned/authorized, without scheme or paths.

Each target must use HTTPS on port 443, an exact allowlisted hostname, no URL credentials/query/fragment, and a unique short ID. Redirects are not followed. The runner uses a bounded timeout and never stores response bodies or full URLs. Only the target ID and status class are included in incident metadata. The allowed-host variable is a security boundary: add only hosts the company owns or has explicit permission to monitor. Use public, unauthenticated health endpoints; this runner does not support sending credentials to health targets.

If runtime target configuration is missing or invalid, the check reports a monitoring configuration failure rather than marking the environment clean. Until these variables are configured and a scheduled run is observed, deployed service health monitoring is not operationally verified.

## Required deployment configuration

Configure this GitHub Actions repository secret:

- `REVELAAI_ALERT_WEBHOOK_URL` — HTTPS endpoint that accepts a JSON POST with `source`, `event_type`, `generated_at`, and an `incidents` array. Do not place the URL or credentials in source code or logs.

The scheduled job fails clearly when the alert adapter is not configured. It must not report alerts as delivered when no endpoint exists. The alert endpoint should authenticate requests independently where supported and restrict who can view incident data.

Workflow: `.github/workflows/brain-os-defensive-monitor.yml`  
Schedule: hourly at minute 17 UTC; manual runs are available through workflow dispatch.

## Incident deduplication and severity

The runner maps the source severity to `info`, `low`, `medium`, `high` or `critical`. Medium and above are eligible for alerting. It suppresses an incident fingerprint for 24 hours after a successfully delivered alert. Failed or unconfigured delivery is not treated as successful deduplication.

Fingerprints are hashes of stable incident attributes. Source IP addresses are used only as one-way fingerprint input and are not included in webhook incident details or monitor incident records.

## Triage

1. Open the failed or alerting workflow run and confirm whether checks completed and whether the alert adapter returned success.
2. Review the incident type, severity, file/line or dependency identifier and suggested remediation.
3. Reproduce the signal in a controlled environment. Static matches are leads for review, not proof of compromise.
4. For suspected credential exposure, follow the approved secret-rotation procedure. Never paste credentials into issue comments or logs.
5. For suspected active compromise, follow the company incident-response plan and isolate affected systems through the authorized infrastructure control plane. This runner does not perform containment.
6. Record the owner, decision, evidence and follow-up issue in the incident tracker.

## Recovery and escalation

- **High/critical or active exploitation suspected:** page the designated security owner immediately using the configured alert channel; preserve logs and follow the incident-response plan.
- **Dependency advisory:** confirm affected/fixed versions and compatibility, open a patch PR, run tests, and deploy through the approved release pipeline.
- **False positive:** document why it is a false positive and create a narrowly scoped reviewed suppression. Do not disable a whole scan merely to silence a finding.
- **Check failure or alert delivery failure:** treat as monitoring degradation, restore the runner/dependency/API/webhook configuration, and rerun a controlled check. Do not interpret missing telemetry as clean status.

## Post-incident review

Document timeline, detection and alert timestamps, affected asset scope, root cause, containment and recovery evidence, false-positive/false-negative observations, and preventive changes. Exercise the alert path with a controlled mock or test incident before relying on it operationally.

## Retention and limitations

The runner stores incident metadata and fingerprints in the `monitor_incidents` collection. Review retention, access control and backup policies before production use. The repository's existing Sci-Core storage abstraction may use a bounded local cache when MongoDB is unavailable; that fallback is not a durable monitoring database. A production rollout should confirm durable persistence and alert delivery in the target environment.

No automatic mitigation is enabled. Any future containment action requires a separate threat model, explicit authorized adapter, least-privilege credentials, idempotency, cooldown/retry limits, post-action verification and an operator override.
