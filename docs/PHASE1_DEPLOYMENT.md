# RevelaAI Phase 1 Deployment Checklist

## Review branches

- RevelaAI: feature/global-productivity-phase1
- RevelaCode Frontend: feature/global-productivity-phase1
- RevelaCode Backend: feature/smart-ai-tiered-tool-entitlements

These are review branches, not production deployments.

## RevelaAI environment variable names

Existing provider credentials remain unchanged. New names introduced by this phase:

- REVELAAI_PRODUCTIVITY_DIR — absolute private directory for generated files. Use a mounted persistent disk, not the default ephemeral /tmp, for production.
- REVELAAI_FILE_SIGNING_SECRET — random secret of at least 32 bytes used to sign expiring download links. If omitted, the existing server-side JWT_SECRET may be used as a fallback; a dedicated key is recommended.
- SANDBOX_SERVICE_URL — private HTTPS address of the dedicated sandbox controller.
- SANDBOX_SHARED_SECRET — random HMAC key shared by RevelaAI and the sandbox controller. Keep it server-side only.
- REVELAAI_TOOL_RESEARCH_GLOBAL_ENABLED
- REVELAAI_TOOL_SPREADSHEET_ENABLED
- REVELAAI_TOOL_WORD_ENABLED
- REVELAAI_TOOL_POWERPOINT_ENABLED
- REVELAAI_TOOL_SANDBOX_PYTHON_ENABLED — optional deployment-level tool switches. Persistent platform-admin switches take precedence.
- SEARXNG_BASE_URL — optional SearXNG instance. Leave unset to use existing SerpAPI configuration and public DuckDuckGo fallback.
- Existing SERPAPI_API_KEY or SERPAPI_KEY is reused when configured; no new SerpAPI key is required if it is already present.

No new third-party text-model key is introduced.

## Separate sandbox host

Deploy sandbox-service on a dedicated Linux host, not alongside the RevelaAI API, MongoDB or primary application secrets. Build the runner and controller images. Install gVisor and verify that Docker reports a runsc runtime. The service refuses execution when gVisor or the approved worker image is missing.

Recommended starting host size: 4 vCPU, 8 GB RAM and 25 GB disk; 16 GB RAM is preferable for concurrent scientific workloads. Limit concurrency and monitor memory/disk usage. Use a private VPN or private service network between RevelaAI and this host. Do not expose the Docker controller publicly.

## Database

The existing SQLAlchemy platform database gains table revela_productivity_tool_controls. The current startup calls Base.metadata.create_all; this creates the new table on the next application startup. For controlled production rollout, include the table in the existing database migration process before exposing admin controls. No Mongo collections or second application database are added.

## Deployment order

1. Review and merge the backend feature-allowlist PR.
2. Review and merge the RevelaAI PR; run tests and deploy the existing RevelaAI service.
3. Review and merge the frontend PR and deploy the web frontend. The Capacitor Android WebView consumes the same web UI; rebuild the APK only after web acceptance.
4. Provision persistent private file storage and set REVELAAI_PRODUCTIVITY_DIR.
5. Build and harden the separate gVisor service, test no-network and resource limits, configure private connectivity, then set SANDBOX_SERVICE_URL and SANDBOX_SHARED_SECRET.
6. Keep sandbox disabled until a successful isolated execution drill passes.

## Rollback

Disable new tool switches from the platform-admin tool controls or set the relevant environment variable to false. Remove the Tools panel import from the AI dashboard if the frontend needs reverting. Existing chat, voice, vision, image generation and core routes are separate and remain intact.
