# USECT-TWO acceptance report

**Scope:** additive files under `core-two/` only. The branch does not alter any existing ZERO/ONE file.

## Repository integration verified from the inspected baseline

- Core-Zero exists at `core-zero/` with module path `usect-zero.local/core-zero`; Mind imports its `mind.Compile` and `radar.Compare` packages directly.
- Core-One exists at `core-one/` with module path `revela-genesis.local/core-one`; Mind imports `genesis.Engine` / `genesis.Guardian` and reads `ListInventions()` and library/invention evidence without calling `NewEngine()` (which would create additional Core-One state).
- The recursive GitHub tree response contained 318 tracked paths. In the baseline, `core-one/inventions/` had only its README, no invention `evidence.json` was recorded, and there were no source `.go` / `.rvx` files in `core-one/libraries/created/` beyond its README.
- OpenAPI source contracts exist at `core-zero/openapi.yaml` and `core-one/openapi.yaml`; no root `openapi.yaml` existed. Core-Two therefore adds a combined gateway contract at `core-two/openapi.yaml` rather than editing either source contract.
- `core-zero/guardian/rules.yaml` is absent in the inspected baseline. The integration endpoint marks this as a policy gap. A present but invalid ZERO policy blocks evolution; an absent policy falls back only to the restrictive Core-Two rules plus the existing Core-One Guardian and ZERO library probes. Resolve this before treating the three-core safety policy as fully integrated.

## Test results (local compatibility harness)

`go test -v ./...` passed the Mind tests, ten sample mutation package tests, RVX package compilation, and provider mesh test. `go vet ./...` passed. Tests covered:

1. Core-Zero/Core-One module paths and import wiring compile against API-compatible sibling-module stubs; upstream public signatures were independently inspected from the repository source.
2. Ten candidate templates parse and type-check; graph-indexed `offline_vault` replay preserves traversal output and benchmarks a median improvement in the synthetic graph phase.
3. A proposal batch of ten mutation folders and `AWAIT_MERGE.md` are staged only below Core-Two.
4. A harmful weapon-search goal is blocked and hash-audited before candidate mutation/evolution directories are created.
5. An invalid existing Core-Zero Guardian rules file fails closed.
6. Whole-tree inventory picks up hub paths, Core-Zero/Core-One boundaries, OpenAPI paths, changelog names and audit-log names.
7. Provider notification uses `REVELACODE_PROVIDER_URL` and `REVELACODE_PROVIDER_KEY`, places the key only in a bearer header, and excludes it from the body; external providers require HTTPS.
8. Unknown historical timing, BOM cost, merge time, safety score and merge score stay `null`/unobserved rather than becoming invented zeroes.

**Important verification limit:** this sandbox did not contain a full checkout of the live repository. The local Go tests used small API-compatible sibling-module stubs after the public Core-Zero/Core-One signatures were inspected from the GitHub tree. Tests against the exact neighbouring module bytes and a full three-daemon startup still need to run in the real repository/CI. Existing workflows are path-filtered to Core-Zero and Core-One and do not run for Core-Two-only changes.

## Sample improvement evidence

The checked-in `offline_vault` replay is a synthetic 1,800-node / 7,200-edge dependency graph. The recorded run measured the graph-traversal phase only; it is not end-to-end invention latency. Values vary by host/load. No vendor quote was fetched; cost units in the BOM fixture are illustrative, not KES. The source baseline contained zero historical Core-One inventions, so production averages remain `null`.

## Security and lifecycle boundaries

- Candidates are curated static Go source, AST-parsed, import-allowlisted, type-checked, and checked against Guardians before staging; candidate source is not run by the evaluator.
- Runtime mutation/evolution artifacts are written only beneath Core-Two. The human owner must review and merge; there is no auto-merge/auto-install.
- AES-GCM protection is a proposal for artifact confidentiality/tamper detection using a runtime external key. It does not make software literally uncopyable and does not change the existing Core-One RVX compiler.
- The Mind API refuses mutation if `MIND_ADMIN_TOKEN` is absent. Production deployment still needs TLS, rate limits, secure secret management, legal/privacy/KEBS assessment and dedicated ZERO Guardian rules.
