# USECT-UNCOPYABLE — trust-boundary hardening

This organ adds five layers of protection to RevelaAI: owner recipe integrity, signed-license entitlements, device identity binding, authenticated RVX dialect artifacts, and founder-signed tool provenance / DNA restoration.

**Important limitation:** source code and binaries cannot be made literally uncopyable once an attacker can read them. These controls make a copied repository unable to authenticate to protected runtime services without owner-controlled trust material, provided production enforcement is enabled and private keys remain private. They do not prevent a determined owner of a modified copy from removing local checks; critical entitlements must also be enforced by hosted services and signed mesh peers.

## Runtime

The active application is FastAPI-only. The API routes are mounted in `asgi.py`; this package does not reintroduce Flask.

### Owner-controlled secrets

Keep these outside Git and inject them using the deployment secret manager:

- `REVELA_MASTER_KEY_PATH`: path to the 512-byte (4096-bit) random RVX root recipe.
- `REVELA_LICENSE_PRIVATE_KEY_PATH`: Ed25519 private key used only by the license issuer / provenance signer.
- `REVELA_LICENSE_PUBLIC_KEY_PATH`: public verification key provisioned independently to runtime verifiers.
- `REVELA_ORGAN_ADMIN_TOKEN`: at least 32 characters, required for lock status and restore administration.
- `REVELA_RECIPE_EXPECTED_SHA256`: optional out-of-band SHA-256 pin of the owner master key.
- `REVELA_HARDWARE_ID`: optional stable device identity supplied by an authenticated enrollment agent.
- `REVELA_DNA_VAULT_PATH`: destination for restored DNA snapshot data.
- `REVELA_WATERMARK_STORE`: private persistence path for signed provenance records.
- `REVELA_DIALECT_PATH`: path to the encrypted current RVX dialect artifact.

Initialize a new local root key with `python -m recipe.cli init`. Do not run that command on every deployment: doing so would create a different root and make existing encrypted artifacts unreadable. Back up the key offline before rotating it.

### Strict startup mode

Set `REVELA_UNCOPYABLE_ENFORCE=true` to make FastAPI startup fail closed unless the owner recipe, independently configured license public key, and device identity signals are available. Keep it disabled only for local development and tests. Roll it out in a staging deployment first, then configure the production secret manager before enabling it in production.

When `REVELA_MESH_REQUIRE_LICENSE=true` (or strict mode is enabled), every `rvx_call` verifies the signed runtime license before sending a packet. Provision `REVELA_MESH_LICENSE_TOKEN` as a short-lived system credential and rotate it; never put it in source code.

## Five locks

1. **Recipe:** validates the 4096-bit root key, private file permissions, and optional externally pinned digest.
2. **License:** Ed25519-signed JWT verification, expiry, plan entitlements, optional hardware fingerprint, and factory allow-list. Enterprise tokens include factory, seed, evolve, migrate, robot and DNA restore entitlements; the factory and seed endpoints reject non-enterprise claims.
3. **Hardware:** creates a hashed fingerprint from available machine identity signals. This is not TPM attestation; high-assurance deployments should add a TPM-backed enrollment agent.
4. **RVX dialect:** `python -m core_uncopyable.rvx_evolver --reason scheduled_rotation` creates a fresh encrypted dialect artifact. `verify_dialect()` rejects artifacts whose date is obsolete or whose authenticated encryption fails. Schedule this command in the trusted owner environment; it is not automatically run by Git pull.
5. **DNA and provenance:** every new Foundry build must create an Ed25519-signed watermark before it is committed. `GET /v1/verify/{tool_id}` checks the watermark. DNA restoration requires both the matching master key and a fresh founder signature over the exact vault digest, timestamp and nonce.

## API

- `GET /v1/verify/{tool_id}` — public provenance verification; missing or invalid signatures return `valid: false`.
- `GET /v1/uncopyable/status` — admin-only, redacted lock status. Requires `X-Organ-Admin-Token`.
- `POST /v1/uncopyable/restore` — admin-only encrypted DNA restore, also requiring a fresh Ed25519 founder signature over canonical JSON.

The restore payload uses `encrypted_blob_b64`, `signature_payload`, and `founder_signature_b64`. The signed payload must be exactly:
```json
{
  "action": "restore_dna",
  "vault_sha256": "<SHA-256 of the encrypted blob>",
  "issued_at": "<UTC ISO-8601 timestamp, within five minutes>",
  "nonce": "<random one-time value, at least 24 characters>"
}
```
Sign the canonical UTF-8 JSON (keys sorted, no whitespace separators) using the founder Ed25519 private key. Keep that private key offline where possible. Production should additionally use a durable replay store for restore nonces.

## Ghost response

This implementation deliberately does **not** overwrite disks or delete master keys when a device is offline or its identity changes. An irreversible self-wipe is vulnerable to false positives, clock manipulation, and denial-of-service. Use quarantine, credential revocation, service-side access denial, alerting and forensic preservation instead.

## Verification

Run:

```powershell
python -m compileall -q core_uncopyable fastapi_routes/uncopyable.py
python -m pytest -q tests/test_usect_uncopyable.py
```

The focused tests cover missing/pinned recipe checks, enterprise license claims, hardware mismatch, encrypted dialect freshness, signed watermarks and founder-authorized restore. They do not prove that a hostile administrator cannot patch local source code; that requires independent hosted enforcement and deployment controls.
