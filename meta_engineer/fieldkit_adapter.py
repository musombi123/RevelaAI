"""Validate Field Engine observations and create human-review records.

This adapter is intentionally proposal-only. It does not execute commands,
change host settings, approve repairs, or deploy generated code.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "1.0"
_SOURCE = "revela-field-engine"
_ID = re.compile(r"^field-[a-f0-9]{16}$")
_SEVERITIES = {"informational", "low", "medium", "high", "critical"}
_SCOPES = {"local", "lab"}


class FieldKitFindingError(ValueError):
    """Raised when an imported Field Engine finding violates the contract."""


def validate_finding(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FieldKitFindingError("finding must be a JSON object")

    required = {
        "schema_version", "id", "source", "observed_at", "target",
        "category", "severity", "title", "summary", "evidence",
        "recommendation", "scope", "simulated",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise FieldKitFindingError("missing required fields: " + ", ".join(missing))

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise FieldKitFindingError("unsupported Field Engine finding schema")
    if payload.get("source") != _SOURCE:
        raise FieldKitFindingError("untrusted finding source")
    if not isinstance(payload.get("id"), str) or not _ID.fullmatch(payload["id"]):
        raise FieldKitFindingError("invalid finding identifier")

    timestamp = payload.get("observed_at")
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise FieldKitFindingError("invalid observed_at timestamp")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FieldKitFindingError("observed_at must be ISO-8601") from exc

    limits = {
        "target": 512, "category": 80, "title": 240,
        "summary": 4000, "recommendation": 4000,
    }
    for field, maximum in limits.items():
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FieldKitFindingError(f"{field} must be a non-empty string up to {maximum} characters")

    if payload.get("severity") not in _SEVERITIES:
        raise FieldKitFindingError("unsupported severity")
    if payload.get("scope") not in _SCOPES:
        raise FieldKitFindingError("unsupported scope")
    if not isinstance(payload.get("simulated"), bool):
        raise FieldKitFindingError("simulated must be boolean")
    expected_scope = "lab" if payload["simulated"] else "local"
    if payload["scope"] != expected_scope:
        raise FieldKitFindingError("simulated evidence must be lab-scoped; observed evidence must be local-scoped")

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 50:
        raise FieldKitFindingError("evidence must be an array of at most 50 items")
    for item in evidence:
        if not isinstance(item, dict):
            raise FieldKitFindingError("each evidence item must be an object")
        if not isinstance(item.get("kind"), str) or not item["kind"].strip() or len(item["kind"]) > 80:
            raise FieldKitFindingError("evidence kind is invalid")
        if not isinstance(item.get("ref"), str) or not item["ref"].strip() or len(item["ref"]) > 1024:
            raise FieldKitFindingError("evidence reference is invalid")
        digest = item.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise FieldKitFindingError("evidence SHA-256 is invalid")
        size = item.get("bytes")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise FieldKitFindingError("evidence byte count is invalid")

    techniques = payload.get("techniques", [])
    if not isinstance(techniques, list) or len(techniques) > 20:
        raise FieldKitFindingError("techniques must be an array of at most 20 items")
    for item in techniques:
        if not isinstance(item, dict):
            raise FieldKitFindingError("technique must be an object")
        if not isinstance(item.get("framework"), str) or not item["framework"].strip():
            raise FieldKitFindingError("technique framework is required")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise FieldKitFindingError("technique name is required")

    # Return a detached JSON-safe copy. Caller-owned mutable objects are not reused.
    import json
    return json.loads(json.dumps(payload, ensure_ascii=False))


def prepare_review_record(payload: Any, actor: str) -> dict[str, Any]:
    finding = validate_finding(payload)
    clean_actor = str(actor or "").strip()
    if not clean_actor or len(clean_actor) > 160:
        raise FieldKitFindingError("a valid reviewer/ingesting actor is required")

    simulated_note = (
        "This is a synthetic lab exercise and must not be represented as a live incident."
        if finding["simulated"]
        else "This is an observation from an explicitly authorised local inspection; verify it independently."
    )
    return {
        "kind": "fieldkit_security_review",
        "source": _SOURCE,
        "finding_id": finding["id"],
        "spec": finding["title"] + ": " + finding["summary"],
        "status": "awaiting_approval",
        "actor": clean_actor,
        "target": finding["target"],
        "severity": finding["severity"],
        "category": finding["category"],
        "scope": finding["scope"],
        "simulated": finding["simulated"],
        "evidence": finding,
        "review_note": simulated_note,
        "approval_required": True,
        "candidate_tests_required": True,
        "auto_execution": False,
        "auto_deploy": False,
        "external_side_effects": False,
    }
