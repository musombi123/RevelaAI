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



def test_assembly_catalog_intent_selects_read_only_catalog_tool():
    assert brain_tools.select_tool_for_message("Show registered assembly templates") == ("assemble_templates", {})
    contract = next(item for item in brain_tools.TOOL_CATALOG if item["operation"] == "assemble_templates")
    assert contract["scope"] == "scan:read"
    assert contract["method"] == "GET"
    assert contract["path"] == "/v1/assemble/templates"


def test_assembly_catalog_dispatch_uses_scoped_key_only(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setenv("USECT_ZERO_BRAIN_API_KEY", "scoped-brain-key")
    observed = {}

    def fake_core(method, path, **kwargs):
        observed.update(method=method, path=path, **kwargs)
        return client.CoreReply(200, {
            "status": "ok",
            "schema_version": "usect-zero.assembly-catalog.v1",
            "templates": [],
            "count": 0,
            "human_review_required": True,
        })

    monkeypatch.setattr(brain_tools, "request_core", fake_core)
    result = brain_tools.execute_tool("assemble_templates")
    assert result["status"] == "success"
    assert observed["method"] == "GET"
    assert observed["path"] == "/v1/assemble/templates"
    assert observed["admin"] is False
    assert observed["api_key"] == "scoped-brain-key"


def test_assembly_request_parses_optional_template_version():
    assert brain_tools.select_tool_for_message("Generate ESP32 sensor wiring using template version 1.0.0") == (
        "assemble", {"target": "esp32-sensor", "template_version": "1.0.0"}
    )


def test_assembly_catalog_tool_is_included_in_prompt():
    assert "usect_zero_list_assembly_templates" in brain_tools.tool_catalog_prompt()
