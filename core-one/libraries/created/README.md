
# Generated Libraries

## Purpose

This directory contains reusable Go contract libraries generated on demand by Revela Genesis Library Forge.

Each generated library provides a bounded, reviewable foundation for reusing capabilities across invention proposals. A library may define contracts, types, validation helpers, interfaces, and other explicitly documented functionality appropriate to its purpose.

Every generated library is a separate artifact. It is not automatically trusted, installed, activated, or imported by the running Genesis engine.

**Default status:** generated proposal awaiting review.  
**Execution policy:** no automatic execution or activation.  
**Import policy:** no dynamic imports into the running Genesis engine.  
**Approval authority:** designated human owner.

## Library Contents

A generated library should include the following artifacts where applicable:

- **Driver (`driver.go`)** — exposes the library's declared capability contract and bounded behavior.
- **Tests** — verify the documented interface, expected behavior, input validation, and failure conditions.
- **Documentation (`README.md`)** — explains the purpose, public API, limitations, usage assumptions, and review requirements.
- **Metadata (`library.json`)** — records the library identity, version, description, declared capabilities, dependencies, and review status.
- **Integrity information** — records relevant artifact hashes when supported by the generation pipeline.

The exact artifact set should be documented in the library metadata. A missing required artifact must remain visible as an incomplete library rather than being treated as a verified reusable component.

## Library Identity and Metadata

Every library should have a stable, normalized identity that is independent of its display title.

Where supported, metadata should record:

- Stable library ID and normalized name.
- Schema and library versions.
- Creation timestamp and generator version.
- Purpose and capability descriptions.
- Public Go package name and exposed interfaces.
- Declared dependencies and compatible versions.
- Source invention or proposal references.
- Artifact inventory and integrity hashes.
- Known limitations and unresolved requirements.
- Current review and approval status.

Names and package identifiers must be validated before source generation. Generated metadata must not be allowed to inject source code, alter filesystem paths, or override trusted engine configuration.

## Generation and Review Lifecycle

Generated libraries should progress through an explicit lifecycle:

1. **Proposed** — Library Forge identifies a reusable capability or contract.
2. **Generated** — Source files, tests, documentation, and metadata are created.
3. **Validated** — Required files, metadata, package identifiers, dependencies, and resource limits are checked.
4. **Tested** — The library is compiled and its tests are run in an appropriate isolated workspace.
5. **Awaiting review** — The library is available for human assessment.
6. **Approved or rejected** — An authorized reviewer records the decision and rationale.
7. **Integrated separately** — An approved library is incorporated through the controlled development process.
8. **Verified** — Integration tests, compatibility checks, and applicable security reviews pass.

Generating a library does not automatically mark it safe, compatible, approved, or ready for production.

Approval of a library is also not authorization to dynamically load it into Genesis. Integration must happen through the project's explicit build, dependency, and release workflow.

## Reuse and Compatibility

Library Forge may recommend existing libraries when a new invention requires similar capabilities.

A matching description or capability score is only a discovery signal. Before reuse, reviewers should establish:

- The public API matches the intended use.
- Source code and metadata are available for review.
- The implementation and tests support the claimed behavior.
- Dependencies are known, permitted, and compatible.
- The licensing terms permit the intended use.
- Security and privacy requirements are satisfied.
- No undocumented network access, filesystem access, or device control is introduced.
- The library does not weaken Guardian policy or other core safety boundaries.

Reusable-library discovery must distinguish between a **candidate**, a **validated artifact**, a **reviewed library**, and an **approved integration**. These states are not interchangeable.

## Dependency Management

Each library should declare its direct dependencies and any material version constraints.

Dependency review should cover:

- Exact dependency identity and version.
- License compatibility.
- Known vulnerabilities and maintenance status.
- Transitive dependency exposure.
- Reproducible builds and lockfile behavior.
- Network access or external service requirements.
- Upgrade and rollback considerations.

Missing dependency information must be treated as unresolved. A successful package match or compilation alone does not establish that a library is safe or appropriately licensed.

Prefer existing standard-library functionality where practical. Any additional dependency should have a documented justification.

## Security and Safety Requirements

Generated libraries must remain within the permissions granted to their approved integration.

Reviewers should check for:

- Unexpected file, network, process, or environment access.
- Credential collection, logging, or disclosure.
- Unsafe deserialization and unbounded resource consumption.
- Path traversal and symlink-related filesystem risks.
- Unvalidated inputs and uncontrolled error handling.
- Unnecessary personal-data collection.
- Unreviewed device-control or external-side-effect operations.
- Changes that bypass Guardian or human-approval requirements.

A library that handles hardware, credentials, financial operations, or sensitive data may require additional specialist review and integration-specific safeguards.

Tests and metadata are evidence for review; they are not substitutes for reviewing the implementation.

## Testing and Verification

Before a library is recommended for integration, the applicable checks should include:

- Go formatting and compilation.
- Unit tests for documented behavior.
- Negative tests for invalid and oversized inputs.
- Tests for error handling and failure conditions.
- Dependency and license review.
- Static analysis and security checks.
- Integration tests for consumers of the public contract.
- Verification that the implementation matches its metadata and documentation.

Tests should be run against the actual generated source in a controlled workspace. A generated test file existing on disk does not mean the test passed.

Record test results and relevant tool versions when the generation pipeline supports them.

## Integrity and Change History

When artifact hashes are produced, retain them alongside the corresponding artifact inventory.

Integrity hashes can help identify changes after generation, but they do not independently prove that the source is trustworthy or safe.

When a library changes materially:

- Preserve the previous version or its recorded provenance.
- Record the reason for the change.
- Update relevant tests and documentation.
- Re-run affected validation and review checks.
- Reassess consumers that depend on the previous API.
- Obtain renewed approval where the change affects safety, permissions, dependencies, or public behavior.

Never silently replace an approved library with an unreviewed revision while retaining the old approval status.

## Relationship to Genesis Core

Genesis may inspect library metadata and rank potential reuse candidates. Such discovery does not confer trust.

The running engine must not automatically:

- Dynamically import a generated library.
- Execute generated library code merely because it exists in this directory.
- Install dependencies without the approved development workflow.
- Treat an unreviewed library as a trusted implementation.
- Modify its own core source or runtime configuration.
- Override Guardian rules or human-approval requirements.

Any integration must be explicit, reviewable, tested, and traceable to an approved change.

## Suggested Directory Organization

The following is a proposed organization, not a claim that every directory already exists:

```text
libraries/
└── created/
    ├── README.md
    └── <library-name>/
        ├── library.json
        ├── driver.go
        ├── driver_test.go
        └── README.md
```

If the current implementation stores each library's files directly under a different layout, retain that established layout unless a separately reviewed migration is approved.

## Acceptance Criteria

A generated library is ready to be considered for integration only when:

- Its identity and metadata are valid.
- Its declared capabilities and public API are documented.
- Required source, tests, and documentation exist.
- Dependencies and licensing considerations have been reviewed.
- Applicable tests and static checks have been run.
- Security, privacy, and permission boundaries have been assessed.
- Known limitations and unresolved requirements are recorded.
- A designated owner has reviewed the proposed integration.

These criteria establish readiness for review, not automatic production approval.

## Operating Principle

**Generate for reuse. Validate the artifact. Test the behavior. Review the dependencies. Require explicit approval. Integrate through a controlled release.**

A generated library is a reusable candidate—not trusted runtime code merely because Library Forge created it.
