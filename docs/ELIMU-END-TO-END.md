# Elimu Hub: End-to-End Contract

This feature branch adds a native FastAPI implementation for the Elimu learning workflow. It does not seed production hubs or claim live end-to-end acceptance. A deployment must use this FastAPI service as the frontend API origin, have published hub/course/lesson records, and configure authentication, CORS, persistence, and the certificate key pair.

## 1. API ownership and configuration

The frontend uses **only** `VITE_API_URL` for these features. Set it to the public base URL of the deployed service that runs this branch's `asgi:app`/FastAPI app, without a trailing slash. The existing `RevelaCode-Backend` repository's `main` branch is Flask-based and does not acquire these routes merely because this branch exists in `RevelaAI`. Pointing `VITE_API_URL` at that Flask deployment will not satisfy this API contract.

Set the actual allowed web origins in the FastAPI environment:

```text
CORS_ORIGINS=https://revelacode.co.ke,https://www.revelacode.co.ke
```

Include additional local or staging origins only if they are really used. This branch does not add fallback CORS origins. The server must also receive the same `JWT_SECRET` as the existing RevelaCode HS256 access-token issuer. Never commit its value.

For the Elimu store, configure `MONGO_URI`. Learning documents default to database `revelai`; override with `REVELAAI_DATABASE_NAME` if the deployment intentionally uses another database. User identity remains represented by the verified RevelaCode JWT. The profile route requests additional account metadata from `REVELACODE_BACKEND_URL/api/user/me` when the upstream endpoint is available; absent metadata is shown as missing rather than guessed.

## 2. JWT and Start Modal

- Successful login persists the access token under `localStorage.revela_jwt`, while mirroring legacy token keys for compatibility.
- If the login response includes `refresh_token`, it is persisted as `revela_refresh_token`. If it includes only an access token and `VITE_API_URL` is configured, the frontend attempts a refresh-ticket exchange against `POST /api/auth/refresh`.
- Authenticated API requests include `Authorization: Bearer <access-token>`. Optional license state is sent as `X-Revela-License` only when stored locally.
- On a non-auth-entry 401, the shared request wrapper attempts one refresh and retries the original request once. A modal open/close does not remove tokens; explicit logout does.
- Refresh tokens cannot be used as access tokens. Refresh exchanges require a valid JWT and return an access token that expires in 30 minutes and a refresh token that expires in 30 days. These lifetimes are defined by this branch; they should be aligned with the product's security policy before a production rollout.

The refresh route is currently stateless: it validates signatures and expiry but does not maintain a server-side revocation/rotation ledger. Add server-side refresh-token tracking/revocation if logout must invalidate previously copied refresh credentials.

## 3. Elimu data contract

No demo hub is automatically inserted into production. The database collection `elimu_hubs` must contain published hub documents similar to:

```json
{
  "name": "Data Literacy",
  "slug": "data-literacy",
  "description": "Introductory data analysis and evidence-based reasoning.",
  "status": "published",
  "is_published": true,
  "skills": ["Data interpretation", "Critical thinking"],
  "instructors": [{"name": "Learning Team"}],
  "courses": [
    {
      "id": "course-foundations",
      "title": "Foundations",
      "description": "Core data-literacy concepts.",
      "skills": ["Reading charts"],
      "lessons": [
        {"id": "lesson-01", "title": "Understand a dataset"},
        {"id": "lesson-02", "title": "Read a chart"}
      ]
    }
  ]
}
```

Use stable unique hub, course, and lesson identifiers. A course with no lessons is displayable but cannot be marked completed; the system does not infer a 100% completion for an empty course. Existing upstream learning-material formats may need an explicit migration/adapter to this collection schema.

Progress is persisted per (JWT subject, hub ID) in `elimu_progress`. Completion actions are validated against the selected hub/course and recorded lesson IDs. Hub progress is computed from recorded lessons, not from a client-provided percentage.

## 4. Authenticated routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/auth/me` | Validate token and return its identity summary |
| POST | `/api/auth/refresh` | Exchange a valid access/refresh JWT for new signed tokens |
| GET | `/api/elimu/hubs` | List published hubs |
| GET | `/api/elimu/hubs/{hub_id}` | Return courses/lessons and current user's progress |
| GET | `/api/elimu/progress?hub_id=...` | Read current user's progress |
| POST | `/api/elimu/progress` | Start course, complete lesson, or complete a course |
| GET | `/api/accounts/profile/download?format=json` | Download full profile/activity payload as JSON |
| GET | `/api/accounts/profile/download?format=pdf` | Download a branded PDF profile/activity report |
| POST | `/api/certificates/generate` | Issue a certificate only after all recorded hub lessons are complete |
| GET | `/api/certificates/{cert_id}` | Download an issued certificate (owner-only) |
| GET | `/api/verify/certificate/{cert_id}` | Public certificate signature verification |
| GET | `/api/verify/certificate/public-key` | Public RSA key used to verify certificate signatures |

Errors are JSON and carry HTTP status codes; configuration/data failures are surfaced as 503/404/409 rather than silently returning fake success.

## 5. Account Profile export

The profile payload combines identity metadata, the user's recorded Elimu progress, relevant hub descriptions/skills/instructors, time spent, completion date, and issued certificate references. The PDF and JSON exports are built server-side from this authenticated payload. Hub records with no progress entry do not appear as "hubs in use"; only recorded activity is represented.

## 6. Certificates: issuer, roles and cryptographic verification

The PDF title is **Certificate of Completion — Highly Certified by RevelaCode**. It records the learner's JWT role claims, Elimu completion roles, the RevelaCode Certification Authority role, hub, completion date, recorded lesson count, skills, time spent, certificate ID, signature fingerprint, and a QR target at:

`https://revelacode.co.ke/verify/certificate/{certificate_id}`

Issuance requires a private RSA key and signs a JWT with **RS256** using issuer `RevelaCode` and audience `RevelaCode Certificate Verification`. A public endpoint validates this signature and returns public credential metadata. Tampering with the signed token or its matching stored credential data causes verification to fail. The page/API reports validity; it does not promise government accreditation, a legally recognized qualification, or third-party accreditation not actually obtained.

### Generate a stable key pair

From the repository root, run:

```powershell
python scripts/generate_certificate_keys.py
```

This creates `secrets/revelacode_certificate_private.pem` and `secrets/revelacode_certificate_public.pem`. The folder is git-ignored. Keep the private key secret and preserve the **same key pair** across deployments; never generate a new pair on each startup. Store the private PEM in the hosting provider's secret store and configure either:

- `REVELACODE_CERTIFICATE_PRIVATE_KEY` to the PEM contents (literal newlines or escaped `\\n`), or
- `REVELACODE_CERTIFICATE_PRIVATE_KEY_PATH` to a private key file provisioned into the runtime.

Configure `REVELACODE_CERTIFICATE_PUBLIC_KEY` to the matching public PEM if the public key is managed separately. If omitted, the application derives the public key from the private key. Optionally set `REVELACODE_CERTIFICATE_SIGNER_NAME` to the organization's authorized certificate-signing name. The default is `RevelaCode Certification Authority`; it is a text label, not a fabricated handwritten signature.

A missing/invalid signing key makes issuance return 503. No certificate is issued on a signing failure.

## 7. Tests

The backend tests use an in-memory Mongo-like fixture and test RSA key to cover routes and cryptographic checks without depending on a deployed database:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q tests/test_elimu_e2e.py tests/test_authgate.py tests/test_profile_download.py tests/test_certificate.py
```

The frontend regression tests use Node's built-in test runner:

```powershell
npm run test:auth
npm run build
```

Passing these tests proves the branch's local route/component contract; it does not by itself prove production login, DNS, CORS, real user data, or a live certificate download. Perform the full browser/API acceptance run against the actual deployment after configuration.
