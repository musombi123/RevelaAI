# RVX Recipe Security and Revenue Lock

Status: additive implementation branch; review and deployment configuration required.

## Security boundary

- The owner RVX master key is 512 random bytes (4096 bits), created outside the repository by default at ~/.revela_recipe/master.key. It is never generated during service startup and is never committed.
- RVX blobs use AES-256-GCM with HKDF-derived keys. Tampering, a wrong key, or malformed envelopes fail closed.
- Mesh packets use a separate REVELA_RVX_MESH_SECRET where services are hosted. Packets bind the route and UTC hour to authenticated ciphertext, and the UTC day labels the evolving dialect; stale-hour or previous-day packets are rejected. Do not copy the offline root key into a cloud service solely to make mesh calls work.
- The daily keyword map is cosmetic metadata and is not a replacement for authenticated encryption or a real programming-language compiler.
- Existing ZERO/ONE/TWO sources remain untouched and readable in Git. This change does not claim they became uncopyable, and it does not install a destructive hook that deletes source files.
- License tokens are Ed25519-signed, not encrypted. The private signing key is separate from the offline RVX master key, lives in a secret manager, and is never stored in Git. Offline verification uses the public key and is bounded by the signed offline_until claim (30 days maximum).

## Initialize owner materials

Run in a trusted local checkout:

    python -m recipe.cli init
    python -m core_billing.keys --output-dir ~/.revelaai/license-keys
    python -m rvx.dialect --master-key ~/.revela_recipe/master.key --output rvx/dialect/today.rvx

Keep master.key offline with a separately stored backup. Put the Ed25519 license private key in a server secret manager as REVELA_LICENSE_PRIVATE_KEY_PATH or REVELA_LICENSE_PRIVATE_KEY. Configure the matching public key for offline verification as REVELA_LICENSE_PUBLIC_KEY_PATH or REVELA_LICENSE_PUBLIC_KEY. Do not use the RVX master key as the license signing key.

Seal a non-tool file without an entitlement:

    python -m rvx.compiler --master-key ~/.revela_recipe/master.key --file notes.txt --seal-only

Compile/seal a licensed tool artifact:

    python -m rvx.compiler --master-key ~/.revela_recipe/master.key --file factory.py --license-key "$REVELA_LICENSE_KEY" --tool-id factory-demo

Compile a **reviewer-approved Foundry manifest** on the owner machine (requires master key and a currently valid signed license):

    python revela.py --recipe --compile --license-key "$REVELA_LICENSE_KEY" --factory-build-id fab_<24-hex-id>

Decrypt an artifact locally:

    python -m rvx.compiler --master-key ~/.revela_recipe/master.key --file factory.py.rvx --open

Offline child bundles returned by `POST /v1/seed/{build_id}` include a signed license token and integrity hash. Save the returned `child_bundle` JSON as `<REVELA_SEED_ROOT>/<seed_id>/child.json` in the customer's offline installation, then verify there with:

    python -m core_seed.cli --seed-id seed_<24-hex-id>

The RVX packager encrypts source bytes; it does not make encrypted blobs executable Go/Python bytecode. Re-materialized source must be built and tested using its original toolchain. Existing Go modules have not been migrated automatically.

## FastAPI + existing Flask gateway

The Render start command is switched to Uvicorn and starts revela_platform.fastapi_app:app. FastAPI owns the new billing, meter, marketplace, Foundry, Seed, and Auditor routes and mounts the original Flask app as a WSGI fallback, preserving existing Flask endpoints. Core-Zero, Core-One and Core-Two remain their existing private Go services.

Local start:

    pip install -r requirements.txt
    uvicorn revela_platform.fastapi_app:app --host 127.0.0.1 --port 5000

Set the same JWT_SECRET as the trusted RevelaCode issuer. For a real service configure REVELA_DATABASE_URL to managed PostgreSQL, REVELA_LICENSE_PRIVATE_KEY_PATH, REVELA_LICENSE_PUBLIC_KEY_PATH, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, and the relevant mesh route/secret settings. A local SQLite database is provided only for development. Hosted factory and billing state requires `REVELA_DATABASE_URL` pointing to a managed database; the root Render service has no extra persistent disk configured. Missing payment or key configuration fails closed; it never issues a license from a success redirect.

## Revenue model and endpoints

- Local: USD $10/month, 10 tools, one licensed country.
- Pro Worldwide: USD $500/month, 100 tools.
- Enterprise: USD $10,000/month, unlimited tool quota.
- POST /v1/billing/buy creates a Stripe subscription checkout. A signed Stripe webhook must confirm payment before GET /v1/billing/license/{intent_id} issues a signed license.
- POST or GET /v1/billing/verify checks the signed license and current server-side activation. Prefer POST because query strings can be logged.
- POST /v1/billing/webhooks/stripe validates the Stripe-Signature header and idempotently records processed events.
- Published tool calls at /v1/{tool_id} require a valid X-Revela-License and authenticated user; tool ownership or a paid marketplace purchase is checked.
- GET /v1/meter/usage returns usage counts by country. No bodies, secrets or client IPs are stored. Savings default to zero and are shown only when a reviewed savings estimate is configured.
- POST /v1/marketplace/publish places safe-looking listings in pending_review; a configured reviewer must approve a tool before it is searchable or callable.
- POST /v1/marketplace/buy creates a one-time Stripe checkout. After signed payment confirmation, GET /v1/marketplace/purchases/{purchase_id} delivers the reviewed listing and available country/language assets.
- Creator earnings use a 70/30 split, recorded as pending payout. Automatic bank/M-Pesa/PayPal payout is not implemented by this stage.
- `POST /v1/foundry/build` writes a declarative factory proposal; `POST /v1/foundry/builds/{build_id}/review` requires a configured reviewer ID before approval. No generated Python is executed, and there is no hardware actuation in this stage.
- `POST /v1/seed/{build_id}` only seeds an approved factory and delivers a verifiable child bundle. Offline mode is bounded by the signed 30-day lease; OS clock rollback cannot be prevented on an ordinary workstation without trusted hardware.
- `GET /v1/auditor/verify` validates local hash-chain continuity. Configure separately controlled immutable storage or export signed checkpoints for stronger audit evidence.

## Deployment caveats

The API's payment integration currently uses Stripe Checkout and Stripe webhooks. PayPal and M-Pesa Global still require payment-provider adapters and credentials; no endpoint claims they are live. FX conversions, taxes, local regulatory compliance, refunds, disputes, billing portal/subscription changes, and real creator payouts need provider-specific implementation and review. Prices are USD list prices, not live exchange-rate quotes. The deterministic marketplace screen is not a full Guardian or safety certification; human review is mandatory before publication.

Source-code encryption cannot retroactively hide publicly committed Go or Python source. The pre-commit protection added to this branch prevents key material from being committed; it does not rewrite Git history or remove source from previous commits.


## Signed factory review and RVXP1 invocation

Generate a separate reviewer signing pair locally:

    python -m core_foundry.keys --output-dir ~/.revelaai/review-keys

Keep `review_private.pem` only in the API service secret manager as `REVELA_REVIEW_PRIVATE_KEY_PATH`. Distribute `review_public.pem` to owner machines as `REVELA_REVIEW_PUBLIC_KEY_PATH`. A factory approval is not trusted for offline compilation or seeding unless this Ed25519 attestation verifies; SHA-256 alone is only an integrity checksum.

Registered tool calls are routed to an explicitly configured `tool.<tool_id>` adapter in `REVELA_RVX_ROUTES`. That adapter must speak RVXP1. Python peers can mount `mesh.receiver.create_rvx_receiver_router` with an explicit handler allowlist. Core-Zero, Core-One and Core-Two are still Go services and cannot receive these packets until Go-side RVXP1 support has been separately implemented and tested.

RVXP1 encrypts packet contents with AES-GCM, binds route + UTC day + hourly key window + unique message ID, and rejects stale or duplicate packets within the receiver process. Multi-worker/distributed receiver deployments require a shared replay store or equivalent coordination. The outer envelope exposes protocol metadata but not payload content.

Hosted Foundry review requires a configured review private key. If it is absent, the API refuses the approval instead of silently marking the factory approved. Local compiler and offline child verifier require the corresponding review public key.
