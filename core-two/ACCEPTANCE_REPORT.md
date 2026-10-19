# USECT-TWO acceptance report
**Scope:** Core-Two implementation files are contained in `core-two/`. This branch also wires the cores into the existing RevelaAI host through `ai/core_mesh.py`, `ai/orchestrator.py`, `services/ai_service.py`, `app.py`, and `README.md`. Existing Core-Zero/Core-One engine source files are unchanged.
## Repository integration verified from the inspected baseline
- Core-Zero exists at `core-zero/` with module path `usect-zero.local/core-zero`; Mind imports its `mind.Compile` and `radar.Compare` packages directly.
- Core-One exists at `core-one/` with module path `revela-genesis.local/core-one`; Mind imports `genesis.Engine` / `genesis.Guardian` and reads `ListInventions()` and library/invention evidence without calling `NewEngine()` (which would create additional Core-One state).
- The recursive GitHub tree response contained 318 tracked paths. In the baseline, `core-one/inventions/` had only its README, no invention `evidence.json` was recorded, and there were no source `.go` / `.rvx` files in `core-one/libraries/created/` beyond its README.
- OpenAPI source contracts exist at `core-zero/openapi.yaml` and `core-one/openapi.yaml`; no root `openapi.yaml` existed. Core-Two therefore adds a combined gateway contract at `core-two/openapi.yaml` rather than editing either source contract.
- `core-zero/guardian/rules.yaml` is absent in the inspected baseline. The integration endpoint marks this as a policy gap. A present but invalid ZERO policy blocks evolution; an absent policy falls back only to the restrictive Core-Two rules plus the existing Core-One Guardian and ZERO library probes. Resolve this before treating the three-core safety policy as fully integrated.
## Test results and verification boundary
At backend commit `678453bb1f479bc617a80f9c76df0c46f8432a04`, the dedicated GitHub Actions workflow passed against the complete PR checkout and the repository's actual relative Core-One/Core-Zero module replacements: `go test -race ./...`, `go vet ./...`, `go build ./cmd/...`, Python compilation of `app.py`, `ai/core_mesh.py`, `ai/orchestrator.py`, and `services/ai_service.py`, plus the five Core Mesh routing/safety tests. The run is [USECT-TWO Core Mesh Integration Checks](https://github.com/musombi123/RevelaAI/actions/runs/39179028880).
This confirms compile, race-test, vet, and command-build coverage for this repository revision. Live end-to-end requests to three deployed daemons, production credentials, real Guardian policy configuration, and actual staging proposal workflow have not been tested by that CI run.
The test suite in the branch covers:
1. Direct module imports for Core-One Genesis and Core-Zero RV Lang/Radar.
2. Ten static candidate templates with parse/type checks and bounded offline `go test` processes.
3. The synthetic offline_vault graph replay with output equivalence and a phase-only benchmark.
4. Harmful-objective blocking before mutation/evolution directories are created.
5. Fail-closed behavior for an invalid existing Core-Zero Guardian policy.
6. Repository inventory across Core-Zero/Core-One, hubs, OpenAPI, changelogs and audit logs.
7. Incremental Mirror cursors, log-summary privacy, and read-only health probes.
8. HTTP telemetry that omits query strings, headers, request bodies, and client IPs.
9. Authenticated human feedback bound to a staged version/tool/mutation, with ranking changes that cannot bypass Guardian/tests or merge code.
10. Shared provider environment names and protection against including the provider key in the request body.
11. Unknown historical timing, BOM cost, merge time, safety score and merge score staying null/unobserved instead of becoming invented zeroes.
The baseline tracked Git tree did not contain `core-zero/guardian/rules.yaml`, so this remains an integration gap. The candidate-validation workflow did run on this pull request and failed its whitespace check on a trailing-space line in this report; that line was removed in commit `5bac3e472db1c0f9910b9ba83035b9f8f4c6ddaf`. A passing rerun for that cleanup has not yet been observed. The draft PR's repository CI now passes for Go race tests, vet, command builds, Python integration syntax and focused route/safety tests. Complete live three-daemon staging health checks and policy review are still required before production.
## Sample improvement evidence
The checked-in `offline_vault` replay is a synthetic 1,800-node / 7,200-edge dependency graph. The recorded run measured the graph-traversal phase only; it is not end-to-end invention latency. Values vary by host/load. No vendor quote was fetched; cost units in the BOM fixture are illustrative, not KES. The source baseline contained zero historical Core-One inventions, so production averages remain `null`.
## Security and lifecycle boundaries
- Candidates are curated static Go source, AST-parsed, import-allowlisted, type-checked, and Guardian-checked before staging. Their `Validate()` tests run in bounded offline Go subprocesses using temporary modules; repository-sourced invention code is not executed. This is process isolation, not an OS-level sandbox.
- Runtime mutation/evolution artifacts are written only beneath Core-Two. The human owner must review and merge; there is no auto-merge/auto-install.
- AES-GCM protection is a proposal for artifact confidentiality/tamper detection using a runtime external key. It does not make software literally uncopyable and does not change the existing Core-One RVX compiler.
- The Mind API refuses mutation if `MIND_ADMIN_TOKEN` is absent. Production deployment still needs TLS, rate limits, secure secret management, legal/privacy/KEBS assessment and dedicated ZERO Guardian rules.
