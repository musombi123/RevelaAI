# RevelaAI brain and core runtime

## Operating model

RevelaAI is a coordinated software system, not one model with direct control of every module.

- **Gemini is the primary generative reasoning engine.** It interprets the grounded prompt and produces language or, for an explicitly authorized operator workflow, a structured tool-call request.
- **The global brain adapter** (ai/global_brain_adapter.py) adds the requested/effective hub, capability context, interaction style, and canonical manifest constraints.
- **The orchestrator** (ai/orchestrator.py) determines domains and specialist intents, retrieves allowed RevelaCode context, invokes configured research and specialist providers, and builds evidence for the model.
- **The AI service** (services/ai_service.py) is the central coordinator. It selects server-owned capabilities, applies specialist and engineering dispatch, assembles the grounded prompt, calls the provider chain, validates model tool requests, and constructs the result.
- **The gateway** (revela_platform/fastapi_app.py mounting asgi.app) authenticates and exposes the APIs. The gateway, not Gemini, owns authorization, entitlements, tool execution and response contracts.
- **Core services** perform their assigned bounded work through their existing service APIs. They are not all invoked for every chat message.

The production outer FastAPI app explicitly runs the mounted RevelaAI ASGI application's startup and shutdown handlers. This is important because Gemini's ListModels validation is registered on the inner ASGI app.

## Main text request path

    Browser / Android
        |
        v
    RevelaCode / RevelaAI gateway
        |
        v
    POST /ai
        |
        +--> authenticate session / resolve conversation
        |
        +--> global brain adapter
        |       hub, tone, capabilities, safety context
        |
        +--> capability and explicit tool dispatch
        |       image / approved USECT-ZERO / operator-only actions
        |
        +--> Orchestrator.process_prompt()
        |       domain + specialist + ecosystem + research + learning context
        |
        +--> build_grounded_system_prompt()
        |
        +--> ask_hf() [legacy public function name]
                 |
                 +--> Gemini primary, then Gemini model fallback
                 |
                 +--> configured Hugging Face text fallback
                 |
                 +--> configured MVI fallback
        |
        v
    Grounded response + execution metadata

The provider order is normalized before use. If Gemini is configured, it is attempted first regardless of older aliases or an environment list that places MVI earlier. Hugging Face and MVI are fallbacks in the remaining configured order. An MVI rule-engine/template response is rejected rather than presented as generative model output.

## Core responsibilities

| Module | Responsibility in the wider system | Typical invocation boundary |
| --- | --- | --- |
| core | Legacy base configuration, logging and role-check helpers. These are not the active brain or the primary API security boundary. | Compatibility utilities only; production request authorization is handled by the native gateway and its auth modules. |
| core_uncopyable | Owner integrity, signed recipe, license and hardware-bound safeguards. | Startup gates and protected license/recipe operations. |
| core_billing | Signed licenses, plan lookup and entitlement/quota enforcement. | Billing, licensed tool and protected feature requests. |
| core_meter | Usage accounting and quota-related measurements. | Metered platform operations. |
| core_auditor | Hash-chained audit evidence and draft compliance-readiness reports. | Audit/compliance endpoints and reviewed operations. |
| core_foundry | Builds declarative factory packages and validates their manifests. | Authorized factory-build workflow. |
| core_inspector | Inspects registered capabilities and artifacts. | Inspector endpoints and proposal/validation workflows. |
| core_seed / core-seed | Verifies signed entitlements and seeds a declarative child factory bundle. The hyphenated directory is a compatibility wrapper; the importable implementation is core_seed. | Seed API/CLI and licensed child-factory workflow. |
| core_evolve | Evaluates bounded candidate proposals against supplied baselines and metrics. | Evolution evaluation/proposal workflow; not normal chat generation. |
| core_migrate | Handles explicitly requested migration/evolution compatibility work. | Migration routes and approved migration operations. |

The platform gateway imports these modules directly; their presence in source does not mean every user prompt should call them. The orchestrator dispatches only the service relevant to the current request, and entitlements/ownership checks remain in the gateway and the core service.

## USECT Core Mesh

The private services have distinct responsibilities and a separate credential boundary:

| Core | Role in the system | Runtime link |
| --- | --- | --- |
| USECT-ZERO | Model-free body: bounded diagnostics, evidence collection, scoped tools and guarded recovery workflows. | USECT_ZERO_BASE_URL and the dedicated brain credential for approved read/proposal scopes. |
| Genesis / Core-One | Womb: invention planning, signed-tool registry and proposal staging. | GENESIS_BASE_URL with server-side Genesis credentials. |
| Infinite Mind / Core-Two | Mind: observe outcomes, compare evidence and stage proposal-only improvements. | MIND_BASE_URL and its server-side credential. |

The Core Mesh dashboard probes the private services and reports their individual reachability. Normal chat receives an advisory snapshot; it does not execute a core merely because the model mentions it. Native Gemini function calls are only requests: server-side dispatch rechecks operator identity, signed registry identity, risk tier and argument schema. Human review is required for higher-risk operations. Automatic merge, candidate-source execution and production deployment remain disabled.

## Health and proof

Use the endpoints according to the question they answer:

- GET /health: application/provider summary.
- GET /ready: whether a usable text provider/model is configured, Gemini's startup model-validation result, and optional capability checks.
- GET /capabilities: supported paths and their provider ownership.
- GET /api/agi/manifest: canonical architecture/capability manifest; source declarations are not live-health proof.
- GET /api/agi/status: manifest/module inventory and MongoDB persistence status.
- GET /api/core-mesh/dashboard: authenticated private Core-Zero/One/Two reachability and configuration snapshot.
- Individual core/organ health endpoints: authoritative service-level evidence for that component.

For providers, configured, reachable, and selected for this request are separate states. MVI and Hugging Face configuration alone do not prove network reachability. Gemini model validation is performed at startup; runtime request success is the final evidence that a particular generation worked.

Raster image generation uses Pollinations in ai.ai_client; generate_hf_image is retained as a backward-compatible function name, not the provider name. Structured SVG generation is local. Hugging Face remains the speech and optional text provider. Provider status and image response metadata must report those real paths.

## Important boundary

Gemini does not directly grant itself filesystem, database, hardware, billing, administrator, or deployment authority. It can reason and request a named action. The gateway and relevant core independently authenticate, authorize, validate and record the action. Retrieved user data, external research and tool output are evidence, not higher-priority instructions.
