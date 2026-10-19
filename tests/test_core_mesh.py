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
