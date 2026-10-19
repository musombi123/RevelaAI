# AWAIT_MERGE — RVX Recipe Security + Revenue Lock

Status: awaiting owner review. Do not merge until the checklist below is completed.

## Added in this proposal

- Python RVX AES-GCM artifact packager, owner key initializer and encrypted daily dialect artifact.
- Daily AES-GCM mesh packet format; route and UTC day are authenticated, stale packets fail closed, and no plaintext transport fallback exists.
- Separate Ed25519-signed plan licenses with a 30-day maximum offline verification window.
- SQLAlchemy records for licenses, checkout intents, meter events, marketplace listings, creator earnings, webhook idempotency and audit entries.
- FastAPI billing, Stripe webhook, meter, and human-reviewed marketplace endpoints; the existing Flask gateway is mounted as fallback.
- Render Uvicorn start command and key/data environment variable declarations.
- Existing Go ZERO/ONE/TWO sources are unchanged.

## Required before merge/deployment

1. Create the owner master key locally and keep offline; verify there is no key file staged in Git.
2. Generate a separate Ed25519 signing pair; store the private key only in a secret manager and configure the public key for verification.
3. Set JWT_SECRET, REVELA_DATABASE_URL (managed PostgreSQL recommended), STRIPE_SECRET_KEY, and STRIPE_WEBHOOK_SECRET.
4. Configure Stripe webhook delivery for checkout completion, invoice paid/failed, and subscription deletion. Test signatures with Stripe test mode first.
5. Configure REVELA_RVX_MESH_SECRET independently on peers plus REVELA_RVX_ROUTES. Existing Go cores do not yet speak RVXP1; do not route production traffic to them until their receivers are implemented and tested.
6. Run Python unit tests, existing Go tests, OpenAPI validation and deployed integration tests.
7. Review plan prices, taxes, billing cancellation/refunds, marketplace Guardian policy, seller identity/tax duties, and payout provider requirements.
8. Inspect all changes and explicitly approve the pull request.

## Acceptance status

- Owner key generation and authenticated RVX blob/packet primitives: implemented in code; tests required.
- License checks: implemented as code; requires configured Ed25519 keys and webhook settlement.
- Stripe checkout and signature-verified webhook path: implemented; must be exercised in Stripe test mode.
- Country meter and 70/30 earnings ledger: implemented in code; payout remains pending.
- Marketplace publish remains pending human review; unsafe listings are rejected by a limited deterministic screen.
- PayPal, M-Pesa Global payouts, automatic FX conversion, and end-to-end tool invocation in Go cores: not implemented.
- Full Go source encryption/migration: not implemented; existing source remains readable in Git.
- Factory, Seed, Auditor: not implemented yet; they should be built only after this security/revenue layer passes review.

No production-readiness, legal-compliance, or uncopyability guarantee is made by this proposal.
