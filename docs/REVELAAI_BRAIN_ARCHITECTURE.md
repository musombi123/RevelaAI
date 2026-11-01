# RevelaAI brain and body architecture

## Operating model

RevelaAI has one executive decision path and multiple specialist bodies. The brain decides what kind of work is needed; a specialist, provider, or Core service performs only the work assigned to it. The browser is a client, not the authority for tools or platform mutations.

### Executive brain

| Component | Responsibility |
| --- | --- |
| `ai.global_brain_adapter.build_global_context` | Resolves Auto versus an explicit hub, applies the selected hub's system guidance, estimates interaction tone, and describes capabilities available for the turn. |
| `ai.intent_router.classify_intent` | Classifies the request for the HTTP/service layer before dispatch. |
| `ai.orchestrator.Orchestrator.process_prompt` | Selects domains, retrieves approved platform context, runs domain-specific intelligence, decides whether live research is required, and assembles grounded evidence. |
| `services.ai_service.process_message` | Enforces action/tool boundaries, invokes the orchestrator, builds the grounded model prompt, calls the provider chain, validates tool results, and returns response metadata. |
| `revelai.core.brain_os` | Maintains capability inventory and privacy-minimized delivery/quality telemetry; diagnoses known components without autonomously modifying production. |
| `ai.core_mesh` | Routes relevant Core requests and reads USECT-ZERO, Genesis and Infinite Mind status. Consequential operations remain approval-gated. |

## Text and multimodal providers

The text order is Gemini first, then configured Hugging Face, then MVI. Gemini's configured primary and fallback model are checked against Google's model catalogue at startup. A catalogue check is not the same as a successful generation request, so diagnostics report those evidence levels separately.

- **Gemini** is the primary generative text provider. It can receive signed Tier-0 Genesis function declarations only for an authenticated, allowlisted operator and relevant requests. The server independently validates registry identity, risk tier and arguments.
- **Hugging Face** is the configured secondary text provider and remains the voice ASR/TTS integration.
- **MVI** is the final text fallback. Its response is rejected when the upstream discloses that it returned a non-generative rule-engine template, so a template is never presented as a generated model answer.
- **Pollinations** is the current raster image provider. SVG/vector output is handled through the existing design path.
- **PDF/document processing, vision, voice, research, ecosystem context and memory** remain separate capability routes/services. Their availability depends on the relevant request path, credentials, entitlements and upstream health.

The backend provider status exposes model identifiers and configuration state only. It never returns provider secrets.

## Body cores and platform components

| Component | Assigned role |
| --- | --- |
| **USECT-ZERO / `core-zero`** | Defensive diagnostics, evidence collection, guarded healing and hardware/device bridge functions. A matched tool request does not silently downgrade to generic text if the selected tool is unavailable. |
| **Genesis / USECT-ONE / `core-one`** | Guarded invention, tool registry, sandbox checks, signed tools and proposal lifecycle. Registry and Guardian checks remain authoritative. |
| **Infinite Mind / USECT-TWO / `core-two`** | Model-free observation, ranking, learning and proposal-only improvements. It does not independently merge or deploy changes. |
| `core_auditor` | Append-only/tamper-evident audit ledger and compliance evidence. |
| `core_billing` | Licensing, claims and entitlement policy for platform capabilities. |
| `core_evolve` | Reviewable evolution proposals and evaluation records. |
| `core_foundry` | Build planning, manifest validation and controlled lifecycle transitions. |
| `core_inspector` | Registered route/capability introspection. |
| `core_meter` | Usage accounting and summaries. |
| `core_migrate` | Device enrollment, migration planning and artifact verification. |
| `core_seed` | Licensed child provisioning and offline verification. |
| `core_uncopyable` | Recipe, hardware identity, license and integrity gates. |
| `services.conversation_store`, `services.memory_service`, `services.memory_store` | Bounded conversation sessions and authenticated, user-scoped Smart Memory persistence. |
| `core` | Shared Python runtime configuration, logging and security primitives. |

The ecosystem registry connects Biashara, Shamba, Elimu and Community providers through the approved RevelaCode gateway. RevelaAI must not bypass that gateway to access platform MongoDB records.

## Request flow

```text
HTTP request
  -> authenticate identity / establish session
  -> Global Brain Adapter (hub, tone, available capabilities)
  -> intent + capability routing
  -> specialist dispatch (image / USECT-ZERO / operator tool / normal request)
  -> Orchestrator (domains, platform context, research, evidence)
  -> grounded system prompt + signed tool catalogue when authorized
  -> Gemini -> Hugging Face -> MVI (configured fallback order)
  -> server-side tool-result verification / response validation
  -> session + entitlement-gated long-term memory
  -> Brain OS delivery telemetry
  -> structured response with provider, model, hub and routing metadata
```

## Operational diagnostics

- `/health`: lightweight service and provider configuration summary.
- `/ready`: determines whether a configured text provider/model exists. The response explicitly says whether Gemini's model catalogue was validated and whether a generation smoke test was performed.
- `/api/brain/status`: consolidated view of the director, provider chain, ecosystem registry, source inventory and live Core Mesh snapshot. The Core Mesh status probe is read-only and cached briefly.

Source presence, environment configuration, successful model-catalogue lookup, and successful generation are different states. A module is not called live merely because its file exists. Actual user turns remain the strongest evidence of provider generation and end-to-end routing.
