# Offline vulnerability feed contract

The native Field Engine accepts a locally supplied, Ed25519-signed JSON advisory snapshot. It performs no network requests.

- The envelope contains Base64-encoded exact payload bytes and a hexadecimal Ed25519 signature over those bytes.
- The public key is supplied separately as 64-character hex.
- The operator must also supply the expected SHA-256 fingerprint through a separate trusted channel. A public key stored next to the feed without a pinned fingerprint is not a trust anchor.
- Feed expiry is checked against the local system clock. Clock accuracy is therefore an operational prerequisite.
- Package matching is exact on Package URL and version string. No semver ranges, distro backports, alias resolution or dependency graph interpretation is claimed.
- Findings are reports only. This package never installs, updates, removes or disables software.
- Keep feed provenance, publisher identity, issue time, expiry, signature result and snapshot digest with each assessment.
