# Revela Field Engine (native Go)

**Version:** 0.3.0 foundation  
**Runtime:** Go standard library only  
**Model dependency:** none  
**Ollama dependency:** none

The Field Engine is the local command centre for the USB edition. It is deliberately deterministic: system inventory, local network metadata, bounded file hashing, Guardian decisions, and inert synthetic detection exercises do not require an LLM.

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
./revela-field simulate --scenario vpn-observation
./revela-field core-status
```

On Windows use `revela-field.exe`.

## Guardian policy

The policy is fail-closed. It permits a small action allowlist for explicitly authorised local inspection, network metadata review, lab-only synthetic emulation, remediation planning and repair verification. Unknown actions are denied. Remote exploitation, VPN bypass, credential dumping, stealth evasion, disabling defences, evidence deletion, payload execution and external-network scanning are prohibited.

A lab simulation is not a live attack. The included scenarios create synthetic telemetry in memory and emit a report marked `simulated: true`; they do not touch the Windows registry, startup folders, services, scheduled tasks, user accounts, credentials, processes or network targets.

## Inspection guarantees and limits

- System and network commands only read metadata.
- VPN detection is heuristic and reports possible tunnel-interface names; a VPN indicator is not a maliciousness verdict.
- Proxy variable names may be reported, but values are not collected.
- File inventory is bounded to 10,000 files and 256 MiB per file, hashes regular files, skips symlinks and does not execute or modify source files.
- Hashes establish byte identity relative to the recorded observation, not authenticity or safety.
- Core status probes only the local loopback ports 8780, 8781 and 8782. A reachable endpoint is not proof that the full core is healthy or correctly configured.
- This foundation does not yet perform general OS remediation. It creates evidence and supports a safe workflow; actual repair adapters must be separately allowlisted, backed up, reviewed and tested.

## Cross-component contract

Findings use the versioned JSON contract in `../contracts/finding.schema.json`. Meta Engineer's adapter validates this contract and turns an observation into an `awaiting_approval` review record. It never converts a Field Engine finding into an automatically executable command.

## Security principle

Guardian learns attacker tradecraft to validate defensive telemetry in a controlled lab. It does not learn to bypass Guardian, operating-system controls, authentication, network privacy or evidence integrity.
