"""Unit tests for evidence-driven evolution and authorized migration planning."""
from __future__ import annotations

import hashlib

import pytest

from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.models import EvolutionEvaluationInput, EvolutionRequest, MetricTarget
from core_migrate.models import (
    DeviceEnrollment,
    HardwareResource,
    MigrationPlanRequest,
    RobotBlueprintRequest,
)
from core_migrate.service import MigrationService


def request(depth: int = 1) -> EvolutionRequest:
    return EvolutionRequest(
        system_id="tool.factory",
        objective="Reduce latency while preserving safety and output quality.",
        metrics=[
            MetricTarget(name="latency_ms", direction="minimize", baseline=100, target=50, unit="ms"),
            MetricTarget(name="success_rate", direction="maximize", baseline=0.95, target=0.99),
        ],
        evidence_refs=["benchmark://baseline-v1"],
        requested_depth=depth,
    )


def test_evolution_requires_complete_evidence_and_passed_reviews(tmp_path):
    engine = EvolutionEngine(tmp_path)
    proposal = engine.propose(request())
    report = engine.evaluate(
        proposal.proposal_id,
        EvolutionEvaluationInput(
            proposal_id=proposal.proposal_id,
            observations={"latency_ms": 40, "success_rate": 0.995},
            test_passed=True,
            security_review_passed=True,
            evidence_refs=["benchmark://candidate-v1"],
        ),
    )
    assert report.eligible_for_review is True
    assert report.verdict == "candidate_for_human_review"
    assert report.speedup_ratio == 2.5


def test_evolution_never_claims_improvement_without_observations(tmp_path):
    engine = EvolutionEngine(tmp_path)
    proposal = engine.propose(request())
    report = engine.evaluate(
        proposal.proposal_id,
        EvolutionEvaluationInput(
            proposal_id=proposal.proposal_id,
            test_passed=True,
            security_review_passed=True,
        ),
    )
    assert report.eligible_for_review is False
    assert report.verdict == "insufficient_evidence"
    assert report.speedup_ratio is None


def test_recursive_evolution_is_bounded_and_scoped(tmp_path):
    engine = EvolutionEngine(tmp_path)
    first = engine.propose(request(depth=2))
    second = engine.propose(request(depth=2), parent_proposal_id=first.proposal_id)
    assert second.generation == 2
    with pytest.raises(EvolutionError):
        engine.propose(request(depth=2), parent_proposal_id=second.proposal_id)


def test_migration_blocks_unknown_or_unauthorized_devices(tmp_path):
    service = MigrationService(tmp_path)
    request_body = MigrationPlanRequest(
        artifact_id="tool-a",
        artifact_sha256="a" * 64,
        target_device_ids=["unknown-device"],
        dry_run=True,
    )
    plan = service.plan(request_body)
    assert plan.status == "blocked"
    assert plan.targets[0].eligible is False


def test_migration_requires_verified_resources_and_owner_authorization(tmp_path):
    service = MigrationService(tmp_path)
    service.enroll(DeviceEnrollment(
        device_id="edge-01",
        display_name="Edge Node",
        owner_id="owner-1",
        platform="linux",
        architecture="aarch64",
        agent_version="0.1.0",
        resources=[HardwareResource(kind="cpu", label="CPU", verified=True, capabilities=["compute"])],
        authorized_for_deployment=False,
    ))
    plan = service.plan(MigrationPlanRequest(
        artifact_id="tool-a",
        artifact_sha256="b" * 64,
        target_device_ids=["edge-01"],
        required_capabilities=["compute"],
    ))
    assert plan.status == "blocked"
    assert "Device owner has not authorized deployment." in plan.targets[0].reasons


def test_robot_blueprint_is_proposal_only_and_requires_safety_inventory(tmp_path):
    service = MigrationService(tmp_path)
    service.enroll(DeviceEnrollment(
        device_id="robot-parts",
        display_name="Verified parts inventory",
        owner_id="owner-1",
        platform="jetson",
        architecture="aarch64",
        agent_version="0.1.0",
        resources=[
            HardwareResource(kind="jetson", label="Compute module", verified=True),
            HardwareResource(kind="camera", label="Camera", verified=True),
        ],
    ))
    blueprint = service.robot_blueprint(RobotBlueprintRequest(
        inventory_device_ids=["robot-parts"],
        objective="Prototype a slow indoor inspection robot.",
    ))
    assert blueprint.status == "proposal_only"
    assert blueprint.physical_actuation_enabled is False
    assert "motor_and_motor_controller" in blueprint.missing_capabilities
    assert "verified_emergency_stop" in blueprint.missing_capabilities


def test_artifact_digest_verification(tmp_path):
    artifact = tmp_path / "bundle.rvx"
    artifact.write_bytes(b"verified artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert MigrationService.verify_artifact(artifact, digest)
    assert not MigrationService.verify_artifact(artifact, "0" * 64)
