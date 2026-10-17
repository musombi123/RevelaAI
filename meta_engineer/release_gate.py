"""Pure release-gate state machine used for simulation and policy tests.

This module deliberately has no deployment client and performs no external
side effects. A real staging adapter must be implemented and authorized
separately before this policy can control infrastructure.
"""
from __future__ import annotations

import re
from typing import Any

_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def _validate_ref(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string identifier")
    clean = value.strip()
    if (
        not _REF_PATTERN.fullmatch(clean)
        or ".." in clean
        or "//" in clean
        or clean.endswith("/")
    ):
        raise ValueError(f"{field} is not a valid bounded release identifier")
    return clean


def simulate_staged_release(
    candidate_ref: str,
    previous_release: str,
    approved: bool,
    health_check_passed: bool | None,
) -> dict[str, Any]:
    """Simulate approval, health gating and rollback without deploying anything."""
    candidate = _validate_ref(candidate_ref, "candidate_ref")
    previous = _validate_ref(previous_release, "previous_release")
    if not isinstance(approved, bool):
        raise ValueError("approved must be boolean")
    if health_check_passed is not None and not isinstance(health_check_passed, bool):
        raise ValueError("health_check_passed must be boolean or null")

    decision = "approval_required"
    active_release = previous
    rollback_target = None
    rollback_verified = False
    if approved and health_check_passed is None:
        decision = "blocked_health_unknown"
    elif approved and health_check_passed is True:
        decision = "staged_candidate_healthy"
        active_release = candidate
    elif approved and health_check_passed is False:
        decision = "rolled_back"
        rollback_target = previous
        active_release = previous
        rollback_verified = True

    return {
        "policy_version": "release-gate-simulation-v1",
        "mode": "simulation_only",
        "candidate_ref": candidate,
        "previous_release": previous,
        "approval_received": approved,
        "health_check_passed": health_check_passed,
        "decision": decision,
        "active_release": active_release,
        "rollback_target": rollback_target,
        "rollback_verified": rollback_verified,
        "external_deploy_performed": False,
        "production_deploy_enabled": False,
        "human_approval_required_for_real_deploy": True,
    }
