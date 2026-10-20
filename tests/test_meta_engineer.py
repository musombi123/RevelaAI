"""Regression tests for review-gated Meta-Engineer proposal generation."""
from meta_engineer.generator import generate_feature
from meta_engineer.introspector import scan_architecture
from meta_engineer.integrator import _safe_path, ForbiddenError

def test_requested_health_route_is_generated_as_proposal():
    result = generate_feature("Add endpoint GET /api/health/meta that returns meta-engineer status")
    assert result["kind"] == "python_fastapi_route_proposal"
    assert '@router.get("/api/health/meta")' in result["code"]
    assert "from fastapi import APIRouter, Request" in result["code"]
    assert "from flask import" not in result["code"]
    assert "proposal_only" in result["code"]
    assert result["runtime_integration"] == "disabled_until_human_approval"


def test_post_backend_proposal_uses_fastapi_and_validates_json():
    result = generate_feature(
        "Add endpoint POST /api/proposals/publish that validates proposal input",
        target="backend",
    )
    code = result["code"]
    assert result["kind"] == "python_fastapi_route_proposal"
    assert "from fastapi import APIRouter, Request" in code
    assert "await request.json()" in code
    assert '"code": "invalid_json"' in code
    assert '"code": "invalid_payload"' in code
    assert "from flask import" not in code


def test_generator_rejects_empty_spec():
    try:
        generate_feature("")
    except ValueError:
        return
    raise AssertionError("empty spec must be rejected")

def test_architecture_scan_is_read_only_and_reports_database_boundary():
    result = scan_architecture()
    assert result["read_only"] is True
    assert result["framework"] == "FastAPI runtime; dormant legacy Flask route source is excluded from the active gateway"
    assert "revelacode.users" not in str(result).lower()

def test_protected_paths_are_rejected():
    try:
        _safe_path("revelai/core/config.py")
    except ForbiddenError:
        return
    raise AssertionError("protected path must be rejected")

def test_release_gate_requires_explicit_approval_and_never_deploys():
    from meta_engineer.release_gate import simulate_staged_release

    result = simulate_staged_release(
        candidate_ref="feature/example",
        previous_release="last-known-good",
        approved=False,
        health_check_passed=True,
    )
    assert result["decision"] == "approval_required"
    assert result["active_release"] == "last-known-good"
    assert result["external_deploy_performed"] is False
    assert result["production_deploy_enabled"] is False


def test_release_gate_rolls_back_simulated_candidate_on_health_failure():
    from meta_engineer.release_gate import simulate_staged_release

    result = simulate_staged_release(
        candidate_ref="feature/example",
        previous_release="last-known-good",
        approved=True,
        health_check_passed=False,
    )
    assert result["decision"] == "rolled_back"
    assert result["active_release"] == "last-known-good"
    assert result["rollback_target"] == "last-known-good"
    assert result["rollback_verified"] is True
    assert result["external_deploy_performed"] is False
    assert result["mode"] == "simulation_only"


def test_release_gate_requires_health_evidence_and_valid_refs():
    import pytest
    from meta_engineer.release_gate import simulate_staged_release

    result = simulate_staged_release(
        candidate_ref="feature/example",
        previous_release="last-known-good",
        approved=True,
        health_check_passed=None,
    )
    assert result["decision"] == "blocked_health_unknown"
    assert result["active_release"] == "last-known-good"
    with pytest.raises(ValueError):
        simulate_staged_release(
            candidate_ref="../production",
            previous_release="last-known-good",
            approved=True,
            health_check_passed=True,
        )

def test_connector_contract_rejects_undeclared_capabilities_and_connectors():
    import pytest
    from revelai.sci_core.connector_contract import (
        ConnectorManifest, ConnectorRegistry, MockSecurityConnector, validate_manifest,
    )

    with pytest.raises(ValueError):
        validate_manifest(ConnectorManifest(
            connector_id="lab-gateway",
            connector_type="hardware_simulator",
            capabilities=("run_arbitrary_command",),
            permissions=("read_telemetry",),
            target_scope="company-lab",
        ))
    registry = ConnectorRegistry(allowed_connector_ids={"approved-lab"})
    with pytest.raises(PermissionError):
        registry.register(MockSecurityConnector(connector_id="unapproved-lab"))


def test_connector_contract_retries_transient_reads_with_a_bounded_limit():
    from revelai.sci_core.connector_contract import ConnectorRegistry, MockSecurityConnector

    adapter = MockSecurityConnector(connector_id="approved-lab", fail_reads_remaining=1)
    registry = ConnectorRegistry(allowed_connector_ids={"approved-lab"})
    registry.register(adapter)
    result = registry.read_telemetry("approved-lab")
    assert result["ok"] is True
    assert result["data"]["device_status"] == "simulated"
    assert adapter.read_attempts == 2


def test_connector_contract_enforces_timeout_and_requires_action_allowlist():
    import pytest
    from revelai.sci_core.connector_contract import (
        ConnectorRegistry, ConnectorTimeout, MockSecurityConnector,
    )

    slow = MockSecurityConnector(connector_id="slow-lab", simulated_latency_ms=5000, request_timeout_seconds=0.05)
    registry = ConnectorRegistry(allowed_connector_ids={"slow-lab"})
    registry.register(slow)
    with pytest.raises(ConnectorTimeout):
        registry.read_telemetry("slow-lab")

    adapter = MockSecurityConnector(connector_id="approved-lab", action_ids=("pulse_test",))
    registry = ConnectorRegistry(allowed_connector_ids={"approved-lab"})
    registry.register(adapter)
    with pytest.raises(PermissionError):
        registry.simulate_action("approved-lab", "unlock_door", {}, "idem-001")


def test_connector_contract_simulated_actions_are_idempotent_and_never_actuate():
    from revelai.sci_core.connector_contract import ConnectorRegistry, MockSecurityConnector

    adapter = MockSecurityConnector(connector_id="approved-lab", action_ids=("pulse_test",))
    registry = ConnectorRegistry(allowed_connector_ids={"approved-lab"})
    registry.register(adapter)
    first = registry.simulate_action("approved-lab", "pulse_test", {"duration_ms": 50}, "idem-002")
    second = registry.simulate_action("approved-lab", "pulse_test", {"duration_ms": 50}, "idem-002")
    assert first == second
    assert first["simulated"] is True
    assert first["external_side_effects"] is False
    assert first["executed"] is False
    assert adapter.simulated_action_count == 1

def test_staging_adapter_contract_blocks_without_explicit_approval():
    from meta_engineer.staging_adapter import SimulatedStagingAdapter, run_staging_drill

    adapter = SimulatedStagingAdapter()
    result = run_staging_drill(
        adapter=adapter,
        candidate_sha="a" * 40,
        previous_sha="b" * 40,
        approval_ref="GH-PR-123",
        approved=False,
    )
    assert result["decision"] == "approval_required"
    assert result["active_sha"] == "b" * 40
    assert result["external_side_effects"] is False
    assert adapter.operations == []


def test_staging_adapter_contract_simulates_healthy_release_without_deployment():
    from meta_engineer.staging_adapter import SimulatedStagingAdapter, run_staging_drill

    adapter = SimulatedStagingAdapter(deploy_result="sim-deploy-1", health_result="healthy")
    result = run_staging_drill(
        adapter=adapter,
        candidate_sha="a" * 40,
        previous_sha="b" * 40,
        approval_ref="GH-PR-124",
        approved=True,
    )
    assert result["decision"] == "staged_candidate_healthy"
    assert result["active_sha"] == "a" * 40
    assert result["health_verified"] is True
    assert result["external_side_effects"] is False
    assert [op["operation"] for op in adapter.operations] == ["deploy_simulated", "health_check_simulated"]


def test_staging_adapter_contract_simulates_rollback_and_verifies_last_known_good():
    from meta_engineer.staging_adapter import SimulatedStagingAdapter, run_staging_drill

    adapter = SimulatedStagingAdapter(
        deploy_result="sim-deploy-2",
        health_result="unhealthy",
        rollback_result="rolled_back",
        rollback_health_result="healthy",
    )
    result = run_staging_drill(
        adapter=adapter,
        candidate_sha="a" * 40,
        previous_sha="b" * 40,
        approval_ref="GH-PR-125",
        approved=True,
    )
    assert result["decision"] == "rolled_back"
    assert result["active_sha"] == "b" * 40
    assert result["rollback_verified"] is True
    assert result["external_side_effects"] is False
    assert [op["operation"] for op in adapter.operations] == [
        "deploy_simulated", "health_check_simulated", "rollback_simulated", "rollback_health_check_simulated"
    ]


def test_staging_adapter_contract_escalates_when_rollback_health_is_bad():
    from meta_engineer.staging_adapter import SimulatedStagingAdapter, run_staging_drill

    adapter = SimulatedStagingAdapter(
        deploy_result="sim-deploy-3",
        health_result="unhealthy",
        rollback_result="rolled_back",
        rollback_health_result="unhealthy",
    )
    result = run_staging_drill(
        adapter=adapter,
        candidate_sha="a" * 40,
        previous_sha="b" * 40,
        approval_ref="GH-PR-126",
        approved=True,
    )
    assert result["decision"] == "rollback_failed_escalate"
    assert result["active_sha"] is None
    assert result["rollback_verified"] is False
    assert result["escalation_required"] is True
    assert result["external_side_effects"] is False



def test_staging_adapter_contract_rejects_live_adapter_objects():
    import pytest
    from meta_engineer.staging_adapter import run_staging_drill

    class LiveLikeAdapter:
        def deploy(self, candidate_sha, idempotency_key):
            raise AssertionError("must never be called")

        def health_check(self, deployment_id):
            raise AssertionError("must never be called")

        def rollback(self, previous_sha, idempotency_key):
            raise AssertionError("must never be called")

    with pytest.raises(PermissionError):
        run_staging_drill(
            adapter=LiveLikeAdapter(),
            candidate_sha="a" * 40,
            previous_sha="b" * 40,
            approval_ref="GH-PR-128",
            approved=True,
        )

def test_staging_adapter_contract_rejects_invalid_commit_and_approval_refs():
    import pytest
    from meta_engineer.staging_adapter import SimulatedStagingAdapter, run_staging_drill

    with pytest.raises(ValueError):
        run_staging_drill(
            adapter=SimulatedStagingAdapter(),
            candidate_sha="../main",
            previous_sha="b" * 40,
            approval_ref="GH-PR-127",
            approved=True,
        )
    with pytest.raises(ValueError):
        run_staging_drill(
            adapter=SimulatedStagingAdapter(),
            candidate_sha="a" * 40,
            previous_sha="b" * 40,
            approval_ref="approved-by-me",
            approved=True,
        )
