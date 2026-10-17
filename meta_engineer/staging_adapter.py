"""Typed staging-release adapter contract and deterministic simulator.

Only the simulator ships here. A live adapter needs separate infrastructure
authorization, protected-environment approval and deployment credentials.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL_REF = re.compile(r"^GH-PR-[1-9][0-9]{0,8}$")


class StagingReleaseAdapter(Protocol):
    """Contract for a separately authorized staging deployment adapter."""

    def deploy(self, candidate_sha: str, idempotency_key: str) -> dict[str, Any]: ...
    def health_check(self, deployment_id: str) -> dict[str, Any]: ...
    def rollback(self, previous_sha: str, idempotency_key: str) -> dict[str, Any]: ...


def _validate_sha(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA40.fullmatch(value):
        raise ValueError(f"{field} must be a full 40-character lowercase commit SHA")
    return value


def _validate_approval_ref(value: str) -> str:
    if not isinstance(value, str) or not _APPROVAL_REF.fullmatch(value):
        raise ValueError("approval_ref must reference a GitHub pull request as GH-PR-N")
    return value


def run_staging_drill(
    adapter: StagingReleaseAdapter,
    candidate_sha: str,
    previous_sha: str,
    approval_ref: str,
    approved: bool,
) -> dict[str, Any]:
    """Exercise approval, deploy, health and rollback policy through the adapter contract."""
    candidate = _validate_sha(candidate_sha, "candidate_sha")
    previous = _validate_sha(previous_sha, "previous_sha")
    approval = _validate_approval_ref(approval_ref)
    if candidate == previous:
        raise ValueError("candidate_sha and previous_sha must differ")
    if not isinstance(approved, bool):
        raise ValueError("approved must be boolean")

    base = {
        "policy_version": "staging-release-contract-v1",
        "mode": "adapter_drill",
        "candidate_sha": candidate,
        "previous_sha": previous,
        "approval_ref": approval,
        "approval_received": approved,
        "external_side_effects": False,
        "production_deploy_enabled": False,
    }
    if not approved:
        return {
            **base,
            "decision": "approval_required",
            "active_sha": previous,
            "health_verified": False,
            "rollback_verified": False,
            "escalation_required": False,
            "operations": [],
        }

    # The shipped adapter is the deterministic simulator. Live implementations
    # must be separately reviewed and must not be passed to this simulator API.
    deploy_result = adapter.deploy(candidate, f"deploy:{candidate}:{approval}")
    deployment_id = str(deploy_result.get("deployment_id", ""))
    if not deployment_id:
        return {
            **base,
            "decision": "deploy_adapter_error_escalate",
            "active_sha": previous,
            "health_verified": False,
            "rollback_verified": False,
            "escalation_required": True,
            "operations": [{"operation": "deploy", "status": "missing_deployment_id"}],
        }

    health = adapter.health_check(deployment_id)
    health_status = health.get("status")
    if health_status == "healthy":
        return {
            **base,
            "decision": "staged_candidate_healthy",
            "active_sha": candidate,
            "deployment_id": deployment_id,
            "health_verified": True,
            "rollback_verified": False,
            "escalation_required": False,
            "operations": [
                {"operation": "deploy", "status": "completed"},
                {"operation": "health_check", "status": "healthy"},
            ],
        }

    rollback = adapter.rollback(previous, f"rollback:{previous}:{approval}")
    rollback_status = rollback.get("status")
    if rollback_status != "rolled_back":
        return {
            **base,
            "decision": "rollback_failed_escalate",
            "active_sha": None,
            "deployment_id": deployment_id,
            "health_verified": False,
            "rollback_verified": False,
            "escalation_required": True,
            "operations": [
                {"operation": "deploy", "status": "completed"},
                {"operation": "health_check", "status": str(health_status or "unknown")},
                {"operation": "rollback", "status": str(rollback_status or "unknown")},
            ],
        }

    rollback_health = adapter.health_check(str(rollback.get("deployment_id") or previous))
    rollback_healthy = rollback_health.get("status") == "healthy"
    return {
        **base,
        "decision": "rolled_back" if rollback_healthy else "rollback_failed_escalate",
        "active_sha": previous if rollback_healthy else None,
        "deployment_id": deployment_id,
        "health_verified": False,
        "rollback_verified": rollback_healthy,
        "escalation_required": not rollback_healthy,
        "operations": [
            {"operation": "deploy", "status": "completed"},
            {"operation": "health_check", "status": str(health_status or "unknown")},
            {"operation": "rollback", "status": "rolled_back"},
            {"operation": "rollback_health_check", "status": "healthy" if rollback_healthy else "unhealthy"},
        ],
    }


class SimulatedStagingAdapter:
    """Test adapter only: records simulated calls and never changes infrastructure."""

    def __init__(
        self,
        deploy_result: str = "sim-deployment",
        health_result: str = "healthy",
        rollback_result: str = "rolled_back",
        rollback_health_result: str = "healthy",
    ):
        self.deploy_result = deploy_result
        self.health_result = health_result
        self.rollback_result = rollback_result
        self.rollback_health_result = rollback_health_result
        self.operations: list[dict[str, Any]] = []

    def deploy(self, candidate_sha: str, idempotency_key: str) -> dict[str, Any]:
        self.operations.append({
            "operation": "deploy_simulated",
            "candidate_sha": candidate_sha,
            "idempotency_key": idempotency_key,
            "external_side_effects": False,
        })
        return {"deployment_id": self.deploy_result, "simulated": True}

    def health_check(self, deployment_id: str) -> dict[str, Any]:
        # First health check is candidate; second is rollback target.
        is_rollback_check = any(op["operation"] == "rollback_simulated" for op in self.operations)
        status = self.rollback_health_result if is_rollback_check else self.health_result
        self.operations.append({
            "operation": "rollback_health_check_simulated" if is_rollback_check else "health_check_simulated",
            "deployment_id": deployment_id,
            "status": status,
            "external_side_effects": False,
        })
        return {"status": status, "simulated": True}

    def rollback(self, previous_sha: str, idempotency_key: str) -> dict[str, Any]:
        self.operations.append({
            "operation": "rollback_simulated",
            "previous_sha": previous_sha,
            "idempotency_key": idempotency_key,
            "status": self.rollback_result,
            "external_side_effects": False,
        })
        return {
            "status": self.rollback_result,
            "deployment_id": previous_sha if self.rollback_result == "rolled_back" else "",
            "simulated": True,
        }
