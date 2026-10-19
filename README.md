# **RevelaCode / RevelaAI — README**

## 🚀 **RevelaCode | Where Faith Meets Intelligence**

RevelaCode is a next-generation, AI-powered platform designed to bridge ancient scripture with modern technology. Built for the digital generation, it transforms biblical verses, symbols, and prophecies into structured, interactive, and meaningful insights through intelligent computation.

RevelaAI — the intelligent assistant within the ecosystem — serves as a personal companion for curiosity, learning, and growth, engaging users in human-like dialogue across science, philosophy, technology, and spirituality.

---

## 🎯 **Vision**

To make wisdom accessible, interactive, and future-proof by fusing AI, faith, and culture into one seamless digital experience.

---

## 🧠 **What This Platform Does**

* Decodes scripture using structured logic and AI-assisted reasoning
* Provides conversational AI through **RevelaAI**
* Delivers intuitive, professional UI/UX for seamless exploration
* Supports continuous learning and knowledge expansion
* Maintains secure and private user interactions

---

## 🛠 **Tech Stack**

**Frontend**

* HTML, CSS, JavaScript
* Responsive UI with modern layout principles

**Backend**

* Node.js
* RESTful APIs
* Regex-based text processing
* Caching for performance optimization

**Deployment**

* Cloud-hosted frontend
* GitHub for version control and collaboration

---

## 🔗 **Live Links**

* 🌐 **RevelaAI / RevelaCode Frontend:** [https://revelacode-frontend.onrender.com/](https://revelacode-frontend.onrender.com/)
* 🧑‍💻 **Backend Repository:** [https://github.com/musombi123/RevelaCode-Backend](https://github.com/musombi123/RevelaCode-Backend)

---

## 📂 **Project Structure (High-Level)**

```
/frontend
  ├── index.html
  ├── stylesheet.css
  ├── assets/
  └── scripts/

/backend
  ├── server.js
  ├── routes/
  ├── controllers/
  └── utils/
```

---

## 🏗 **Key Features**

### 🔹 RevelaAI Capabilities

* Conversational intelligence
* Cross-disciplinary knowledge
* Personalized learning guidance
* Secure and private interaction
* Continuously updated knowledge base

### 🔹 RevelaCode Capabilities

* Scripture analysis engine
* Prophecy decoding dashboard
* User profile & settings panel
* AI-powered interpretation tools

---

## 👨‍💻 **Creator**

**Musombi William**
Founder & Lead Engineer — RevelaCode
Full-Stack Developer | Tech-Faith Innovator

📧 [musombiwilliam769@gmail.com](mailto:musombiwilliam769@gmail.com)
🔗

 
## USECT Core Mesh: Core-Zero + Genesis (Core-One) + Infinite Mind (Core-Two)

### Render deployment wiring

The root `render.yaml` blueprint defines the public RevelaAI Flask gateway and three private Go services: `usect-zero-core`, `genesis-core-one`, and `infinite-mind-core`. Keep the cores private; the gateway uses Render's private `hostport` references and imports each core's server-side token with `fromService`. Both `USECT_ZERO_URL` (gateway adapter) and `USECT_ZERO_BASE_URL` (Core Mesh dashboard and Mind proxy) must refer to the same Core-Zero service. Core-One and Core-Two similarly use `GENESIS_BASE_URL` and `MIND_BASE_URL`. The Python gateway and Core-Two normalize Render's internal `service-name:port` references to HTTP and permit clear-text only to loopback/internal single-label service names; public hosts must use HTTPS.

After syncing the Blueprint, verify each service's health endpoint and then refresh RevelaCode Admin → Core Mesh. A green application root or a healthy gateway does not by itself prove all three cores are connected. The dashboard must show `reachable: true` for ZERO, ONE and TWO. This blueprint must be synced/applied in Render; merging the file alone does not provision services or edit existing environment values.


RevelaAI exposes a server-side Core Mesh integration for authenticated status, orchestrator routing metadata, and operator-triggered proposals:

- `GET /api/core-mesh/dashboard` — safe, credential-free status for ZERO, Genesis, and Infinite Mind.
- `POST /api/core-mesh/genesis/invent` — submit an invention demand to Genesis through the Mind proxy; returns a proposal only.
- `POST /api/core-mesh/mind/evolve` — request a guarded Core-Two evolution proposal; it does not merge or deploy it.

Configure service origins in the RevelaAI service environment (never commit tokens): `USECT_ZERO_BASE_URL`, `GENESIS_BASE_URL`, and `MIND_BASE_URL`. Local defaults use loopback ports 8780/8781/8782 and are only suitable when all daemons share the same host. For separately deployed services, set each origin to its HTTPS service URL. The Mind service also needs its existing `USECT_ZERO_BASE_URL` and `GENESIS_BASE_URL` values so its proxy can reach both cores.

The RevelaAI server uses `MIND_ADMIN_TOKEN` for proposal requests and `GENESIS_ADMIN_TOKEN` (or `GENESIS_TOKEN`) for Genesis proxy authentication. These must match the server-side settings of the corresponding core services. Add comma-separated approved operator user IDs in `CORE_MESH_ADMIN_USER_IDS` to enable proposal controls; `META_ENGINEER_ADMIN_USER_IDS` is accepted as a fallback. The browser never receives these secrets. Normal chat/orchestration only produces advisory routing metadata and cannot trigger an invention/evolution. Guardians remain authoritative, and all proposed changes require human review; automatic execution and automatic merge remain disabled.

### Production runtime configuration

- **USECT-ZERO gateway and dashboard:** set `USECT_ZERO_ENABLED=true`. The dashboard uses `USECT_ZERO_BASE_URL`; the gateway accepts `USECT_ZERO_URL` as its explicit override and falls back to `USECT_ZERO_BASE_URL` when the override is empty. Point them at the same deployed Core-Zero origin.
- **USECT-ZERO admin operations:** set `USECT_ZERO_ADMIN_TOKEN` on both RevelaAI and the Core-Zero service to the same strong secret. A successful health probe proves reachability only; it does not prove that the admin token matches or that the key-management store is writable.
- **JWT:** `JWT_SECRET` must match the signing secret used by RevelaCode Backend and be at least 32 random bytes for HS256. Rotate it on both services as one coordinated change; changing only one side breaks token verification until both sides match and users obtain valid sessions.
- **Gemini:** set `GEMINI_MODEL=gemini-3.8-flash` and `GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite` in the RevelaAI Render environment. Environment values override source defaults. If a configured model responds with 404, the code currently falls back, but keeping the primary model current avoids a failed provider call on each new chat.

## RevelaAI Smart Memory v2 — deployment configuration

RevelaAI stores filtered conversation memory in the separate MongoDB database `revelai`. It does not read or write `revelacode.users`; user existence is verified through the protected RevelaCode endpoint.

Configure these server-side environment variables in the RevelaAI deployment (never commit secrets):

- `MONGO_URI`: the same MongoDB Atlas Cluster0 connection string used by RevelaCode.
- `JWT_SECRET`: the same JWT signing secret as RevelaCode so incoming Bearer tokens can be validated.
- `REVELACODE_BACKEND_URL=https://revelacode-backend.onrender.com`
- `REVELAAI_SERVICE_KEY`: a long, random shared service secret; configure the exact same value in both RevelaAI and RevelaCode-Backend. Never expose it to the browser or commit it.
- Optional: `REVELACODE_VERIFY_TIMEOUT_SECONDS=4`.

RevelaCode-Backend remains the source of identity. The frontend can use `GET /api/auth/me` with its existing Bearer JWT to retrieve the canonical `userId`. RevelaAI validates the signed JWT, checks that its subject matches the requested user ID, and calls `GET /api/auth/verify/:userId` using `X-REVELAAI-SERVICE-KEY`. Memory requests fail closed if identity verification is unavailable.

Memory API (all user-specific requests require a valid Bearer JWT):

- `POST /api/memory/chat` — filters and saves useful conversation turns.
- `GET /api/memory/:userId` — returns the authenticated user's bestThings.
- `POST /api/memory/ideas` and `GET /api/memory/ideas/:userId` — deduplicated ideas.
- `POST /api/memory/ideas/:ideaId/implementation` — records a reviewed implementation artifact and reference; submitted code is never executed by this endpoint.
- `DELETE /api/memory/useless/:userId` — prunes legacy noise from stored conversation messages.

Noise is discarded before persistence. Idea records are proposals with status `new`; generated chat text is not executed as code or written into production files automatically. Implementation should be tested and reviewed before being marked implemented.


## Worldwide country adapters and user-taught learning

**Born in Nairobi, Built for Worldwide.** Kenya remains the default country profile (KE) for backward compatibility. Requests may send a country and language; the shared adapters provide a country-specific currency label, supplier directory, language choice, nominal electrical reference and local-regulation reminders. Supplier names are lookup leads, not verified quotes or stock. Electrical guides require datasheet and qualified local review.

### Unknown-topic learning lifecycle

1. The existing orchestrator compares a niche request against the local Core-One inventory and human-published Living Brain records. A low-evidence specialist request is marked unknown; it is not repeatedly retried or sent to the language model to invent technical steps.
2. The chat asks for one to three safe steps. An authenticated caller may submit the teaching packet to POST /v1/learn/unknown. The API accepts text steps and an optional SHA-256 photo reference, not raw image bytes.
3. Content is screened before it is stored. Matching restricted content is rejected and only a minimized audit record is written. Submitted notes are private by default; cross-user use requires explicit consent_to_share: true.
4. With that consent, RevelaAI may ask the existing Core-One Genesis to create a proposal. The result is await_merge, not a deployed endpoint. Genesis retains its own Guardian; no automatic execution or merge is enabled.
5. Only an authenticated Core Mesh operator may publish a shared knowledge record, attesting that the tool and endpoint were reviewed/merged and providing a merge commit SHA. Publication requires a consented submission. At that point, existing Core-Two Mind may stage one improvement proposal, which also remains await_merge.
6. GET /v1/learn/known returns only explicitly shared, human-reviewed records. It does not disclose the submitter's user ID.

### Learning API and deployment

- POST /v1/learn/unknown: requires the normal RevelaCode Bearer JWT. Body fields: topic, steps (1–12 strings), optional country, language, photo_hash, source_request, and explicit Boolean consent_to_share.
- GET /v1/learn/known: authenticated list of reviewed, shareable knowledge and the staged improvement status, if any.
- POST /v1/learn/known/{topic_key}/publish: authenticated Core Mesh operator only. Attests review/publication with tool_name, endpoint and merge_commit. The server checks input format and consent; the operator remains responsible for confirming the merge really exists.
- Configure REVELAAI_LEARNING_ROOT to a persistent, access-controlled storage directory in production. Defaults point to the repository's living-brain/ folder for local development. The application needs write permissions; back up and restrict this directory.

This feature is a deterministic unknown detector plus a reviewed learning workflow. It is not proof of AGI, perfect safety detection, legal compliance, or uncopyability. RVX/provider secrets must remain in server-side secret storage and never in public commits.
