# RevelaAI USB Field Engine

**Version:** 0.3.0 foundation  
**Purpose:** Portable, model-free system inspection, evidence triage and controlled defensive validation.

The primary field runtime is a precompiled Go application. The core commands do not require Ollama, a cloud model, a Go compiler or third-party Go modules on the target computer. The existing Python Field Kit remains as a companion for case work, binary inspection, custody records, secret-pattern review and offline notes.

## Native Go Field Engine

The release workflow builds native executables for Windows x64 and Linux x64 and bundles them under `bin/<os>-<arch>/`. The Windows launcher prefers the native engine. The Linux launcher does the same. Use:

```text
revela-field doctor
revela-field system
revela-field network
revela-field audit --root ./authorised-directory --authorized
revela-field simulate --scenario auth-failure-burst
revela-field simulate --scenario startup-entry
revela-field simulate --scenario vpn-observation
revela-field core-status
```

`doctor` checks whether the separately built Core-ZERO, Core-ONE and Core-TWO executables are bundled. `core-status` probes only their local health endpoints on ports 8780, 8781 and 8782. Binary presence and HTTP reachability are not proof that Guardian enforcement or cross-core integration is correct.

### Safe adversary emulation

The simulator uses synthetic fixtures to validate defensive detection logic. It currently includes authentication-failure bursts, a fictional startup-entry change and VPN tunnel visibility. The scenarios do not create real accounts, startup entries, scheduled tasks, services, registry keys, processes, payloads or network traffic. Each report is explicitly marked `simulated: true`.

Guardian is fail-closed. It permits explicitly authorised local inventory and lab-only synthetic scenarios. It blocks remote exploitation, VPN bypass, credential dumping, stealth evasion, disabling defences, deleting evidence, arbitrary payload execution and external-network scanning.

### System and network inspection

The native engine reports a minimal host snapshot, local network-interface metadata, possible tunnel-interface name hints and the presence (not values) of proxy environment variables. VPN indicators are observations, not evidence of maliciousness. It does not attempt to bypass VPN protections or identify people behind network endpoints.

The file inventory command hashes bounded regular files, skips symlinks and does not execute or modify source files. It is a metadata/evidence inventory, not a malware verdict or forensic disk image.

## Python evidence companion

The companion uses only the Python standard library. It supports:

| Tool | Command | Function |
|---|---|---|
| Case workspace | python -m revela_fieldkit case create ... | Create case metadata, evidence/report folders and custody log. |
| Evidence inventory | python -m revela_fieldkit inventory ... | Hash regular files with SHA-256 and save an integrity manifest. |
| Integrity verification | python -m revela_fieldkit verify ... | Re-hash source files and compare them to the saved manifest. |
| Custody log | python -m revela_fieldkit custody verify ... | Verify the event hash chain. |
| Binary analysis | python -m revela_fieldkit binary inspect FILE | Read PE/ELF/Mach-O/WebAssembly headers and APK layout without executing files. |
| File inspection | python -m revela_fieldkit inspect FILE --hash | Report metadata, magic-byte signature, sample entropy and optional SHA-256. |
| Secret-pattern audit | python -m revela_fieldkit secrets scan PATH | Detect selected credential patterns and redact values. |
| Tool discovery | python -m revela_fieldkit doctor | Check whether selected specialist tools are installed. |
| Offline notes | python -m revela_fieldkit knowledge search TERMS | Search bundled reference notes. |
| Case report | python -m revela_fieldkit report --case CASE_DIR | Generate a Markdown report from local case records. |

## Ollama is not required

The native Field Engine is deterministic and model-free. The older Python `ask` command remains an optional legacy local-model bridge, but no Field Engine inspection, simulation, evidence or core-status command calls it. Do not install a model just to operate the USB.

## USB layout and preparation

The bundle contains:
- `bin/windows-amd64/` — Field Engine, Core-ZERO, Core-ONE and Core-TWO executables.
- `bin/linux-amd64/` — matching Linux x64 executables.
- `contracts/finding.schema.json` — versioned hand-off format to Meta Engineer.
- `native/` source in the repository — Go implementation and tests; release bundles contain the executables.
- `src/revela_fieldkit/` — Python evidence companion.
- `runtimes/python-win-x64/` — embedded Python runtime prepared by CI for the Windows USB release.
- `data/` — reserved for local cases, reports and runtime state.

Recommended drive: 32 GB minimum for tools and case work; 64 GB or larger if retaining substantial evidence. Use exFAT or NTFS for Windows/Linux sharing. Keep customer evidence on an encrypted, access-controlled volume. Do not commit evidence, credentials, tokens or private keys to the public repository.

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

## Meta Engineer hand-off

Field Engine findings use `contracts/finding.schema.json`. The Python adapter in `meta_engineer/fieldkit_adapter.py` validates findings and prepares a review-only record with `awaiting_approval`, candidate tests required and auto-execution disabled. This first iteration validates the contract; an authenticated API ingest route and offline persistent review store remain follow-up work.

## Specialist tools and updates

Ghidra, GNU ddrescue, The Sleuth Kit, Autopsy, TestDisk/PhotoRec, Volatility 3, Wireshark, Zeek, JADX, APKTool, MobSF, Semgrep, Trivy and OSV-Scanner remain separate upstream tools with their own licensing and release processes. The first native release does not silently install them or execute their outputs.

## Limitations — do not overstate capability

- The native Field Engine is an inspection and defensive validation foundation, not a complete EDR, SIEM, penetration-testing platform or automatic malware-removal product.
- Live vulnerability feed import, source authenticity/signature checks and freshness reporting are not implemented yet.
- General Windows/Linux repair adapters, backup/rollback and post-repair verification are not implemented yet.
- The synthetic scenarios do not prove that real EDR/SIEM sensors detect real-world attacks.
- Core binary presence and loopback health responses do not prove all core modules work together. Run CI, stack integration tests and target-device smoke tests.
- File hashing is not a forensic image and does not replace a hardware write blocker.
- Hash equality verifies byte identity relative to a reference; it does not prove authenticity, ownership or safety.
- A VPN indicator alone is not malicious activity and must not be used to infer identity.
- Offline AI, when optionally used by the legacy companion, may hallucinate and is never an authority for forensic or repair decisions.

Cloud RevelaAI, hosted providers and any unbundled connectors remain online services. This USB release is a local-first field layer, not a complete offline clone of every RevelaAI cloud service.
