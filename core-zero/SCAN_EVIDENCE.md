# USECT-ZERO — Pre-implementation repository evidence

**Snapshot time:** 2026-10-18 (Africa/Nairobi; UTC date aligned)
**Repository:** https://github.com/musombi123/RevelaAI
**Inspected ref:** `main`
**Observed latest commit SHA via GitHub commit search:** `db9723467a2d20ab36de4f5d8e0d2a78fbaa7ae8`
**Method:** GitHub repository metadata, root contents listing, directory contents listing for the first-party source/test/docs/config directories, and targeted searches for `core-zero`, `changelog`, self-heal/AST restoration, OpenAPI/API-key request, `semver_compare`, and `benchmark_runner`. This is source-host evidence, not a local checkout, clean-working-tree proof, or runtime/hardware test.

## Repository metadata observed

- Default branch: `main`; repository visibility: public; primary detected language: Python.
- GitHub repository size metadata: 42,417 KiB.
- Root contains existing application, AI adapters, service/routes, test suite, `meta_engineer/`, `revelai/core/`, `revelai/sci_core/`, and CI workflows.
- No root entry named `core-zero/`, `changelog/`, `openapi.yaml`, or `/v1/keys/request` implementation appeared in the inspected root contents.
- Important qualification: `routes/meta_engineer_routes.py` computes and writes proposal evidence under `changelog/meta_engineer/` when proposals pass. Therefore, changelog functionality exists at runtime even though no root `changelog/` directory is present in the checked-in root listing.

## Existing functionality detected — preserve, do not duplicate

1. `meta_engineer/introspector.py` — read-only Python architecture scanner; maps structure, imports and schemas; identifies protected paths and candidate route slots.
2. `meta_engineer/generator.py` — deterministic proposal generator; validates input and emits non-integrated candidate artifacts.
3. `meta_engineer/sandbox_tester.py` — bounded static-contract testing; candidate source is treated as text and not imported/executed.
4. `meta_engineer/integrator.py` — path protection, proposal persistence, and changelog/audit records in MongoDB when configured.
5. `meta_engineer/release_gate.py` and `meta_engineer/staging_adapter.py` — release policy simulation/staging adapter scaffolding; release gate explicitly says simulation-only and has no deploy side effects.
6. `routes/meta_engineer_routes.py` — existing Flask blueprint with admin-gated `/health`, `/scan`, `/propose`, `/approve/<idea_id>`, audit/status and pruning routes.
7. `revelai/core/agi_manifest.py` and `revelai/core/brain_os.py` — capability/self-description manifest and Brain OS capability/guardrail logic.
8. `revelai/sci_core/connector_contract.py`, `defensive_shield.py`, `disaster_manager.py`, `hardware_lab.py`, `monitor_runner.py`, `research_engine.py`, and `storage.py` — existing connector policy, defensive checks, simulations, hardware prototype support, monitoring, research and storage.
9. `docs/brain-os-engineering-charter.md`, `docs/BRAIN_OS_RECOVERY_RUNBOOK.md`, `docs/HARDWARE_LAB_CHECKLIST.md`, and related Brain OS docs — state that recovery is simulation-only, live hardware is not authorized by default, and broad autonomous production mutation is not yet proven.
10. Existing tests include `tests/test_meta_engineer.py`, `tests/test_brain_os.py`, `tests/test_agi_manifest.py`, and Sci-Core tests. Existing workflows include `meta-engineer-tests.yml`, `brain-os-candidate-validation.yml`, `brain-os-defensive-monitor.yml`, and smart-memory checks.
11. Existing first-party folders observed at root include `.github/`, `ai/`, `ai_client/`, `config/`, `core/`, `db/`, `docs/`, `features/`, `meta_engineer/`, `models/`, `revelai/`, `routes/`, `schemas/`, `services/`, `tests/`, `utils/`, `vision/`, `voice/`, and `workflows/`. The repository also includes `vosk-model-small-en-us-0.15/` assets.

## Targeted searches

GitHub code searches for `core-zero`, `changelog`, self-healing/AST restoration/audit, `openapi.yaml`/API key request, and `semver_compare`/`benchmark_runner` returned no matching search results. This supports “no match found in these searches,” not proof that no analogous behavior exists anywhere.

## Initial gap assessment

- No dedicated universal, standalone `/core-zero/` kernel or first API contract surfaced in the inspected tree.
- No `/v1/keys/request` endpoint/spec surfaced. Existing application auth and Meta-Engineer admin-gating must remain untouched; new key handling should be isolated and default to pending human approval.
- Existing healing/recovery code is diagnostic or simulation-first, not autonomous code restoration. A safe delta should add detection + candidate recovery into an isolated sandbox, evidence output, and an approval state; it must not silently modify live files.
- Existing hardware-lab artifacts are planning/checklist/connector layers. They do not prove generic automatic generation of correct wiring diagrams/STLs/firmware or direct Go execution on an ESP32-S3.
- Daily external technology discovery conflicts with strict offline operation if treated as a live scanner. Keep offline comparison deterministic and provide an optional, explicitly configured evidence-import workflow for externally collected reports; do not add a hidden network dependency.

## Files/directories to leave untouched during the delta

All inspected existing paths listed above, including `README.md`, `requirements.txt`, `app.py`, `core/`, `meta_engineer/`, `routes/`, `revelai/`, `services/`, `tests/`, workflows, and existing docs. Only new files under `/core-zero/` should be created for the prototype.

## Evidence limits

- This is a GitHub-hosted source inventory and selected-file review. No repository checkout was mounted in a local execution sandbox, so no local filesystem scan, `git status`, Go compilation, project test run, intentionally deleted-file exercise, offline network trace, or hardware target test is claimed.
- Large speech/model assets are inventoried by visible directory names, not recursively expanded as individual binary entries.
- Raspberry Pi Zero / Jetson Nano performance, ESP32-S3 runtime feasibility, BOM cost below US$50, KiCad export correctness, ROS2/LabVIEW/FPGA compatibility, and production key issuance need separate device/toolchain tests.
