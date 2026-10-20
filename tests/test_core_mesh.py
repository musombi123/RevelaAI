import pytest

import ai.core_mesh as core_mesh


def _online_dashboard():
    return {
        "status": "online",
        "cores": {
            "zero": {"id": "USECT-ZERO", "status": "online", "reachable": True, "version": "test"},
            "one": {"id": "USECT-ONE", "status": "online", "reachable": True, "version": "test"},
            "two": {"id": "USECT-TWO", "status": "online", "reachable": True, "version": "test"},
        },
    }


def test_normal_chat_does_not_trigger_core_health_fanout(monkeypatch):
    monkeypatch.setattr(core_mesh, "_cache_value", None)

    def fail_if_probed(*args, **kwargs):
        raise AssertionError("ordinary chat must not run live core probes")

    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", fail_if_probed)
    result = core_mesh.orchestrator_core_context("Explain photosynthesis in simple terms.")

    assert result["selected_core"] == "orchestrator"
    assert result["mesh_status"] == "not_probed"
    assert result["cores"]["two"]["reachable"] is None
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["automatic_merge"] is False


def test_invention_request_routes_advisorially_to_genesis(monkeypatch):
    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", lambda: _online_dashboard())

    result = core_mesh.orchestrator_core_context(
        "Create a tool that summarizes school documents.",
        domain="general",
        intent="engineering",
    )

    assert result["selected_core"] == "core-one"
    assert result["cores"]["one"]["reachable"] is True
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["human_approval_required"] is True


def test_improvement_request_routes_advisorially_to_infinite_mind(monkeypatch):
    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", lambda: _online_dashboard())

    result = core_mesh.orchestrator_core_context(
        "Improve core performance by reducing repeated scans.",
        domain="general",
        intent="engineering",
    )

    assert result["selected_core"] == "core-two"
    assert result["cores"]["two"]["reachable"] is True
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["automatic_merge"] is False


def test_render_private_hostport_is_normalized_and_allowed(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "usect-zero-core:10000")
    base = core_mesh._base_url("USECT_ZERO_BASE_URL", "")
    assert base == "http://usect-zero-core:10000"
    core_mesh._validate_base(base)


def test_invalid_hostport_is_not_normalized(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "usect-zero-core/path")
    base = core_mesh._base_url("USECT_ZERO_BASE_URL", "")
    assert base == "usect-zero-core/path"
    with pytest.raises(core_mesh.CoreMeshError):
        core_mesh._validate_base(base)


def test_off_host_http_core_url_is_rejected():
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh._validate_base("http://core-service.example.com")
    assert error.value.code == "core_service_tls_required"


def test_only_allowlisted_proposal_fields_are_returned():
    proposal = core_mesh._public_proposal({
        "id": "proposal-123",
        "tool_name": "school_doc_summary",
        "status": "await_merge",
        "source_code": "DO NOT FORWARD THIS",
        "admin_token": "never-return-this",
    })

    assert proposal["id"] == "proposal-123"
    assert proposal["human_approval_required"] is True
    assert proposal["automatic_execution"] is False
    assert proposal["automatic_merge"] is False
    assert "source_code" not in proposal
    assert "admin_token" not in proposal


def test_mind_unavailable_is_explicit_and_normal_chat_stays_available(monkeypatch):
    monkeypatch.setattr(core_mesh, "_cache_value", None)

    def fake_safe_fetch(base, path, *, headers=None):
        if path == "/v1/mind/health":
            return {"status": "unavailable", "reachable": False, "reason": "connect_error"}
        return {"status": "ok", "reachable": True, "version": "test", "count": 0}

    monkeypatch.setattr(core_mesh, "_safe_fetch", fake_safe_fetch)
    snapshot = core_mesh._dashboard_snapshot()
    mind = snapshot["cores"]["two"]

    assert mind["status"] == "unavailable"
    assert mind["availability"] == "mind_unavailable"
    assert mind["reason"] == "mind_unavailable"
    assert "chat and the other cores remain available" in mind["availability_message"]
    assert snapshot["status"] == "degraded"

    # An ordinary chat prompt must not depend on the live Mind daemon.
    result = core_mesh.orchestrator_core_context("What is photosynthesis?")
    assert result["selected_core"] == "orchestrator"
    assert result["safety"]["operation_executed"] is False

def test_core_one_upgrade_routes_to_mind_with_explicit_core_one_target(monkeypatch):
    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", lambda: _online_dashboard())

    result = core_mesh.orchestrator_core_context(
        "Upgrade Core-One to improve its tool reliability.",
        domain="programming",
        intent="engineering",
    )

    assert result["selected_core"] == "core-two"
    assert result["target_core"] == "core-one"
    assert result["operation_kind"] == "core_one_improvement_proposal"
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["target_mutation_performed"] is False
    assert result["safety"]["candidate_source_execution"] is False
    assert result["safety"]["human_approval_required"] is True
    assert result["safety"]["automatic_merge"] is False


def _valid_mind_foundry_candidate():
    return {
        "candidate_id": "candidate_school_summary_v2",
        "source_core": "core-one-foundry",
        "tool_name": "school_doc_summary",
        "objective": "Reduce false positives while preserving the output contract.",
        "baseline_version_hash": "a" * 64,
        "candidate_version_hash": "b" * 64,
        "source_sha256": "c" * 64,
        "risk_tier": 1,
        "sandbox_tested": True,
        "sandbox_evidence_ref": "evidence/core-one/candidate-school-summary-v2.json",
    }


def test_mind_foundry_candidate_bridge_forwards_metadata_only(monkeypatch):
    monkeypatch.setenv("MIND_BASE_URL", "http://127.0.0.1:8782")
    monkeypatch.setattr(core_mesh, "_upstream_headers", lambda **kwargs: {"X-Mind-Token": "internal-test"})
    seen = {}

    def fake_request(base, path, **kwargs):
        seen.update({"base": base, "path": path, **kwargs})
        return {
            "status": "hold",
            "candidate_id": "candidate_school_summary_v2",
            "tool_name": "school_doc_summary",
            "candidate_version_hash": "b" * 64,
            "source_sha256": "c" * 64,
            "guardian_passed": True,
            "core_one_guardian_passed": True,
            "scored": False,
            "score": 0.0,
            "canary": {"decision": "hold"},
            "production_verified": False,
            "automatic_merge": False,
            "promotion_executed": False,
            "rollback_executed": False,
        }

    monkeypatch.setattr(core_mesh, "_request_json", fake_request)
    result = core_mesh.score_mind_foundry_candidate(_valid_mind_foundry_candidate())

    assert seen["path"] == "/v1/mind/candidates"
    assert seen["method"] == "POST"
    assert seen["payload"]["source_core"] == "core-one-foundry"
    assert "source_code" not in seen["payload"]
    assert "candidate_source" not in seen["payload"]
    assert result["target_core"] == "core-one"
    assert result["assessment_only"] is True
    assert result["human_approval_required"] is True
    assert result["automatic_merge"] is False
    assert result["promotion_executed"] is False
    assert result["rollback_executed"] is False
    assert result["status"] == "hold"


def test_mind_foundry_candidate_bridge_rejects_source_code_and_bad_hash(monkeypatch):
    candidate = _valid_mind_foundry_candidate()
    candidate["source_code"] = "package main"

    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh.score_mind_foundry_candidate(candidate)
    assert error.value.code == "invalid_mind_candidate"

    candidate = _valid_mind_foundry_candidate()
    candidate["source_sha256"] = "not-a-hash"
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh.score_mind_foundry_candidate(candidate)
    assert error.value.code == "invalid_mind_candidate"

def test_mind_evolution_proposal_is_explicitly_targeted_at_core_one(monkeypatch):
    monkeypatch.setenv("MIND_BASE_URL", "http://127.0.0.1:8782")
    monkeypatch.setattr(core_mesh, "_upstream_headers", lambda **kwargs: {"X-Mind-Token": "internal-test"})
    monkeypatch.setattr(
        core_mesh,
        "_request_json",
        lambda *args, **kwargs: {
            "status": "await_merge",
            "version": "v1-test",
            "tool_name": "school_doc_summary",
            "selected_mutation": "bounded-input-guard",
            "await_merge_path": "core-two/evolutions/v1-test/AWAIT_MERGE.md",
        },
    )

    result = core_mesh.propose_mind_evolution(
        "Improve Core-One tool reliability using reviewed evidence.",
        "school_doc_summary",
    )

    assert result["target_core"] == "core-one"
    assert result["operation_kind"] == "core_one_improvement_proposal"
    assert result["target_modified"] is False
    assert result["human_approval_required"] is True
    assert result["automatic_merge"] is False
    assert result["automatic_execution"] is False

def test_live_brain_prompt_receives_mind_to_core_one_target_and_safety_rules():
    from services.ai_service import build_grounded_system_prompt

    prompt = build_grounded_system_prompt(
        "BASE PROMPT",
        {
            "core_mesh": {
                "selected_core": "core-two",
                "target_core": "core-one",
                "operation_kind": "core_one_improvement_proposal",
                "route_reason": "Infinite Mind stages Core-One improvements for review.",
                "mesh_status": "online",
                "cores": {},
            }
        },
    )

    assert "- Selected core: core-two" in prompt
    assert "- Target core: core-one" in prompt
    assert "- Operation kind: core_one_improvement_proposal" in prompt
    assert "must not edit Core-One" in prompt
    assert "never forward candidate source code or secrets" in prompt
    assert "Never claim an invention, mutation, repair, deployment, or merge occurred" in prompt
