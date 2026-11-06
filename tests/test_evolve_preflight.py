"""Tests for the independent Evolver factory preflight gates."""
from __future__ import annotations

import pytest

from fastapi_routes.evolve_migrate import (
    FactoryPreflightBlocked, _active_tool_baseline, _factory_preflight,
)


def architecture_snapshot(*, parse_error: bool = False):
    dependencies = {
        "core_evolve/engine.py": ["os", "pathlib"],
        "core_evolve/learning.py": ["hashlib", "re"],
        "fastapi_routes/evolve_migrate.py": ["fastapi", "core_evolve.engine"],
    }
    if parse_error:
        dependencies["core_evolve/engine.py"] = ["parse-error:SyntaxError"]
    return {
        "read_only": True,
        "structure": {
            "core_evolve": ["core_evolve/engine.py", "core_evolve/learning.py"],
            "fastapi_routes": ["fastapi_routes/evolve_migrate.py"],
        },
        "dependencies": dependencies,
    }


def test_factory_preflight_passes_independent_meta_and_defender_checks(monkeypatch):
    monkeypatch.setattr("meta_engineer.introspector.scan_architecture", architecture_snapshot)
    monkeypatch.setattr("revelai.sci_core.defensive_shield.scan_codebase", lambda: [])
    result = _factory_preflight()
    assert result["meta_engineer"]["status"] == "passed"
    assert result["sci_defender"]["status"] == "passed"
    assert result["meta_engineer"]["read_only"] is True


def test_factory_preflight_blocks_meta_engineer_parse_failures(monkeypatch):
    monkeypatch.setattr(
        "meta_engineer.introspector.scan_architecture",
        lambda: architecture_snapshot(parse_error=True),
    )
    monkeypatch.setattr("revelai.sci_core.defensive_shield.scan_codebase", lambda: [])
    with pytest.raises(FactoryPreflightBlocked, match="parse failures"):
        _factory_preflight()


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_factory_preflight_blocks_sci_defender_high_risk_findings(monkeypatch, severity):
    monkeypatch.setattr("meta_engineer.introspector.scan_architecture", architecture_snapshot)
    monkeypatch.setattr(
        "revelai.sci_core.defensive_shield.scan_codebase",
        lambda: [{"type": "vulnerable_pattern", "severity": severity}],
    )
    with pytest.raises(FactoryPreflightBlocked, match="critical/high findings"):
        _factory_preflight()


def test_factory_preflight_fails_closed_when_security_scan_unavailable(monkeypatch):
    monkeypatch.setattr("meta_engineer.introspector.scan_architecture", architecture_snapshot)

    def fail_scan():
        raise RuntimeError("scanner unavailable")

    monkeypatch.setattr("revelai.sci_core.defensive_shield.scan_codebase", fail_scan)
    with pytest.raises(FactoryPreflightBlocked, match="Sci Defender security preflight failed"):
        _factory_preflight()


def test_factory_capability_registry_separates_source_from_runtime_readiness(monkeypatch):
    from core_evolve.capabilities import capability_registry

    monkeypatch.setattr("core_evolve.capabilities._present", lambda module, source_path, root: True)

    def mongo_unavailable():
        raise RuntimeError("MongoDB unavailable")

    monkeypatch.setattr("core_evolve.learning.ensure_available", mongo_unavailable)
    registry = capability_registry()
    assert registry["schema_version"] == "revela.factory-capability.v1"
    assert registry["registry_kind"] == "capability_inventory_not_executable_tool_registry"
    by_id = {item["capability_id"]: item for item in registry["capabilities"]}
    assert by_id["evolver.evidence_ledger"]["source_present"] is True
    assert by_id["evolver.evidence_ledger"]["runtime_state"] == "blocked"
    assert by_id["genesis.invention_factory"]["runtime_state"] == "not_probed"
    assert by_id["hardware.robot_blueprints"]["execution_boundary"] == "physical_actuation_disabled"


def test_capability_registry_marks_missing_source_without_claiming_runtime_ready(monkeypatch):
    from core_evolve.capabilities import capability_registry

    monkeypatch.setattr("core_evolve.capabilities._present", lambda module, source_path, root: False)
    registry = capability_registry()
    assert all(item["source_present"] is False for item in registry["capabilities"])
    assert all(item["runtime_state"] == "missing" for item in registry["capabilities"])


def test_mind_review_requires_verified_active_genesis_baseline():
    records = [
        {
            "name": "inventory_tool",
            "version": "1.0.0",
            "artifact_hash": "a" * 64,
            "risk_tier": 1,
            "active": False,
            "manifest": {"name": "inventory_tool"},
        },
        {
            "name": "inventory_tool",
            "version": "1.1.0",
            "artifact_hash": "b" * 64,
            "risk_tier": 1,
            "active": True,
            "manifest": {"name": "inventory_tool"},
        },
    ]
    baseline = _active_tool_baseline(records, "inventory_tool")
    assert baseline == {
        "tool_name": "inventory_tool",
        "version": "1.1.0",
        "artifact_hash": "b" * 64,
        "risk_tier": 1,
    }


def test_mind_review_rejects_unverified_or_inactive_baselines():
    records = [
        {
            "name": "inventory_tool",
            "version": "1.0.0",
            "artifact_hash": "not-a-hash",
            "risk_tier": 1,
            "active": True,
            "manifest": {"name": "inventory_tool"},
        },
        {
            "name": "other_tool",
            "version": "1.0.0",
            "artifact_hash": "c" * 64,
            "risk_tier": 1,
            "active": True,
            "manifest": {"name": "other_tool"},
        },
    ]
    assert _active_tool_baseline(records, "inventory_tool") is None
