"""Tests for the bounded USECT-ZERO brain tool catalogue and dispatcher."""
from __future__ import annotations

from ai import usect_zero_tools as brain_tools
from services import usect_zero_client as client


def test_diagnostics_intent_selects_the_named_read_only_tool():
    assert brain_tools.select_tool_for_message("Run USECT-ZERO diagnostics and check baseline drift") == ("diagnostics", {})
    contract = next(item for item in brain_tools.TOOL_CATALOG if item["operation"] == "diagnostics")
    assert contract["scope"] == "scan:read"
    assert contract["method"] == "GET"
    assert contract["path"] == "/v1/diagnostics"


def test_diagnostics_dispatch_uses_scoped_key_not_admin_channel(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setenv("USECT_ZERO_BRAIN_API_KEY", "scoped-brain-key")
    monkeypatch.setenv("USECT_ZERO_ADMIN_TOKEN", "must-not-be-used-for-brain-tools")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(
            200,
            {
                "schema_version": "usect-zero.diagnostics.v1",
                "status": "ready",
                "baseline": {
                    "status": "compared",
                    "added_count": 2,
                    "modified_count": 1,
                    "missing_count": 0,
                },
            },
        )

    monkeypatch.setattr(brain_tools, "request_core", fake_core)
    result = brain_tools.execute_tool("diagnostics")

    assert result["status"] == "success"
    assert result["executed"] is True
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/diagnostics"
    assert observed["api_key"] == "scoped-brain-key"
    assert observed["admin"] is False
    assert "USECT_ZERO_ADMIN_TOKEN" not in observed


def test_diagnostics_tool_catalog_is_included_in_prompt():
    assert "usect_zero_diagnostics" in brain_tools.tool_catalog_prompt()
