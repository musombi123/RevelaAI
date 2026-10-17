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
