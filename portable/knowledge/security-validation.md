# Defensive Security Validation Notes

Use OWASP WSTG and ASVS to structure web application testing. Use CWE to name weakness classes and CVSS v4.0 to communicate technical severity. Business risk also depends on exposure, asset value, exploit prerequisites and mitigations.

A useful finding contains affected asset/version, exact scope, preconditions, expected vs observed behaviour, minimal safe reproduction, redacted evidence, impact, confidence, references, remediation, owner and retest result.

Recommended local tools include Semgrep and CodeQL for code analysis, Trivy and OSV-Scanner for dependencies/images, and OWASP ZAP in a scoped lab/staging environment. Treat all automated results as leads requiring human validation.

A real monitoring service requires installed endpoint/network telemetry, an asset inventory, retention, alert routing and response ownership. A scanner cannot monitor an asset it cannot observe.
