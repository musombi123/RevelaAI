# USECT-ZERO as a first-class brain tool

USECT-ZERO is wired into the primary `services/ai_service.py` request pipeline. The brain does not treat it as a text-model fallback: the server's engineering-tool dispatcher runs before ordinary model generation, and the catalog of supported operations is included in the model instructions on every turn. When a supported engineering task is selected but the core/key is unavailable, the request returns an explicit tool-unavailable result instead of pretending to have completed the operation with a generic answer.

## Required runtime configuration

Keep the core as a separate private service and set these variables on the RevelaAI backend:

```text
USECT_ZERO_ENABLED=true
USECT_ZERO_URL=<private internal URL of the Go core>
USECT_ZERO_BRAIN_API_KEY=<dedicated USECT-ZERO developer key>
USECT_ZERO_TIMEOUT_SECONDS=5
```

The dedicated brain key must be issued through the core's existing human approval flow with the scopes needed for the tools to be enabled:

- `scan:read`
- `heal:propose`
- `assemble:propose`
- `radar:compare`
- `bridge:propose`
- `mind:compile`

The brain key is a scoped USECT-ZERO key—not an AI-provider key and not the admin token. Do not put it in source control, model prompts, frontend configuration, or user-visible logs. The tool layer never forwards an admin token or the browser's bearer JWT. The existing API adapter verifies the scope at the Go core.

## Tool dispatch and behavior

- Repository scan, healing proposal, assembly fixture, offline evidence comparison, adapter plan, and RV Lang compilation are named tools.
- Supported requests are selected by the server-side engineering dispatcher before model generation. Tool results are attached as structured current-turn evidence.
- The current version deliberately dispatches at most one operation per user message.
- Radar comparison requires a supplied JSON object with `current` and `candidate` evidence. The tool will not invent benchmark values or sources.
- Assembly is currently limited to the registered `esp32-sensor` fixture. Unsupported targets are reported as unsupported by the core.
- Healing only proposes; it does not approve or restore files. No admin operations, deployment, arbitrary code execution, or hardware actuation are available to the brain.
- Tool catalog availability is documented in the model prompt every turn, but execution is performed by the bounded server dispatcher—not by parsing arbitrary model-generated shell commands.

## Operational requirements

Keep rate limiting in front of public key-request intake, and persist the Go core's `core-zero/state/`, `core-zero/evidence/` and `core-zero/audit_log/` directories across restarts. The tool flag remains disabled until the private service and scoped key are configured.
