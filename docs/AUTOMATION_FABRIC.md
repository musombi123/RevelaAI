# RevelaAI Automation Fabric v1

Automation Fabric is a deterministic, review-first tool runtime for RevelaAI. It is a real Python module and HTTP API, not a prompt. It intentionally requires no model, model weights, or paid AI provider.

## What is included

- A versioned tool registry with JSON argument contracts and required permission scopes.
- A bounded workflow planner (maximum 20 steps and 350 KB of JSON arguments).
- Short-lived, per-principal consent grants with explicit revocation.
- A SHA-256 plan hash that the client must send back after reviewing the plan.
- One-shot execution; plans cannot be run twice.
- SQLite-backed plan status and a hash-chained audit trail.
- Workspace path traversal protection and atomic UTF-8 writes.
- A deterministic arithmetic evaluator that does not use Python eval.
- A tool factory that writes a disabled proposal (manifest.json, tool.py, README.md) but never imports, installs, or runs the generated source.
- A loopback-only companion runtime for operations that require the installed device.
- Optional public HTTPS research constrained to an explicit host allowlist.

## Hosted API

After deployment, routes are available at:

- GET /api/automation-fabric/health — non-sensitive status.
- GET /api/automation-fabric/tools — registry and the caller's active consent grants.
- GET /api/automation-fabric/consent — list active grants.
- POST /api/automation-fabric/consent — grant selected scopes.
- POST /api/automation-fabric/consent/revoke — revoke selected scopes.
- POST /api/automation-fabric/plan — validate and persist a plan without executing it.
- GET /api/automation-fabric/plans/{plan_id} — inspect a plan belonging to the authenticated user.
- POST /api/automation-fabric/execute — execute an unexpired plan once, only with valid grants, the exact plan hash, and approved=true.
- GET /api/automation-fabric/audit — read the caller's hash-chained audit events.

All non-health routes reuse RevelaAI's existing JWT plus authoritative RevelaCode user-verification gate. If the account-verification service or service key is not configured, the routes fail closed.

Example plan request:

    POST /api/automation-fabric/plan
    Authorization: Bearer <RevelaCode JWT>
    Content-Type: application/json

    {
      "steps": [
        {"tool": "math.evaluate", "args": {"expression": "(128 / 4) + 7"}},
        {"tool": "factory.scaffold_python_tool", "args": {
          "name": "mqtt_adapter",
          "description": "Proposal for a reviewed MQTT integration."
        }}
      ]
    }

The response contains plan.plan_id, plan.plan_hash, plan.required_scopes, and a full step-by-step plan for review. The user must separately grant the listed scopes, then submit:

    POST /api/automation-fabric/execute
    Authorization: Bearer <RevelaCode JWT>
    Content-Type: application/json

    {
      "plan_id": "<plan.plan_id>",
      "plan_hash": "<exact plan.plan_hash>",
      "approved": true
    }

Consent example:

    POST /api/automation-fabric/consent
    {
      "accepted": true,
      "scopes": ["workspace:write", "tools:scaffold"],
      "reason": "Create a reviewed tool proposal",
      "ttl_seconds": 3600
    }

Revocation example:

    POST /api/automation-fabric/consent/revoke
    {
      "scopes": ["workspace:write"]
    }

Never put the JWT, service key, or local agent token in a public repository or browser logs.

## Local device agent

The hosted API operates only in an isolated per-user server workspace. It cannot control the user's laptop, browser, USB device, serial port, Bluetooth device, or GPIO from the cloud service. Device-side access requires installation on the target machine.

With the repository checked out and its existing dependencies installed:

    python -m automation_fabric.local_agent

The local service listens on http://127.0.0.1:38741/api/v1, creates a bearer token in ~/.revelaai/automation-fabric.token, and uses ~/RevelaAIWorkspace for workspace operations. On first launch the token is printed once. To display the saved token deliberately later:

    python -m automation_fabric.local_agent --show-token

Do not expose the local agent on 0.0.0.0 or port-forward it. It rejects non-loopback clients and uses a random bearer token. Browser access is disabled unless the exact frontend origin is set in REVELAAI_AUTOMATION_ALLOWED_ORIGINS, for example:

    REVELAAI_AUTOMATION_ALLOWED_ORIGINS=https://revelacode-frontend.onrender.com

The user still needs to provide the local token to an approved local client; this API does not silently retrieve it from the user's device.

## Built-in tools

| Tool | Required scope | Hosted execution |
|---|---|---|
| math.evaluate | none | Yes |
| workspace.list | workspace:read | Yes, isolated hosted workspace |
| workspace.read_text | workspace:read | Yes, isolated hosted workspace |
| workspace.write_text | workspace:write | Yes, isolated hosted workspace; explicit plan confirmation |
| factory.scaffold_python_tool | tools:scaffold, workspace:write | Yes; files remain disabled proposals |
| research.fetch_public_page | research:public_web | Yes; HTTPS host allowlist only |
| system.inventory | system:read | Local agent only |
| hardware.discover | hardware:discover | Local agent only; read-only Linux device-node discovery |

The default research host allowlist is:

    github.com,raw.githubusercontent.com,docs.python.org,developer.mozilla.org,pypi.org

Use REVELAAI_AUTOMATION_ALLOWED_HOSTS to configure exact trusted domains or their subdomains. Redirect destinations are revalidated. Page size and timeout are bounded; only text-based responses are accepted.

## Environment configuration

- REVELAAI_AUTOMATION_DB: path to the SQLite database. The default is /tmp/revelaai-automation-fabric.sqlite3; that default is ephemeral on many cloud hosts. Set a durable, private path if retained audit history is needed.
- REVELAAI_AUTOMATION_SERVER_WORKSPACE: root for isolated hosted user workspaces. Default: /tmp/revelaai-automation-workspaces.
- REVELAAI_AUTOMATION_WORKSPACE: local-agent workspace. Default: ~/RevelaAIWorkspace.
- REVELAAI_AUTOMATION_ALLOWED_HOSTS: comma-separated research HTTPS host allowlist.
- REVELAAI_AUTOMATION_ALLOWED_ORIGINS: exact browser origins allowed to call the local service; empty by default.

Grant rows, plan metadata, execution summaries, and audit events are retained in SQLite; old plans are pruned after seven days. Full execution output is returned only to the caller and is not persisted as a run result. File-write arguments stored with plans can contain user content, so the database path must be private and protected. Use an encrypted disk where available.

## Security boundaries

- No shell command executor.
- No arbitrary Python or JavaScript evaluation.
- Generated tool files are never auto-imported or auto-run.
- All file operations are scoped to a per-user workspace, using canonical path resolution.
- Every execution needs a fresh short-lived consent grant for each declared scope and an exact reviewed plan hash.
- Plans expire after 15 minutes and execute once.
- Research is opt-in and restricted to public HTTPS hosts.
- Hardware discovery is read-only and does not open devices or activate actuators.
- A host's OS, accounts, network ports, installed drivers, firmware interfaces, and permissions define the actual reach. "Universal automation" is an extensible engineering target, not a claim that every device can be controlled safely from one generic module.

## Tests

    python -m pytest tests/test_automation_fabric.py -q

Before production use, also add OS-specific integration tests, a proper process supervisor for the local agent, an installer that explains every permission, signed plugin packages, a hardened HTTP server, and real adapter-specific authorization and safe-stop logic. Hardware actuation must be implemented by individually reviewed adapters with device-specific limits, emergency stop, and fail-safe behavior—not by allowing arbitrary commands.
