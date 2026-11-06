# Sci-Core IP Guard deployment and operations

Sci-Core IP Guard is a **persistent application-edge control for the RevelaAI ASGI service**. It stores exact public-IP blocks and audit events in the existing \`revelai\` MongoDB database, then rejects matching requests in \`asgi.py\`. It does not change Render's Cloudflare edge policy, Render host firewall, Nginx, or the separate RevelaCode Backend.

## Required Render environment configuration

The IP Guard is intentionally unavailable when durable MongoDB storage is unavailable. Keep the existing \`MONGO_URI\` configured for the RevelaAI service.

For a standard Render public web-service ingress, use Cloudflare's client-IP header:

- `REVELAAI_TRUST_CLOUDFLARE_IP_HEADER=true`

Render states that inbound public web-service traffic passes through Cloudflare. Cloudflare documents `CF-Connecting-IP` as the single visitor IP header sent to the origin and recommends it over parsing `X-Forwarded-For`. Enable this setting only for the Render service behind its normal Cloudflare ingress. Do not expose a separate untrusted origin path that bypasses that ingress while trusting this header.

Fallback for a separately verified proxy chain only:

- `REVELAAI_TRUST_PROXY_HEADERS=true`
- `REVELAAI_TRUSTED_PROXY_HOPS=<verified number of trusted proxy hops>`

The fallback selects from the right based on the configured hop count. Do not copy an assumed value such as 1 or 2 without observing the actual header chain for the service. An incorrect count can select a proxy or an attacker-supplied address. Do not trust `X-Real-IP`.

When no trusted public client address can be established, IP-based blocking is not applied and the status endpoint does not claim a verified client IP.
Optional administrator safety allowlist:

- \`SCI_CORE_IP_ALLOWLIST=<your-stable-admin-public-ip>/32\`
- For IPv6, use \`<your-stable-admin-ipv6>/128\`.
- Multiple addresses/networks are comma-separated.

The allowlist is checked before both manual and automatic blocks. Automatic blocking is disabled until at least one stable administrator egress IP/network has been explicitly allowlisted. The API also refuses to block the public IP used by the administrator's current session when it can reliably resolve it. This prevents a burst of expired-admin-token requests on an administrator's shared network from locking out the operator.

## What is enforced

- Manual block: one exact, globally routable IPv4 or IPv6 address. CIDR ranges, private addresses, loopback, multicast, unspecified and documentation/test ranges are rejected.
- Duration: 5 minutes through 7 days. The dashboard offers 15 minutes through 7 days.
- Reason: required and audited.
- Automatic response: only after SCI_CORE_IP_ALLOWLIST is configured, 50 HTTP 401 responses from the same non-allowlisted public IP within a rolling 5-minute window on \`/api/auth/\`, \`/auth/\`, or \`/api/sci/\` endpoints creates a 30-minute \`auto_bruteforce\` block.
- Unblock: administrator-only, reasoned and audited.
- Audit: actor, source, IP, reason, action and timestamp. Failed-auth records contain IP, endpoint path and timestamp only; authorization headers, passwords, request bodies and tokens are never persisted.

The threshold is intentionally high to reduce accidental blocks from shared NATs. Automatic blocking only sees requests that reach the RevelaAI service; it does not observe sign-in attempts sent directly to the separate RevelaCode Backend.

## Administrator API

All routes require the existing RevelaCode-verified platform administrator bearer session:

- \`GET /api/sci/ip-guard/status\`
- \`POST /api/sci/ip-guard/block\` with \`{ "ip": "...", "reason": "...", "duration_minutes": 60, "confirm": true }\`
- \`POST /api/sci/ip-guard/unblock\` with \`{ "ip": "...", "reason": "..." }\`

A degraded IP Guard status means MongoDB persistence could not be verified. Manual block/unblock calls fail with HTTP 503 in that state. The service does not pretend a block succeeded if the write cannot be persisted.

## Operational verification

1. Set the Render environment variables above and deploy the backend change.
2. Open Administration → Core systems → Sci-Core Defensive Core.
3. Confirm the IP Protection panel reports \`active\`, \`persistent: true\`, and \`enforcement: application_edge\`.
4. Confirm the displayed client IP matches the administrator's actual public egress IP before attempting any block. If it is unresolved or incorrect, fix the trusted proxy configuration first.
5. Block a known test public IP address you control for 5–15 minutes, then make a request to the RevelaAI service from that source. It should receive HTTP 403 with \`SCI_CORE_IP_BLOCKED\`.
6. Release the test block from an allowed administrator IP and verify an \`unblocked\` audit event.
7. Do not test by blocking your own current IP or a shared office/mobile-carrier NAT.

## Limits

This is application-layer rejection after a request reaches the RevelaAI ASGI process. Render's own edge protection still handles network-layer DDoS filtering; Sci-Core handles selected application-level sources. To block traffic to RevelaCode Backend, the same control must be implemented and deployed in that backend independently.
