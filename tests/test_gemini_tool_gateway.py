from __future__ import annotations

import json

import pytest

from ai import gemini_tool_gateway as gateway


def _names(*, operator=False, automation=False):
    return {
        item["name"]
        for item in gateway.gemini_tool_declarations(
            include_privileged=operator,
            include_automation=automation,
        )
    }


def test_read_only_catalogue_is_available_without_automation():
    names = _names()

    assert "revelaai_research" in names
    assert "revelaai_get_core_status" in names
    assert "revelaai_get_learning_status" in names
    assert "revelaai_verify_seed" in names
    assert "usect_zero_scan_repository" in names

    assert "revelaai_plan_tool" not in names
    assert "revelaai_draft_feature" not in names
    assert "usect_zero_assemble_fixture" not in names
    assert "revelaai_request_mind_evolution" not in names


def test_automation_catalogue_exposes_planning_but_not_operator_only_tools():
    names = _names(automation=True, operator=False)

    assert "revelaai_plan_tool" in names
    assert "revelaai_draft_feature" in names
    assert "usect_zero_assemble_fixture" in names
    assert "revelaai_propose_evolution" not in names
    assert "revelaai_request_mind_evolution" not in names
    assert "revelaai_inspect_meta_engineer" not in names


def test_operator_catalogue_exposes_guarded_evolution_tools_only_with_automation():
    denied_names = _names(automation=False, operator=True)
    allowed_names = _names(automation=True, operator=True)

    assert "revelaai_request_mind_evolution" not in denied_names
    assert "revelaai_request_mind_evolution" in allowed_names
    assert "revelaai_inspect_meta_engineer" in allowed_names
    assert "revelaai_plan_device_migration" in allowed_names


def test_automation_intent_classifier_catches_tool_builds_but_not_explanations():
    assert gateway.requires_automation_entitlement("Build a full-stack soil analysis tool")
    assert gateway.requires_automation_entitlement("Run the Genesis signed tool")
    assert not gateway.requires_automation_entitlement("Explain Gemini function calling")
    assert not gateway.requires_automation_entitlement("What can RevelaAI help me research?")


def test_draft_feature_is_blocked_before_generator_when_entitlement_is_missing(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "_automation_entitlement",
        lambda _authorization: {
            "status": "blocked",
            "executed": False,
            "reason": "automation_entitlement_required",
        },
    )

    def should_not_generate(*_args, **_kwargs):
        raise AssertionError("Generator must not run without entitlement.")

    monkeypatch.setattr("meta_engineer.generator.generate_feature", should_not_generate)
    result = gateway._dispatch_gemini_tool_impl(
        "revelaai_draft_feature",
        {"specification": "Build a bounded crop-health assistant", "target": "fullstack"},
        user_id="user-1",
        authorization="Bearer denied",
    )

    assert result["status"] == "blocked"
    assert result["executed"] is False
    assert result["reason"] == "automation_entitlement_required"


def test_draft_feature_returns_review_only_scaffold(monkeypatch):
    marks = []
    monkeypatch.setattr(gateway, "_automation_entitlement", lambda _authorization: None)
    monkeypatch.setattr(gateway, "_mark", lambda core, operation, status: marks.append((core, operation, status)))
    monkeypatch.setattr(
        "meta_engineer.generator.generate_feature",
        lambda specification, target: {
            "feature": "crop-helper",
            "target": target,
            "spec": specification,
            "files": [{"path": "backend-proposals/crop-helper.py", "content": "# review-only"}],
            "runtime_integration": "disabled_until_human_approval",
            "auto_deploy": False,
        },
    )

    result = gateway._dispatch_gemini_tool_impl(
        "revelaai_draft_feature",
        {"specification": "Build a bounded crop-health assistant", "target": "backend"},
        user_id="user-1",
        authorization="Bearer granted",
    )

    assert result["status"] == "proposal_only"
    assert result["executed"] is False
    assert result["safety"]["source_written_to_repository"] is False
    assert result["safety"]["generated_code_execution"] is False
    assert ("meta_engineer", "draft_feature_scaffold", "proposal_only") in marks


def test_seed_verification_is_owner_scoped(monkeypatch):
    class FakeSeedRunner:
        def verify_child_offline(self, seed_id):
            assert seed_id == "seed_" + "a" * 24
            return {
                "ok": True,
                "seed_id": seed_id,
                "owner_user_id": "another-user",
                "execution_enabled": False,
            }

    monkeypatch.setattr("core_seed.seed_runner.SeedRunner", FakeSeedRunner)
    result = gateway._dispatch_gemini_tool_impl(
        "revelaai_verify_seed",
        {"seed_id": "seed_" + "a" * 24},
        user_id="user-1",
        authorization="",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "seed_owner_mismatch"


def test_core_evolve_proposal_is_not_misreported_as_core_two_usage(monkeypatch):
    marks = []

    class FakeProposal:
        def model_dump(self, mode="python"):
            return {"proposal_id": "proposal-1", "status": "proposed"}

    class FakeEngine:
        def propose(self, request):
            assert request.system_id == "revelaai-tool-runtime"
            return FakeProposal()

    monkeypatch.setattr(gateway, "_operator_allowed", lambda _user_id: True)
    monkeypatch.setattr(gateway, "_automation_entitlement", lambda _authorization: None)
    monkeypatch.setattr(gateway, "_mark", lambda core, operation, status: marks.append((core, operation, status)))
    monkeypatch.setattr("core_evolve.engine.EvolutionEngine", FakeEngine)

    result = gateway._dispatch_gemini_tool_impl(
        "revelaai_propose_evolution",
        {
            "system_id": "revelaai-tool-runtime",
            "objective": "Reduce tool dispatch latency without reducing validation coverage.",
            "metrics": [{"name": "latency_ms", "direction": "minimize", "baseline": 100, "target": 80}],
        },
        user_id="operator-1",
        authorization="Bearer granted",
    )

    assert result["status"] == "proposal_only"
    assert ("core_evolve", "propose", "proposal_only") in marks
    assert not any(core == "core_two_infinite_mind" for core, _, _ in marks)


def test_gateway_tool_registry_includes_the_new_general_capabilities():
    assert gateway.is_gateway_tool("revelaai_draft_feature")
    assert gateway.is_gateway_tool("revelaai_verify_seed")
    assert gateway.is_gateway_tool("revelaai_get_learning_status")
