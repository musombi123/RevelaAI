# USECT-FOUNDRY — Python-Native Factory Builder

The importable implementation lives in `core_foundry/` because Python package names cannot contain hyphens. This directory preserves the specification's `/core-foundry/` organ name.

Current boundary: builds a signed-by-hash, reviewable factory manifest and deterministic workflow plan. It does not execute generated source, actuate hardware, flash firmware, or publish factories without human review. Production factory runtime execution is a later, sandboxed phase after acceptance and Guardian policy tests pass.

Run tests from repository root with `python -m pytest -q tests`.
