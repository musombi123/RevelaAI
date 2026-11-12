# Workspace Auditor and Repair Workbench

The Python companion adds repository-level diagnostics to the native Go Field Engine. It is local-first, deterministic, and model-independent.

## Start from USB

Windows:
- Run Run-Workspace-Audit.cmd from the USB root, or Run-Workspace-Audit.ps1 -Root E:\source.
- The released Windows package uses the embedded Python runtime. A local Python 3.10+ runtime is used only when the embedded runtime is absent.

Linux:
- Run ./run-workspace-audit.sh from the USB root.
- Python 3.10+ is required unless a verified runtime is added at runtimes/python-linux-x64/bin/python3.

USB mass-storage devices do not reliably auto-run applications on insertion. Launch the script explicitly after inserting the drive; this is intentional and avoids unsafe autorun behavior.

## Commands

List candidate mounted volumes without reading their contents:

    python -m revela_fieldkit drives

Run the bounded local audit on an explicitly authorized root:

    python -m revela_fieldkit audit --root /path/to/repository --authorized --out ./workspace-audit.json

Inspect an entire authorized USB or workspace root. Repositories are discovered recursively; common caches, dependency folders, VCS internals and symlinks are excluded:

    python -m revela_fieldkit audit --root /media/USB --authorized --out ./audit.json

Optionally export individual findings using the existing Field Engine / Meta Engineer hand-off schema:

    python -m revela_fieldkit audit --root ./repository --authorized --findings-dir ./data/field-findings

The exported records can be submitted one at a time through the existing native command:
revela-field sync --finding FILE --url https://revelaai.onrender.com
Use an existing administrator bearer session in the current shell. Sync is optional, authenticated and remote; the auditor never uploads code, source files, environment values or the complete report. The existing Meta Engineer integration stores submitted findings as awaiting approval. This does not activate a repair or silently dispatch work to ZERO, Genesis or Infinite Mind.

If the local operator explicitly requests current npm advisory data, the following uses the network:

    python -m revela_fieldkit audit --root ./repository --authorized --npm-audit

Network access is disabled by default. No package installation, dependency update, build script or project test command is run by an audit.

## Diagnostic coverage

- Recursive repository discovery for Git, Node, Python, Go, Rust, Java and Render Blueprint markers.
- Python AST parsing, syntax-error reporting and duplicate literal FastAPI/Flask-style route observations.
- Node parser-only checks for .js, .mjs and .cjs when Node is installed; JSX and TypeScript need their project compiler.
- Relative JavaScript module references and static HTML href/src targets.
- npm manifest/lockfile presence and direct dependency lock drift; Python manifest inventory and Go direct require count.
- Render Blueprint fromService.name references compared with declared service names.
- Package/root license metadata observations, Git commit/branch and tracked-worktree-change summary.
- Optional production-only npm audit advisory counts when explicitly enabled.

The audit is bounded and static. It does not prove runtime health, license compliance, vulnerability exploitability, deployment readiness or absence of defects. It does not parse every framework's route graph or every language's AST.

## Controlled repairs

The repair engine accepts a reviewable JSON plan with schema revelaai.repair-plan.v1. Each change contains:

- path: repository-relative path.
- expected_sha256: exact SHA-256 of the existing file; use null only when creating a new file.
- new_content_base64: Base64-encoded UTF-8 replacement content (1 byte to 2 MiB).
- reason: short human-readable rationale.

Example invocation:

    python -m revela_fieldkit repair apply --root ./repository --plan ./approved-plan.json --authorized --approve

Both flags are mandatory. The engine rejects path traversal, symlinks, credential files, binary files, stale hashes, duplicate targets, unsupported extensions and oversized plans. It does not execute shell commands, installers, migrations or candidate code. Original bytes are stored outside the repository before an atomic replacement. The transaction JSON identifies the backup and expected post-repair hashes.

Rollback:

    python -m revela_fieldkit repair rollback --transaction /path/to/backups/TRANSACTION/transaction.json --authorized --approve

Rollback is blocked if a target changed after the repair. It verifies the stored backup hash before restoration. Keep the external backup directory until the repair has been validated and the transaction is no longer needed.

## Core and safety boundary

- ZERO remains the model-free policy and evidence layer.
- Genesis and Infinite Mind remain separate reasoning/proposal services; this auditor does not invoke them or grant them host access.
- Findings can use the existing signed/validated Field Engine hand-off path into the Meta Engineer awaiting-approval queue. Operator authentication and the existing approval system remain authoritative.
- No MongoDB connection is opened by this portable module. It does not create a second database or persist reports in the cloud.
- No feature flag is enabled automatically. A candidate change must be represented in a reviewed plan and pass post-change build/tests before it is considered complete.
- No host settings, services, startup entries, registry keys, accounts, network routes, firewall rules or security products are changed.

For production use, preserve evidence, inspect the generated JSON report, review every suggested change and run the repository's real CI/build/test suite after a repair.
