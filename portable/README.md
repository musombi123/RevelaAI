# RevelaAI USB Field Engine

**Version:** 0.3.0 foundation
**Purpose:** Portable, model-free system inspection, evidence triage and controlled defensive validation.

The primary field runtime is a precompiled Go application. The native commands do not require Ollama, a cloud model, a Go compiler or third-party Go modules on the target computer. The existing Python Field Kit remains as a companion for case work, binary inspection, custody records, secret-pattern review and offline notes.

## Native Go Field Engine

The release workflow builds executables for Windows x64 and Linux x64 under `bin/<os>-<arch>/`. The Windows and Linux launchers prefer the native engine. Use:

```text
revela-field doctor
revela-field system
revela-field network
revela-field audit --root ./authorised-directory --authorized
revela-field simulate --scenario auth-failure-burst
revela-field simulate --scenario startup-entry
revela-field simulate --scenario vpn-observation
revela-field core-status
revela-field core-start --authorized
```

`doctor` reports whether the separately built Core-ZERO, Core-ONE and Core-TWO executables are present. `core-status` probes only their local health endpoints on ports 8780, 8781 and 8782. Binary presence and HTTP reachability are not proof that Guardian enforcement or cross-core integration is correct.

### Start the three USECT cores from the USB

The Windows/Linux USB release contains:
- `bin/<platform>/` — precompiled Field Engine and ZERO/ONE/TWO service executables.
- `runtime-source/` — the matching core modules, worldwide library and Guardian policy files.
- `data/logs/` and `data/runtime/` — local service logs and state, created on demand.

Run `revela-field core-start --authorized` or choose menu option 6 and type `START`. The supervisor verifies the core source and Guardian policy files, generates temporary service tokens, starts each core on loopback only, checks the three health endpoints, and stops the child services when the operator exits. Mind auto-evolution is disabled. Provider/model credentials and the host's general environment are not passed into the core processes. Runtime logs and data remain on the USB.

This is a local stack startup, not proof that every internal package is healthy. The CI suite must pass the Go tests and the three-core startup smoke test for the specific release commit.

### Safe adversary emulation

The simulator uses synthetic fixtures to validate defensive detection logic. It currently includes authentication-failure bursts, a fictional startup-entry change and VPN tunnel visibility. The scenarios do not create real accounts, startup entries, scheduled tasks, services, registry keys, processes, payloads or network traffic. Each report is explicitly marked `simulated: true`.

Export a synthetic finding for later review:

```text
revela-field simulate --scenario auth-failure-burst --finding-out ./data/auth-failure-finding.json
```

Guardian is fail-closed. It permits explicitly authorised local inventory and lab-only synthetic scenarios. It blocks remote exploitation, VPN bypass, credential dumping, stealth evasion, disabling defences, deleting evidence, arbitrary payload execution and external-network scanning.

### System and network inspection

The native engine reports a minimal host snapshot, local network-interface metadata, possible tunnel-interface name hints and the presence (not values) of proxy environment variables. VPN indicators are observations, not evidence of maliciousness. It does not attempt to bypass VPN protections or identify people behind network endpoints.

The file inventory command hashes bounded regular files, skips symlinks and does not execute or modify source files. It is a metadata/evidence inventory, not a malware verdict or forensic disk image.

## Meta Engineer hand-off

Field Engine findings use `contracts/finding.schema.json`. The Meta Engineer adapter validates the finding contract and the authenticated endpoint `POST /api/meta-engineer/fieldkit/findings` stores an `awaiting_approval` item in the existing Meta Engineer `revelai.ideas` collection. Persistence and audit require the existing configured MongoDB connection. Duplicate finding IDs are idempotently rejected/recognised.

To submit a finding from a connected workstation, use an existing authorised RevelaCode administrator bearer session. Do not save it to the USB, a case file or a log:

PowerShell:

```powershell
$env:REVELA_ADMIN_BEARER = "<existing administrator bearer session>"
.\bin\windows-amd64\revela-field.exe sync --finding .\data\auth-failure-finding.json --url https://revelaai.onrender.com
Remove-Item Env:REVELA_ADMIN_BEARER
```

For Linux, export the same environment variable for the current shell and run `bin/linux-amd64/revela-field sync --finding ./data/auth-failure-finding.json --url https://revelaai.onrender.com`. Remote sync requires HTTPS; plain HTTP is accepted only for loopback testing. Redirects are rejected. The tool submits the structured finding only, not the inspected files.

A successful hand-off means the finding entered the review queue. It does not mean the vulnerability is confirmed, a repair has been approved, or a host was changed. Meta Engineer currently records schema validation as a hand-off gate; repair-specific tests must still be created before any future repair is approved.

## Python evidence companion

The companion uses only the Python standard library. It supports:

| Tool | Command | Function |
|---|---|---|
| Case workspace | python -m revela_fieldkit case create ... | Create case metadata, evidence/report folders and custody log. |
| Evidence inventory | python -m revela_fieldkit inventory --case CASE --source DIR | Hash regular files and save an integrity manifest. |
| Integrity verification | python -m revela_fieldkit verify --case CASE | Re-hash source files and compare them to the saved manifest. |
| Custody log | python -m revela_fieldkit custody verify --case CASE | Verify the event hash chain. |
| Binary analysis | python -m revela_fieldkit binary inspect FILE | Read PE/ELF/Mach-O/WebAssembly headers and APK layout without executing files. |
| File inspection | python -m revela_fieldkit inspect FILE --hash | Report metadata, magic-byte signature, sample entropy and optional SHA-256. |
| Secret-pattern audit | python -m revela_fieldkit secrets scan PATH | Detect selected credential patterns and redact values. |
| Tool discovery | python -m revela_fieldkit doctor | Check whether selected specialist tools are installed. |
| Offline notes | python -m revela_fieldkit knowledge search TERMS | Search bundled reference notes. |
| Case report | python -m revela_fieldkit report --case CASE_DIR | Generate a Markdown report from local case records. |

## Ollama is not required

The native Field Engine is deterministic and model-free. The older Python `ask` command remains an optional legacy local-model bridge, but no Field Engine inspection, simulation, evidence, core-start or core-status command calls it. Do not install a model just to operate the USB.

## USB layout and preparation

The bundle contains:
- `bin/windows-amd64/` — Field Engine, Core-ZERO, Core-ONE and Core-TWO executables.
- `bin/linux-amd64/` — matching Linux x64 executables.
- `runtime-source/` — matching core source/modules and Guardian policy files used by the local supervisor.
- `contracts/finding.schema.json` — versioned hand-off format to Meta Engineer.
- `native/` source in the repository — Go implementation and tests; release bundles contain the executables.
- `src/revela_fieldkit/` — Python evidence companion.
- `runtimes/python-win-x64/` — embedded Python runtime prepared by CI for the Windows USB release.
- `data/` — local cases, logs, reports and runtime state.

Recommended drive: 32 GB minimum for tools and case work; 64 GB or larger if retaining substantial evidence. Use exFAT or NTFS for Windows/Linux sharing. Keep customer evidence on an encrypted, access-controlled volume. Do not commit evidence, credentials, tokens or private keys to a public repository.

### Windows

Run `Start-RevelaAI.cmd` or:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Start-RevelaAI.ps1
```

The CI-built Windows native executable starts first. The Python case-workspace menu is a fallback/companion.

### Linux

```sh
cd /path/to/USB/portable
chmod +x start-linux.sh
./start-linux.sh
```

The native Linux x64 engine starts first. Python 3.10+ is required only for the companion fallback.

## Specialist tools and updates

Ghidra, GNU ddrescue, The Sleuth Kit, Autopsy, TestDisk/PhotoRec, Volatility 3, Wireshark, Zeek, JADX, APKTool, MobSF, Semgrep, Trivy and OSV-Scanner remain separate upstream tools with their own licensing and release processes. The first native release does not silently install them or execute their outputs.

## Limitations — do not overstate capability

- The native Field Engine is an inspection and defensive validation foundation, not a complete EDR, SIEM, penetration-testing platform or automatic malware-removal product.
- Live vulnerability feed import, source authenticity/signature checks and freshness reporting are not implemented yet.
- General Windows/Linux repair adapters, backup/rollback and post-repair verification are not implemented yet.
- The synthetic scenarios do not prove that real EDR/SIEM sensors detect real-world attacks.
- The supervisor checks service health, but package-level cross-core correctness still requires the complete CI test suite and platform smoke tests.
- File hashing is not a forensic image and does not replace a hardware write blocker.
- Hash equality verifies byte identity relative to a reference; it does not prove authenticity, ownership or safety.
- A VPN indicator alone is not malicious activity and must not be used to infer identity.
- Offline AI, when optionally used by the legacy companion, may hallucinate and is never an authority for forensic or repair decisions.

Cloud RevelaAI, hosted providers and any unbundled connectors remain online services. This USB release is a local-first field layer, not a complete offline clone of every RevelaAI cloud service.

Remote sync is allowlisted to `revelaai.onrender.com` by default. A deployment using a different approved HTTPS hostname must explicitly configure `REVELA_FIELD_ALLOWED_SYNC_HOSTS` as a comma-separated list in the local launch environment. Only exact hostnames are accepted; custom remote ports and redirects are rejected. The Field Engine applies its Guardian sync gate before transmission.


### Import a real SBOM before vulnerability matching

The USB supports offline imports from CycloneDX JSON 1.4–1.7 and SPDX JSON 2.3:

```text
revela-field manifest import --format cyclonedx --file ./data/bom.json --out ./data/package-manifest.json --authorized
revela-field manifest import --format spdx-json --file ./data/software.spdx.json --out ./data/package-manifest.json --authorized
```

The importer preserves the SBOM creation timestamp and tool provenance, normalizes component Package URLs by separating the version, traverses nested CycloneDX components, and deduplicates exact package/version entries. Entries missing an exact version or Package URL are counted as skipped. The output manifest must be a new path; the source SBOM is never edited.

After import, run the signed-feed `vuln scan` command described below. CycloneDX XML, SPDX 3.x, direct OS package-database acquisition and dependency-range resolution are not included yet. An SBOM is only as complete and current as its producer; an empty scan is not proof of a clean system.

## Signed offline vulnerability assessment

The native engine includes two additional commands:

```text
revela-field feed verify --file ./data/vuln-feed.json --public-key ./data/trusted-publisher.pub --fingerprint YOUR_PINNED_SHA256 --authorized

revela-field vuln scan --manifest ./data/package-manifest.json --feed ./data/vuln-feed.json --public-key ./data/trusted-publisher.pub --fingerprint YOUR_PINNED_SHA256 --authorized --out-dir ./data/findings
```

The feed envelope contains a Base64 JSON payload and an Ed25519 signature. The operator supplies the publisher public key and its SHA-256 fingerprint obtained separately from a trusted channel. A public key copied from the same untrusted USB as the feed is not sufficient. The engine rejects invalid signatures, wrong key fingerprints, malformed schemas, and expired feeds.

The manifest currently uses the versioned `revela-package-manifest/1` JSON format: `schema_version`, `generated_at`, `source`, and `packages[]` with `ecosystem`, `name`, `version`, and Package URL. A sample format is documented in `docs/VULNERABILITY_FEED_FORMAT.md`.

Matching is deliberately exact: Package URL and version string must both match an advisory. It does not interpret version ranges, distro backports, aliases, OS vendor patch levels, or transitive dependency resolution. A zero-match result means only that this exact matcher found no entries in this particular signed snapshot; it is not proof that the device is vulnerability-free.

Each match becomes a normal Field Engine finding with:
- package-manifest and signed-feed evidence references;
- feed ID, publisher, expiry and payload digest in the assessment report;
- severity, advisory ID and reported fixed versions;
- `scope=local`, `simulated=false`, and a review-only remediation recommendation.

The scanner never downloads updates, installs packages, removes software, disables services or modifies the supplied manifest. Exported findings can be submitted to Meta Engineer using the normal authenticated `sync` command.
