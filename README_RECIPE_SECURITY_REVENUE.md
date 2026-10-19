# RVX Recipe Security and Revenue Lock

Status: additive implementation branch; review and deployment configuration required.

## Security boundary

- The owner RVX master key is 512 random bytes (4096 bits), created outside the repository by default at ~/.revela_recipe/master.key. It is never generated during service startup and is never committed.
- RVX blobs use AES-256-GCM with HKDF-derived keys. Tampering, a wrong key, or malformed envelopes fail closed.
- Mesh packets use a separate REVELA_RVX_MESH_SECRET where services are hosted. Packets bind the route and UTC day to the authenticated ciphertext; previous-day packets are rejected. Do not copy the offline root key into a cloud service solely to make mesh calls work.
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

Decrypt an artifact locally:

    python -m rvx.compiler --master-key ~/.revela_recipe/master.key --file factory.py.rvx --open

The RVX packager encrypts source bytes; it does not make encrypted blobs executable Go/Python bytecode. Re-materialized source must be built and tested using its original toolchain. Existing Go modules have not been migrated automatically.

## FastAPI + existing Flask gateway

The Render start command is switched to Uvicorn and starts revela_platform.fastapi_app:app. FastAPI owns the new billing, meter, and marketplace routes and mounts the original Flask app as a WSGI fallback, preserving existing Flask endpoints. Core-Zero, Core-One and Core-Two remain their existing private Go services.

Local start:

    pip install -r requirements.txt
    uvicorn revela_platform.fastapi_app:app --host 127.0.0.1 --port 5000

Set the same JWT_SECRET as the trusted RevelaCode issuer. For a real service configure REVELA_DATABASE_URL to managed PostgreSQL, REVELA_LICENSE_PRIVATE_KEY_PATH, REVELA_LICENSE_PUBLIC_KEY_PATH, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, and the relevant mesh route/secret settings. A local SQLite database is provided only for development. Missing payment or key configuration fails closed; it never issues a license from a success redirect.

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

## Deployment caveats

The API's payment integration currently uses Stripe Checkout and Stripe webhooks. PayPal and M-Pesa Global still require payment-provider adapters and credentials; no endpoint claims they are live. FX conversions, taxes, local regulatory compliance, refunds, disputes, billing portal/subscription changes, and real creator payouts need provider-specific implementation and review. Prices are USD list prices, not live exchange-rate quotes. The deterministic marketplace screen is not a full Guardian or safety certification; human review is mandatory before publication.

Source-code encryption cannot retroactively hide publicly committed Go or Python source. The pre-commit protection added to this branch prevents key material from being committed; it does not rewrite Git history or remove source from previous commits.
