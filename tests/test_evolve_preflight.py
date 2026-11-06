"""Tests for the independent Evolver factory preflight gates."""
from __future__ import annotations

import pytest

from fastapi_routes.evolve_migrate import FactoryPreflightBlocked, _factory_preflight


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
