"""Tests for USECT-ZERO as a primary brain tool, not a provider fallback."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from ai import usect_zero_tools as tools


def test_repository_scan_is_selected_before_model_generation():
    selected = tools.select_tool_for_message(
        "Please scan this repository and show its architecture and tracked files."
    )
    assert selected == ("scan", {})


@pytest.mark.parametrize(
    "message",
    [
        "Hi RevelaAI, how are you?",
        "Explain polymorphism in object-oriented programming.",
        "Write a romantic caption for my photo.",
    ],
)
def test_unrelated_requests_do_not_call_usect_zero(message):
    assert tools.select_tool_for_message(message) is None


def test_bridge_plan_selects_declared_bridge_target():
    assert tools.select_tool_for_message(
        "Create an integration bridge plan for a ROS2 robot"
    ) == ("bridge", {"target": "ros2"})


def test_rv_lang_tool_requires_explicit_source():
    assert tools.select_tool_for_message(
        "Compile this RV Lang source: scan\nheal src/example.py"
    ) == ("mind", {"source": "scan\nheal src/example.py"})
    assert tools.select_tool_for_message("Please explain what RV Lang is") is None


def test_radar_requires_user_supplied_current_and_candidate_evidence():
    assert tools.select_tool_for_message(
        "Compare candidate version 2.0.0 against current version 1.0.0"
    ) is None

    supplied = {
        "current": {
            "name": "core",
            "version": "1.0.0",
            "benchmark": 100,
            "source": "local test",
            "evidence_id": "test-current",
        },
        "candidate": {
            "name": "core",
            "version": "2.0.0",
            "benchmark": 140,
            "source": "local test",
            "evidence_id": "test-candidate",
        },
    }
    selected = tools.select_tool_for_message(
        "Use radar to compare this benchmark evidence: " + __import__("json").dumps(supplied)
    )
    assert selected is not None
    operation, args = selected
    assert operation == "radar"
    assert args == supplied


def test_execution_uses_dedicated_scoped_key_and_redacts_repository_root(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BRAIN_TOKEN", "brain-tool-key")
    core_call = Mock(return_value=type("Reply", (), {
        "status_code": 200,
        "payload": {
            "status": "ok",
            "repository_root": "/srv/private/host-system-alpha",
            "file_count": 41,
            "git_head": "abc123",
            "manifest_sha256": "sha256",
            "language_counts": {"Python": 23, "Go": 18},
            "files": [
                {"path": "app.py", "sha256": "a", "bytes": 2, "language": "Python"},
            ],
            "read_only": True,
        },
    })())
    monkeypatch.setattr(tools, "request_core", core_call)

    outcome = tools.execute_for_message("Scan the repository architecture now.")

    assert outcome is not None
    assert outcome["tool"] == "usect_zero"
    assert outcome["name"] == "usect_zero_scan_repository"
    assert outcome["status"] == "success"
    assert outcome["fallback"] is False
    assert outcome["result"]["file_count"] == 41
    assert "repository_root" not in outcome["result"]
    assert "/srv/private/host-system-alpha" not in str(outcome)
    core_call.assert_called_once_with(
        "GET",
        "/v1/scan",
        body=None,
        api_key="brain-tool-key",
        admin=False,
    )


def test_matched_tool_fails_closed_when_generated_brain_token_is_missing(monkeypatch):
    monkeypatch.delenv("USECT_ZERO_BRAIN_TOKEN", raising=False)
    core_call = Mock(side_effect=AssertionError("missing token must not call the core"))
    monkeypatch.setattr(tools, "request_core", core_call)

    outcome = tools.execute_for_message("Scan this repository and list its files.")

    assert outcome is not None
    assert outcome["status"] == "unavailable"
    assert outcome["error_code"] == "usect_zero_brain_token_missing"
    assert outcome["fallback"] is False
    core_call.assert_not_called()


def test_tool_key_is_not_a_provider_key_or_admin_token(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BRAIN_TOKEN", "scoped-developer-key")
    core_call = Mock(return_value=type("Reply", (), {
        "status_code": 200,
        "payload": {"status": "ok", "read_only": True},
    })())
    monkeypatch.setattr(tools, "request_core", core_call)

    tools.execute_tool("scan")

    assert core_call.call_args.kwargs["admin"] is False
    assert core_call.call_args.kwargs["api_key"] == "scoped-developer-key"


def test_primary_brain_does_not_invoke_model_when_required_tool_is_unavailable(monkeypatch):
    import importlib
    import sys
    import types

    existing_service = sys.modules.pop("services.ai_service", None)
    stubs = {
        "ai.ai_client": types.ModuleType("ai.ai_client"),
        "ai.system_prompt": types.ModuleType("ai.system_prompt"),
        "ai.orchestrator": types.ModuleType("ai.orchestrator"),
    }
    stubs["ai.ai_client"].ask_hf = lambda **kwargs: pytest.fail(
        "must not silently fall back to a model answer"
    )
    stubs["ai.system_prompt"].SYSTEM_PROMPT = "test system prompt"

    class StubOrchestrator:
        def process_prompt(self, **kwargs):
            pytest.fail("unavailable required tools should return before orchestration")

    stubs["ai.orchestrator"].Orchestrator = StubOrchestrator

    try:
        with monkeypatch.context() as isolated:
            for name, module in stubs.items():
                isolated.setitem(sys.modules, name, module)
            ai_service = importlib.import_module("services.ai_service")
            isolated.setattr(
                ai_service,
                "execute_for_message",
                lambda *args, **kwargs: {
                    "tool": "usect_zero",
                    "name": "usect_zero_scan_repository",
                    "operation": "scan",
                    "status": "unavailable",
                    "executed": False,
                    "fallback": False,
                    "error_code": "usect_zero_brain_token_missing",
                },
            )

            result = ai_service.process_message(
                "Scan this repository and diagnose its structure.",
                intent="programming",
            )
    finally:
        sys.modules.pop("services.ai_service", None)
        if existing_service is not None:
            sys.modules["services.ai_service"] = existing_service

    assert result["error_code"] == "engineering_tool_unavailable"
    assert result["capability"] == "engineering_tool"
    assert result["tool_execution"]["status"] == "unavailable"
