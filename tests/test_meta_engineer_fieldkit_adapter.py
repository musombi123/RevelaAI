"""Contract tests for importing offline Revela Field Engine findings."""
from copy import deepcopy

import pytest

from meta_engineer.fieldkit_adapter import (
    FieldKitFindingError,
    prepare_review_record,
    validate_finding,
)


def sample_finding(simulated=True):
    return {
        "schema_version": "1.0",
        "id": "field-0123456789abcdef",
        "source": "revela-field-engine",
        "observed_at": "2026-10-31T12:00:00Z",
        "target": "isolated synthetic fixture" if simulated else "C:/authorised/lab",
        "category": "identity_monitoring",
        "severity": "informational",
        "title": "Synthetic authentication-failure burst",
        "summary": "A synthetic fixture represents repeated failed authentication events.",
        "evidence": [{"kind": "synthetic_event", "ref": "scenario://auth-failure-burst"}],
        "recommendation": "Review alert thresholds and MFA coverage.",
        "scope": "lab" if simulated else "local",
        "simulated": simulated,
        "techniques": [{"framework": "MITRE ATT&CK Enterprise v20.0", "name": "Brute Force", "tactic": "Credential Access"}],
    }


def test_valid_finding_becomes_review_only_record():
    record = prepare_review_record(sample_finding(), actor="field-operator")
    assert record["status"] == "awaiting_approval"
    assert record["approval_required"] is True
    assert record["auto_execution"] is False
    assert record["auto_deploy"] is False
    assert record["external_side_effects"] is False
    assert "synthetic lab exercise" in record["review_note"]


def test_observed_finding_must_be_local_scoped():
    finding = sample_finding(simulated=False)
    assert validate_finding(finding)["scope"] == "local"
    finding["scope"] = "lab"
    with pytest.raises(FieldKitFindingError):
        validate_finding(finding)


def test_simulated_finding_must_be_lab_scoped():
    finding = sample_finding(simulated=True)
    finding["scope"] = "local"
    with pytest.raises(FieldKitFindingError):
        validate_finding(finding)


def test_untrusted_source_and_invalid_digest_are_rejected():
    finding = sample_finding()
    finding["source"] = "unknown-tool"
    with pytest.raises(FieldKitFindingError):
        validate_finding(finding)

    finding = sample_finding()
    finding["evidence"][0]["sha256"] = "not-a-hash"
    with pytest.raises(FieldKitFindingError):
        validate_finding(finding)


def test_malformed_or_oversized_payload_is_rejected():
    with pytest.raises(FieldKitFindingError):
        validate_finding(None)
    finding = sample_finding()
    finding["summary"] = "x" * 4001
    with pytest.raises(FieldKitFindingError):
        validate_finding(finding)


def test_invalid_actor_is_rejected():
    with pytest.raises(FieldKitFindingError):
        prepare_review_record(sample_finding(), actor=" ")
