# Core-Two improvement report — v0.1.0 sample proposal

- **Status:** staged for explicit human merge. Existing Core-One and Core-Zero files remain untouched.
- **Selected mutation:** `graph-indexed`, an indexed visited-node set replacing repeated linear membership scans.
- **Fixture:** synthetic `offline_vault`, 1,800 nodes, 7,200 edges, five replay rounds.
- **Recorded graph-phase benchmark:** 2,656,694 ns/round baseline; 421,937 ns/round indexed candidate; 6.30× throughput ratio in one local run.
- **Limit:** machine-dependent graph-phase microbenchmark only; not end-to-end invention time or proof of production speedups.
- **Production evidence:** zero historical invention evidence records were present. Production timing, KES BOM cost and human merge time remain unknown/null.
- **Guardian gap:** `core-zero/guardian/rules.yaml` was absent in the inspected baseline and needs owner review.
- **RVX:** AES-GCM confidentiality/integrity proposal; no promise that software is literally uncopyable.
- **Merge gate:** never automatically installed, executed, or merged. Read `AWAIT_MERGE.md`.
