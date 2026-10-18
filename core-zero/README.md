# USECT-ZERO — Universal Self-Evolving Core Tool

**Host System Alpha — first implementation.** This is an additive, model-free engineering core designed to be copied into a host repository without replacing host files. The kernel uses Go's standard library only in this initial revision, so the Go build itself does not require downloading modules. External parsers and hardware/vendor toolchains are explicit adapters, not implicit runtime dependencies.

## Status and guarantees

This repository addition is an **MVP scaffold**, not a claim that every hardware target or engineering artifact is production-ready. It provides deterministic inventory, API-key request/approval, proposal/audit state, an RV Lang plan compiler, a local radar comparison function, an explicitly bounded sensor-kit artifact template, a bridge capability plan, and a human-gated tracked-file recovery prototype.

- The service binds to `127.0.0.1:8780` by default. Do not expose it to a network without TLS, authorization, rate limiting and deployment review.
- `POST /v1/keys/request` only creates a `pending_approval` request. An operator reviews metadata through `GET /v1/keys/requests`, then approves it with `USECT_ZERO_ADMIN_TOKEN`; the raw key is returned once and only its SHA-256 hash is persisted. Issued keys can be explicitly revoked.
- All mutations are logged to `audit_log/events.jsonl` under the runtime data root. Generated artifacts and recovery candidates are kept under `evidence/`; approvals are stored under `state/`. By default that data root is `core-zero/`; set `USECT_ZERO_DATA_DIR` to an absolute persistent-storage path for a deployed service.
- Recovery requires an explicitly recorded baseline and a clean hash match with content available from the recorded local Git revision. It proposes restoration for missing files and hash-verified replacements for modified files. Modified targets are rechecked against the hash observed at proposal time, their prior bytes are saved under `core-zero/evidence/heal/<proposal>/backup/`, and replacements require explicit approval. Self-recovery of `core-zero/` control files remains blocked. It does **not** reconstruct a function from changelog snapshots or infer which function is semantically safe.
- Candidate RV output, hardware artifacts, flash scripts and bridge plans are proposals. Candidate code is never auto-imported, compiled output is not executed, and firmware is never flashed by this service.
- Radar does not contact GitHub, arXiv or vendor sites. It compares supplied local evidence offline. Current external-trend collection therefore requires a separate operator-controlled import step.
- The assembly example is a reviewable `esp32-sensor` fixture, not an arbitrary-target CAD engine. Its STL is a simple base plate without mounting holes; board pin layouts, component compatibility, dimensions and cost need human verification.

## Requirements and run

- Go 1.23+ for building this source.
- Git CLI available locally for baseline and recovery-from-`HEAD` operations. These commands do not access the network.
- Python 3.10+ only if using the optional bridge helper.

From the parent repository root:

```sh
go -C core-zero test ./...
go -C core-zero build -o core-zero/usect-zero ./cmd/usect-zero
./core-zero/usect-zero -mode scan -root .
```

Record the current repository baseline before testing deletion recovery:

```sh
./core-zero/usect-zero -mode baseline -root .
./core-zero/usect-zero -mode heal-propose -root .
```

Start the local API:

```sh
USECT_ZERO_ADMIN_TOKEN='replace-with-a-long-local-secret' ./core-zero/usect-zero -mode serve -root . -listen 127.0.0.1:8780
```

No production key should be issued until the admin token is configured securely. For production use, the token must be supplied by a secret manager/environment and rotated; do not commit it.

## Core modules

| Module | Implemented now | Explicit limitation |
|---|---|---|
| `diagnostics/` | Runtime metadata, storage write/cleanup probes, and added/modified/missing file comparison against a saved baseline | Read-only repository analysis; reports drift but never repairs it; samples at most 50 paths per category |
| `heal/` | Baseline comparison for missing and modified files, verified candidates, stale-target checks, backup evidence, rollback-aware human-approved restore | Whole-file only; does not restore USECT-ZERO control files, infer function-level fixes, or run an autonomous watcher |
| `assemble/` | Versioned curated-template registry, generic board profiles, BOM/wiring validation, declared voltage-range checks, version-pinned generation, manifest, BOM/SVG/STL and inert flash stub | Profiles are family-level references, not certified pin maps; missing manufacturer constraints require human review; artifacts remain drafts, not validated CAD/ECAD or firmware |
| `radar/` | Offline strict-semver comparison and +30% benchmark rule | No unattended internet scan; imported evidence required |
| `forge/` | OpenAPI contract and local pending API-key workflow | Not yet an externally hosted developer portal or multi-tenant production service |
| `bridge/` | Adapter registry contract and proposal plans for ROS2, FPGA/Verilog, LabVIEW and USB/Bluetooth | No live device/vendor adapter is bundled or authorized |
| `mind/` | Bounded RV Lang parser and Go plan-code emitter, plus local IDE | Generated Go describes a plan; it is not executed and cannot rewrite the core |

## Portability notes

The Go kernel is intended for ordinary Linux/Windows/macOS hosts, including Raspberry Pi Zero-class Linux and Jetson Nano. Direct execution of a full Go service on ESP32-S3 is **not claimed**; treat that class of microcontroller as a separately built target/adapter controlled from a compatible host. The <$50 hardware target is a design objective, not a verified BOM price. The present implementation intentionally uses no tree-sitter, libgit2, OpenAPI Generator, KiCad or ROS runtime package yet; adapters should be introduced incrementally with pinned versions, license review, offline cache tests and per-platform CI.

Assembly templates are registered with a strict semantic version and must pass deterministic validation before generation. The read-only `GET /v1/assemble/templates` catalog and `GET /v1/assemble/boards` board-profile catalog use `scan:read`; `POST /v1/assemble` requires `assemble:propose` and may pin an exact `template_version`. Board profiles state their nominal family-level logic/input voltage and always expose that the exact board revision/pin map is unverified. Templates may declare manufacturer-backed sensor supply/logic ranges; incompatible declared ranges block generation, while absent ranges or missing datasheet review produce an explicit electrical-review-required status. This metadata validation is not a certification. The generated `template.json` captures the selected template, board profile, validation checks, and explicit `hardware_verified: false` provenance. Existing artifact paths are never overwritten by a generation attempt.

## Approval sequence

`Propose -> Sandbox evidence -> Wait for explicit human approval -> Execute approved bounded operation -> Audit`. If evidence or a required dependency is missing, the action must remain blocked. Approval endpoints require both admin authentication and an operation-specific confirmation string.
