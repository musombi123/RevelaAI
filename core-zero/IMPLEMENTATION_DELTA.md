# USECT-ZERO initial additive delta

## Host files intentionally not modified

No existing path was updated, moved or deleted. The implementation is isolated under the new `/core-zero/` directory. In particular, leave these existing systems intact:

- Root and runtime: `README.md`, `app.py`, `requirements.txt`, `render.yaml`, `runtime.txt`, `LICENSE`, `.gitignore`, `.dockerignore`.
- Existing shared foundations: `core/`, `config/`, `db/`, `models/`, `utils/`, `schemas/`.
- Existing AI/host-specific modules: `ai/`, `ai_client/`, `features/`, `services/`, `routes/`, `revelai/`, `vision/`, `voice/`, `vosk-model-small-en-us-0.15/`.
- Existing engineering work: `meta_engineer/`, `workflows/`, `.github/workflows/`, `docs/`, `tests/` and their files.

`routes/meta_engineer_routes.py` already emits proposal documentation into a runtime `changelog/meta_engineer/` path; that existing behavior is preserved. USECT-ZERO does not write into that path.

## New files introduced

- `core-zero/README.md` — setup, constraints, safety invariants and current limitations.
- `core-zero/SCAN_EVIDENCE.md` — pre-implementation source-host inventory evidence.
- `core-zero/IMPLEMENTATION_DELTA.md` — protected-path and new-file manifest.
- `core-zero/openapi.yaml` — first API contract, including `POST /v1/keys/request` and approval-gated issuance.
- `core-zero/go.mod` — standard-library-only Go module declaration.
- `core-zero/.gitignore` — excludes generated state, evidence and audit data.
- `core-zero/cmd/usect-zero/main.go` — CLI and local HTTP service entrypoint; serving performs a startup pre-check scan.
- `core-zero/internal/kernel/kernel.go` — repository inventory, SHA-256 evidence, baseline storage and append-only audit events.
- `core-zero/internal/kernel/kernel_test.go` — inventory/exclusion test.
- `core-zero/internal/api/server.go` — scoped API routes and explicit human approval endpoints.
- `core-zero/internal/api/server_test.go` — key request → human approval → scoped access regression test.
- `core-zero/heal/heal.go`, `storage.go`, `git.go`, `heal_test.go` — missing-file proposal, local-Git candidate staging, hash verification and explicit restore approval.
- `core-zero/assemble/assemble.go`, `assemble_test.go` — curated offline sensor-kit BOM/wiring/SVG/STL/flash-stub artifacts.
- `core-zero/radar/radar.go`, `radar_test.go` — offline semantic-version and benchmark comparison with a greater-than-30% review threshold.
- `core-zero/forge/keys.go`, `keys_test.go` — pending key requests, admin review queue, restricted scopes, one-time issue, hash-only persistence and revocation.
- `core-zero/bridge/bridge.go` — plans for ROS2, FPGA/Verilog, LabVIEW and device adapters; no real device drivers.
- `core-zero/mind/rvlang.go`, `rvlang_test.go` — 20-keyword inventory and safe declarative plan-to-Go-source compiler.
- `core-zero/ide/index.html` — self-contained local RV Lang plan editor.
- `core-zero/python_bridge.py` — optional, bounded subprocess bridge for an existing Python host.

The CLI creates `core-zero/state/`, `core-zero/evidence/` and `core-zero/audit_log/` at runtime. Those generated files are excluded from Git by `.gitignore`; they are not bundled as pre-populated state.

## Evidence and acceptance status

Locally executed checks for this delta: `go test ./...`, `go vet ./...`, and a Go CLI build. The deletion-recovery test creates a temporary Git repository, deletes a tracked file, verifies that the proposal leaves it missing, rejects an incorrect confirmation, and restores it only after the explicit approval phrase.

Not yet proven: direct ESP32-S3 execution, Raspberry Pi Zero or Jetson performance, `<$50` physical BOM, live GitHub/arXiv daily collection, arbitrary-target CAD/ECAD, function-level AST restoration from changelog, real ROS2/FPGA/LabVIEW/USB/Bluetooth adapters, public internet deployment security/rate limiting, and a self-rewriting RV runtime. These require follow-up adapters and environment-specific validation and must not be described as complete.
