# Core Mesh wiring and RevelaAI Design Studio

## 1. Frontend configuration and secrets

The browser is allowed to know public routing values such as:

- `VITE_REVELAAI_API_URL=https://revelaai.onrender.com`
- `VITE_API_BASE_URL=https://revelacode-backend.onrender.com`

Those URLs identify public HTTP services. They are not credentials.

Never place any of these in a `VITE_*` variable, JavaScript bundle, browser local/session storage, APK resource, or client request body:

- `USECT_ZERO_ADMIN_TOKEN`, `USECT_ZERO_BRAIN_TOKEN`
- `GENESIS_ADMIN_TOKEN`, `GENESIS_SIGNING_KEY`
- `MIND_ADMIN_TOKEN`
- `JWT_SECRET`, `GEMINI_API_KEY`, `POLLINATIONS_API_KEY`
- `REVELAAI_SERVICE_KEY`, database URLs, license private keys, or owner/action approval tokens

Vite embeds `VITE_*` values into downloadable JavaScript. Anyone can inspect the browser bundle, WebView APK assets, or network requests. A public API base URL is expected; an admin/core/signing credential would give an attacker the same authority as the service account.

## 2. Core Mesh route and service trace

### Private service layout

The Render Blueprint in this repository defines these private services:

| Render service | Runtime | Purpose | Public health route |
|---|---|---|---|
| `usect-zero-core` | Go private service | ZERO diagnostics, scoped brain operations and guarded recovery | `/v1/health` |
| `genesis-core-one` | Go private service | Genesis invention proposals and signed-tool registry | `/v1/genesis/health` |
| `infinite-mind-core` | Go private service | Mind metrics, candidate evaluation and guarded evolution | `/v1/mind/health` |
| `RevelaAI` | FastAPI web gateway | Authenticates the user, proxies to private cores and runs Gemini tools | `/_fastapi/health` |

`render.yaml` uses Render `fromService` references to inject private host:port addresses and matching core credentials. These values are resolved by Render; the frontend must never receive them.

### Why the supplied dashboard reports 0/3

The dashboard calls `GET /api/core-mesh/dashboard` in `fastapi_routes/core_mesh.py`. That calls `get_core_mesh_dashboard()` in `ai/core_mesh.py`, which probes the public read-only health routes:

- ZERO: `USECT_ZERO_URL` or `USECT_ZERO_BASE_URL` + `/v1/health`
- Genesis: `GENESIS_BASE_URL` + `/v1/genesis/health`
- Infinite Mind: `MIND_BASE_URL` + `/v1/mind/health`

The URL resolver is `services/core_config.py:core_base_url()`. It intentionally returns an empty URL in production if the environment variable is absent; it does not silently fall back to localhost. The fetch helper then returns `core_service_not_configured`.

This is different from a service that has a URL but is stopped: that path returns an upstream connection/unavailable diagnostic. The three `core_service_not_configured` diagnostics in the supplied dashboard therefore point to missing/empty gateway routing values (or a Render Blueprint that has not been synced/provisioned), not merely bad tokens.

The health endpoints for all three cores are read-only and do not require the mutation/admin credentials. Consequently:
- A missing `USECT_ZERO_BRAIN_TOKEN` does **not** explain ZERO's public health probe failing; it disables the separate user-side scoped ZERO tool identity.
- A missing `GENESIS_ADMIN_TOKEN` does **not** explain Genesis public health failing; it blocks authenticated Genesis status/registry/proposal requests.
- A missing `MIND_ADMIN_TOKEN` does **not** explain Mind public health failing; it blocks Mind mutations.
- A missing `GENESIS_SIGNING_KEY` disables valid signed-tool creation/verification; it is not the cause of a missing Genesis URL.

### User-side AI versus admin Core Mesh

Normal chat enters through `POST /ai` in `fastapi_routes/ai.py`, then `services/ai_service.py:process_message()`, and Gemini tool dispatch in `ai/gemini_tool_gateway.py:dispatch_gemini_tool()`. It does not call the `/api/core-mesh/*` dashboard/admin routes.

There is one important exception to the broad claim that Core Mesh configuration never affects user-side AI: the scoped ZERO tools. When Gemini selects a ZERO tool, the path is:

`dispatch_gemini_tool()` → `ai/usect_zero_tools.py:execute_tool()` → `services/usect_zero_client.py:request_core()` → private `usect-zero-core`.

That path requires the dedicated `USECT_ZERO_BRAIN_TOKEN` (sent as a scoped API key) and the ZERO private URL. It does **not** use `USECT_ZERO_ADMIN_TOKEN` or the dashboard admin routes. So ordinary chat and non-ZERO tools remain independent, but the screenshot's missing ZERO brain token can make those particular user-side ZERO tools unavailable.

Genesis signed-tool declarations are added to Gemini only for a user who has the Core Mesh operator identity and the required automation entitlement. Core-One/Core-Two proposal and mutation endpoints remain operator/entitlement-gated. Do not broaden those permissions to make the dashboard green.

## 3. Environment variable matrix

The "runtime observation" column uses the dashboard text supplied with the incident. The GitHub repository shows the intended Render Blueprint wiring; it does not grant access to the live Render environment, so live values cannot be independently read here.

| Variable | Service(s) that need it | Runtime observation | Purpose / action |
|---|---|---|---|
| `USECT_ZERO_URL` and `USECT_ZERO_BASE_URL` | RevelaAI gateway | Effective URL appears missing: ZERO says `core_service_not_configured` | Private ZERO host:port. Blueprint links both to `usect-zero-core` hostport. |
| `USECT_ZERO_BRAIN_TOKEN` | `usect-zero-core` + RevelaAI gateway | Gateway reports Missing | Scoped identity for user-side Gemini ZERO tools. Generated on ZERO; gateway imports the exact same value with `fromService`. |
| `USECT_ZERO_ADMIN_TOKEN` | `usect-zero-core` + RevelaAI gateway | Configured in supplied dashboard | Separate administrator credential. Keep same value on both services. |
| `USECT_ZERO_ENABLED=true` | RevelaAI gateway | Enabled in supplied dashboard | Enables the ZERO adapter; the new diagnostics endpoint checks it. |
| `GENESIS_BASE_URL` | RevelaAI gateway + Infinite Mind | Effective URL appears missing: Genesis says `core_service_not_configured` | Private Genesis host:port. Blueprint links it from `genesis-core-one`. |
| `GENESIS_ADMIN_TOKEN` (gateway also accepts legacy `GENESIS_TOKEN`) | `genesis-core-one` + RevelaAI gateway + Infinite Mind | Gateway reports Missing | Authenticates remote Genesis status, registry and proposal calls. Blueprint generates on Genesis and links the exact value to gateway and Mind. The core service itself reads `GENESIS_ADMIN_TOKEN`. |
| `GENESIS_SIGNING_KEY` | `genesis-core-one` only | Dashboard showed Unknown because Genesis health was unavailable | Ed25519 signing material for the signed registry. Must be base64 for a 32-byte seed or 64-byte private key. Do not use a generic random text string. |
| `GENESIS_ORCHESTRATOR_TOOLS_ENABLED=true` | RevelaAI gateway | Enabled in supplied dashboard | Allows the authorized Genesis tool catalogue path. It does not bypass operator or approval checks. |
| `GENESIS_OWNER_APPROVAL_TOKEN` | Genesis + RevelaAI gateway | Not shown by supplied dashboard | Optional owner approval path for higher-risk activation. Blueprint links the Genesis-side value to the gateway. |
| `GENESIS_ACTION_APPROVAL_TOKEN` | Genesis + RevelaAI gateway | Not shown by supplied dashboard | Optional action approval path. Blueprint links the Genesis-side value to the gateway. |
| `GENESIS_OWNER_USER_IDS` | RevelaAI gateway | Not shown by supplied dashboard | Canonical owner IDs for Tier 1/2 signed-tool approval. |
| `MIND_BASE_URL` | RevelaAI gateway | Effective URL appears missing: Mind says `core_service_not_configured` | Private Infinite Mind host:port. Blueprint links it from `infinite-mind-core`. |
| `MIND_ADMIN_TOKEN` | `infinite-mind-core` + RevelaAI gateway | Configured in supplied dashboard | Authenticates Mind mutations; health and metrics reads are public/read-only. Blueprint links the same generated value to the gateway. |
| `CORE_MESH_ADMIN_USER_IDS` (alias `META_ENGINEER_ADMIN_USER_IDS`) | RevelaAI gateway | Configured in supplied dashboard | Comma-separated canonical RevelaCode user IDs permitted to operate the mesh. Keep the server-side operator allowlist. |
| `USECT_ZERO_BASE_URL`, `USECT_ZERO_ADMIN_TOKEN` | Infinite Mind | Blueprint declares both as private-service links | Lets Mind proxy to ZERO without public URLs or browser credentials. |
| `GENESIS_BASE_URL`, `GENESIS_ADMIN_TOKEN` | Infinite Mind | Blueprint declares both as private-service links | Lets Mind proxy to Genesis. |

### Secret formats

- The four ordinary service tokens (`USECT_ZERO_ADMIN_TOKEN`, `USECT_ZERO_BRAIN_TOKEN`, `GENESIS_ADMIN_TOKEN`, `MIND_ADMIN_TOKEN`) can be 32-byte cryptographically random hex strings. The Blueprint already uses Render `generateValue: true` for these on the owning core and `fromService` to share the exact value with the gateway.
- `GENESIS_SIGNING_KEY` is different. Genesis decodes it as base64 Ed25519 key material and accepts exactly a 32-byte seed or 64-byte private key. The Blueprint now marks it `sync: false` so a valid key can be entered explicitly.

PowerShell command to generate one ordinary 256-bit token locally if manual setup is necessary:

```powershell
[Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

PowerShell command to generate a valid 32-byte Ed25519 seed encoded as Base64:

```powershell
[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Run each command locally. Never paste the resulting values into chat, source code, Vite variables, browser storage or GitHub. If manually configuring a token, generate it once and set the same value on every service listed in the table. Prefer the Blueprint's `generateValue` + `fromService` wiring so Render maintains that equality automatically.

## 4. Manual Render repair procedure

1. Open Render Dashboard → **Blueprints** → the RevelaAI Blueprint → **Sync**. The repository's `render.yaml` already declares the private services and `fromService` links. Syncing is the first action because the supplied diagnostics show that the running gateway is not resolving the expected private URLs.
2. Confirm these four services exist and are deployed: `RevelaAI`, `usect-zero-core`, `genesis-core-one`, `infinite-mind-core`. The three core services must remain **Private Services**. Do not expose their ports publicly.
3. Open `usect-zero-core` → Environment. Confirm Render generated `USECT_ZERO_ADMIN_TOKEN` and `USECT_ZERO_BRAIN_TOKEN`. Do not create a second, different value on the gateway. The Blueprint's `fromService` links should populate the gateway with those exact values.
4. Open `genesis-core-one` → Environment. Confirm `GENESIS_ADMIN_TOKEN` is generated. Set `GENESIS_SIGNING_KEY` using the Base64 PowerShell command above. Keep it only on this Genesis service. If you use Tier 1/2 owner approval, configure `GENESIS_OWNER_APPROVAL_TOKEN` and `GENESIS_ACTION_APPROVAL_TOKEN` here; the gateway links them using `fromService`.
5. Open `infinite-mind-core` → Environment. Confirm `MIND_ADMIN_TOKEN` is generated. Confirm its Blueprint-linked `USECT_ZERO_BASE_URL`, `USECT_ZERO_ADMIN_TOKEN`, `GENESIS_BASE_URL` and `GENESIS_ADMIN_TOKEN` references exist.
6. Open `RevelaAI` → Environment. Confirm these private references are present: `USECT_ZERO_URL`, `USECT_ZERO_BASE_URL`, `USECT_ZERO_ADMIN_TOKEN`, `USECT_ZERO_BRAIN_TOKEN`, `GENESIS_BASE_URL`, `GENESIS_ADMIN_TOKEN`, `MIND_BASE_URL`, `MIND_ADMIN_TOKEN`. Confirm `USECT_ZERO_ENABLED=true` and `GENESIS_ORCHESTRATOR_TOOLS_ENABLED=true`.
7. On the same `RevelaAI` service, confirm `CORE_MESH_ADMIN_USER_IDS` contains the exact canonical RevelaCode user ID for the operator account. Do not use a display name or a browser-side role flag. Do not remove the existing allowlist check.
8. Deploy the three core services first, then deploy/restart `RevelaAI` so the gateway receives the private service references. Do not put any of these variables into the frontend's Vite environment.
9. Sign in as an allowlisted administrator and open Administration → Core systems → USECT Core Mesh. The new **Server configuration diagnostics** panel calls the operator-only `GET /api/core-mesh/configuration` endpoint and explains missing settings by variable name only. It also tests the gateway Genesis token against Genesis' read-only authenticated status route, so a present-but-mismatched token is shown as rejected rather than green. Select **Check configuration**, then **Refresh status**.
10. Interpret the result:
    - `core_service_not_configured`: the gateway still has no private base URL; re-check Render Blueprint links and service names.
    - upstream connection/unavailable: the URL exists, but the private service is stopped, unhealthy or still deploying; inspect that service's deploy logs.
    - HTTP 401 on Genesis status/registry: the gateway's `GENESIS_ADMIN_TOKEN` does not match the Genesis service token.
    - signing key invalid/missing: set a valid Base64 Ed25519 key on Genesis and redeploy it.
    - 0/3 should only change when the actual read-only health probes respond. A configured token alone does not make a core reachable.

Human approval, Guardian enforcement, signed artifact verification, operator allowlisting and the no-automatic-merge policy remain unchanged.

## 5. Image generator: findings and new flow

### Previous implementation

The existing raster path uses the Pollinations image endpoint at `https://gen.pollinations.ai`, default model `flux`, and server-side `POLLINATIONS_API_KEY`. The model and fallback are controlled by `POLLINATIONS_IMAGE_MODEL` and `POLLINATIONS_IMAGE_FALLBACK_MODEL`; fallback is intentionally empty by default. The request timeout is `POLLINATIONS_IMAGE_TIMEOUT` (default 120 seconds).

`ai/image_prompt.py` already classified some artefacts and tried to mark text-aware requests. However, `ai/ai_client.py:generate_hf_image()` explicitly discards `has_text` (`del has_text`). That means a poster/flyer sent down the raster path still asks a diffusion image model to draw letters. Diffusion models can approximate lettering but cannot guarantee exact spelling, line breaks or typographic hierarchy. The prior service also had only an SVG-vs-raster branch; most poster/social requests went to raster. Finally, the native FastAPI app had no generated-image GET route even though responses constructed `/ai/images/<filename>` URLs.

### New two-path pipeline

- **Design path:** `POST /ai` → image intent router → existing configured text model via `ask_hf()` writes a structured JSON design brief → Pillow template renderer draws exact copy and layout. The model controls layout, palette, typography style, hierarchy and motifs; user-supplied copy is extracted and preserved verbatim unless the user explicitly asks for translation.
- **Eight templates:** poster, flyer, Instagram post, story, WhatsApp status, business card, certificate and logo sheet.
- **Safe area:** templates reserve at least 8.5% of the canvas for safe margins. RevelaCode's blue/green/gold palette is the default brand palette; a requested colour overrides it.
- **Backgrounds:** when the user requests a photo/realistic background (or sets `use_ai_background`), the existing Pollinations provider creates a text-free background; the code renderer overlays exact copy afterward.
- **Illustration path:** photo/artwork requests continue to use the already-configured Pollinations provider/model, with a prompt enhancer for composition, focal point, lighting, depth and colour. No new provider was added.
- **Formats and sizes:** 1:1, 4:5, 9:16, 16:9 and A4 are supported. Design and illustration assets export PNG, JPG and PDF. The PNG remains the chat preview; all three downloads are returned in response metadata.
- **Revisions:** the backend now reuses the frontend's `sessionId`/conversation ID. Short follow-ups such as "change the colour to green", "make the title bigger" or "use Swahili" revise the previous design brief in the same conversation.
- **Serving and Android:** `GET /ai/images/{filename}` serves only generated files with strict filename/path checks. The frontend shows PNG/JPG/PDF download links. The Android Capacitor WebView uses Android's DownloadManager for these secure generated-media downloads; no desktop-only browser API is required.
- **Reliability:** Pollinations requests retry once only for transient timeouts/network/server failures. Authentication/permission failures are not retried. The API returns a friendly timeout or temporary-unavailability message.

The design revision state is held in the existing bounded process-local conversation session store. It survives messages in the same live gateway process, but a Render process restart/redeploy clears that in-memory revision state. Generated files also use the configured temporary image directory and its retention cleanup; they are not a permanent asset library.

## 6. Important safety boundaries retained

- Browser receives public API URLs and user JWTs only.
- Core credentials remain server-side and are passed service-to-service.
- Genesis signatures are validated using Ed25519 key material; signing is not enabled by merely setting a random text string.
- The dashboard remains read-only for status. Proposal/evolution/activation routes retain operator and entitlement checks.
- Genesis remains proposal-only; Guardian decisions, signed-artifact checks, explicit human approvals and no-auto-merge behavior are not relaxed.
