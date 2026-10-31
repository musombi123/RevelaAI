# Field Methods: Evidence, Recovery and Security Work

## Before an investigation
Obtain written authority, define the exact devices/accounts/assets and time period, record exclusions, agree data handling, and nominate an emergency contact. Do not expand scope based on discoveries.

## Evidence integrity
Record who collected an item, when and where, the device identity and condition, acquisition method, tool version, cryptographic hash, errors, and each transfer. Keep originals protected and analyze verified working copies. A hash can show that a byte sequence has not changed between comparisons; it does not establish who created the file or whether the content is truthful.

## Recovery triage
Avoid writing to the source. A software inventory/hash is not forensic imaging. Failing disks may need a hardware write blocker and a specialist acquisition process. On physically unstable media, stop repeated power cycles and refer to a qualified recovery lab. Recovery depends on encryption, TRIM, overwrites and hardware condition.

## Security validation
Use an asset allowlist and written scope. Start with source/dependency/configuration checks, then passive observation, then narrowly scoped tests in staging. A scanner alert is a hypothesis. Confirm affected versions, preconditions, impact and evidence; report false positives and limitations. Never claim a finding is confirmed solely because a tool printed a warning.

## Stop conditions
Stop when the target is out of scope, a device may be damaged by continued operation, sensitive out-of-scope data appears, service stability is affected, or authority is unclear.
