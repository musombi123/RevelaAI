# Revela Field Engine (native Go)

**Version:** 0.3.0 foundation
**Runtime:** Go standard library only
**Model dependency:** none
**Ollama dependency:** none

The Field Engine is the local command centre for the USB edition. It is deterministic: system inventory, local network metadata, bounded file hashing, Guardian decisions, synthetic detection exercises and loopback core supervision do not require an LLM.

## Commands

Build from this directory:

```sh
go test ./...
go vet ./...
go build -trimpath -o revela-field ./cmd/revela-field
```

Run:

```sh
./revela-field doctor
./revela-field system
./revela-field network
./revela-field audit --root ./sample-directory --authorized
./revela-field simulate --scenario auth-failure-burst
./revela-field simulate --scenario startup-entry
./revela-field simulate --scenario vpn-observation --finding-out ./finding.json
./revela-field core-status
./revela-field core-start --authorized
./revela-field sync --finding ./finding.json --url https://revelaai.example
```

On Windows use `revela-field.exe`.

`core-start` is intended for the release bundle at `portable/bin/<os>-<arch>/revela-field`. It requires the matching `portable/runtime-source/` modules, Guardian policy files and three prebuilt core binaries. It starts Core-ZERO, Genesis and Infinite Mind on loopback, with temporary random service tokens, USB-local logs/state and Mind auto-evolution disabled. Child services receive a minimal environment, not the host's cloud-provider or Mongo credentials. Press Ctrl+C to stop the local stack.

`sync` requires `REVELA_ADMIN_BEARER` to contain an existing authorised RevelaCode administrator session. Use it only in the current shell; never persist it to the USB or logs. Remote origins must use HTTPS, loopback HTTP is accepted for development, and HTTP redirects are rejected. Only the versioned JSON finding is sent to the Meta Engineer review endpoint.

## Guardian policy

The policy is fail-closed. It permits a small action allowlist for explicitly authorised local inspection, network metadata review, lab-only synthetic emulation, local core startup, and review-oriented remediation planning. Unknown actions are denied. Remote exploitation, VPN bypass, credential dumping, stealth evasion, disabling defences, evidence deletion, payload execution and external-network scanning are prohibited.

A lab simulation is not a live attack. The included scenarios create synthetic telemetry in memory and emit a report marked `simulated: true`; they do not touch the Windows registry, startup folders, services, scheduled tasks, user accounts, credentials, processes or network targets.

## Inspection guarantees and limits

- System and network commands only read metadata.
- VPN detection is heuristic and reports possible tunnel-interface names; a VPN indicator is not a maliciousness verdict.
- Proxy variable names may be reported, but values are not collected.
- File inventory is bounded to 10,000 files and 256 MiB per file, hashes regular files, skips symlinks and does not execute or modify source files.
- Hashes establish byte identity relative to the recorded observation, not authenticity or safety.
- Core status probes only the local loopback ports 8780, 8781 and 8782. A reachable endpoint is not proof that the full core is healthy or correctly configured.
- General OS remediation is not yet implemented. The current native release creates evidence, performs synthetic validation and starts the three cores; repair adapters require separate allowlisting, backups, explicit review and postcondition tests.

## Cross-component contract

Findings use `../contracts/finding.schema.json`. Meta Engineer's adapter validates the contract. The authenticated `POST /api/meta-engineer/fieldkit/findings` endpoint records an `awaiting_approval` item in the existing review store. It never converts a finding into an automatically executable command. Persistence requires the existing Meta Engineer MongoDB configuration.

## Security principle

Guardian learns attacker tradecraft to validate defensive telemetry in a controlled lab. It does not learn to bypass Guardian, operating-system controls, authentication, network privacy or evidence integrity.

Remote `sync` destinations are restricted to `revelaai.onrender.com` by default. A custom deployment hostname must be explicitly added to `REVELA_FIELD_ALLOWED_SYNC_HOSTS`; remote custom ports and redirects are rejected. Guardian also screens the sync action before sending.

## Offline signed vulnerability feed

The Go engine supports:

```sh
./revela-field feed verify --file ./data/vuln-feed.json --public-key ./data/trusted-publisher.pub --fingerprint YOUR_PINNED_SHA256 --authorized
./revela-field vuln scan --manifest ./data/package-manifest.json --feed ./data/vuln-feed.json --public-key ./data/trusted-publisher.pub --fingerprint YOUR_PINNED_SHA256 --authorized --out-dir ./data/findings
```

The envelope carries exact signed payload bytes, a Base64 payload and an Ed25519 signature. Trust is anchored by a separately pinned SHA-256 fingerprint; do not trust a key merely because it shipped beside a feed. Feed issue/expiry timestamps are checked.

The initial manifest contract is `revela-package-manifest/1`. Matching is exact Package URL plus exact version text; no semver ranges, distro backports, aliases, or transitive-dependency resolution are claimed. An empty result is not a clean bill of health. Findings are local-scope review records only; packages are never changed.
## Import CycloneDX and SPDX manifests

```sh
./revela-field manifest import --format cyclonedx --file ./data/bom.json --out ./data/packages.json --authorized
./revela-field manifest import --format spdx-json --file ./data/software.spdx.json --out ./data/packages.json --authorized
```

CycloneDX JSON 1.4-1.7 and SPDX JSON 2.3 are supported. The importer carries the BOM creation timestamp and tool provenance, traverses nested CycloneDX components, normalizes purls to separate exact version strings, and counts components omitted for missing purl/version. The output is a new file, created without overwriting. It never modifies source SBOMs.
