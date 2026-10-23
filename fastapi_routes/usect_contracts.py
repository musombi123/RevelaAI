"""Compatibility API contracts for the documented USECT Seed/Migrate calls.

These endpoints reuse the existing billing, identity and migration services.
They deliberately generate proposals and inventory reports only; they do not
silently scan arbitrary networks, execute remote commands, certify equipment,
or actuate robotics hardware.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core_migrate.models import MigrationPlanRequest, RobotBlueprintRequest
from fastapi_routes.auth import authenticate_identity
from fastapi_routes.evolve_migrate import (
    _migrator,
    _require_enterprise_license,
    _require_organ_token,
)
from revela_platform.database import FactoryRecord, SeedRecord, SessionLocal

router = APIRouter(tags=["USECT Compatibility Contracts"])


def _authorize(request: Request, entitlement: str, payload: dict[str, Any] | None = None):
    """Require the organ secret, the correct signed entitlement and a backend-verified user."""
    _require_organ_token(request.headers.get("X-Organ-Admin-Token"))
    _require_enterprise_license(request.headers.get("X-Revela-License"), entitlement)
    _identity, user_id, error = authenticate_identity(
        request.headers.get("Authorization", ""),
        dict(request.headers),
        payload or {},
    )
    if error is not None:
        return None, error
    return user_id, None


class MigrationCompatInput(BaseModel):
    seed_id: str = Field(min_length=1, max_length=160)
    target_device: str = Field(min_length=3, max_length=120)
    required_capabilities: list[str] = Field(default_factory=list, max_length=50)


class RobotBuildCompatInput(BaseModel):
    objective: str = Field(
        default="Create a safe, reviewable robot architecture proposal from the declared resources.",
        min_length=10,
        max_length=1000,
    )
    resources: dict[str, int | float | str | bool] = Field(default_factory=dict, max_length=50)
    inventory_device_ids: list[str] = Field(default_factory=list, max_length=50)
    required_safety_controls: list[str] = Field(
        default_factory=lambda: [
            "emergency_stop",
            "speed_limit",
            "operator_takeover",
            "collision_stop",
        ],
        min_length=1,
        max_length=20,
    )


@router.post("/v1/migrate/scan", tags=["USECT-MIGRATE"])
def scan_registered_devices(request: Request):
    """Return only devices enrolled into this service; never run an ambient network scan."""
    user_id, error = _authorize(request, "migrate")
    if error is not None:
        return error
    devices = [d for d in _migrator().list_devices() if d.owner_id == user_id]
    entries = []
    for device in devices:
        verified = [r for r in device.resources if r.verified]
        entries.append({
            "device_id": device.device_id,
            "display_name": device.display_name,
            "platform": device.platform,
            "architecture": device.architecture,
            "agent_version": device.agent_version,
            "last_seen": device.last_seen.isoformat(),
            "authorized_for_deployment": device.authorized_for_deployment,
            "verified_resource_count": len(verified),
            "verified_resource_kinds": sorted({r.kind for r in verified}),
            "eligible_for_plan": bool(device.authorized_for_deployment and verified),
        })
    return {
        "status": "completed",
        "discovery_mode": "authenticated_enrolled_inventory",
        "network_scan_performed": False,
        "remote_commands_executed": False,
        "devices": entries,
        "device_count": len(entries),
        "message": (
            "Only explicitly enrolled devices belonging to the authenticated user are listed. "
            "Enroll and verify a device before creating a migration plan."
        ),
    }


@router.post("/v1/migrate/migrate", status_code=202, tags=["USECT-MIGRATE"])
def plan_seed_migration(body: MigrationCompatInput, request: Request):
    """Translate {seed_id, target_device} into a dry-run migration plan, never a remote install."""
    user_id, error = _authorize(request, "migrate", body.model_dump())
    if error is not None:
        return error

    with SessionLocal() as session:
        seed = session.get(SeedRecord, body.seed_id)
        if seed is None:
            raise HTTPException(status_code=404, detail="Seed was not found in the RevelaAI registry.")
        if seed.owner_user_id != user_id:
            raise HTTPException(status_code=403, detail="Seed belongs to another user.")
        factory = session.get(FactoryRecord, seed.parent_build_id)
        if factory is None:
            raise HTTPException(status_code=409, detail="The seed's parent factory manifest is unavailable.")
        manifest_hash = str(factory.manifest_sha256 or "").strip().lower()

    if len(manifest_hash) != 64 or any(ch not in "0123456789abcdef" for ch in manifest_hash):
        raise HTTPException(status_code=409, detail="The parent factory manifest has no valid SHA-256 digest.")

    try:
        device = _migrator().get_device(body.target_device)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Target device is not enrolled.") from exc
    if device.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Target device belongs to another user.")

    plan = _migrator().plan(MigrationPlanRequest(
        artifact_id=body.seed_id,
        artifact_sha256=manifest_hash,
        target_device_ids=[body.target_device],
        required_capabilities=body.required_capabilities,
        dry_run=True,
    ))
    return {
        "status": plan.status,
        "seed_id": body.seed_id,
        "target_device": body.target_device,
        "plan": plan.model_dump(mode="json"),
        "remote_deployment_performed": False,
        "remote_commands_executed": False,
        "physical_actuation_enabled": False,
        "human_approval_required": True,
    }


def _declared_resource_count(resources: dict[str, Any], names: tuple[str, ...]) -> float:
    total = 0.0
    for name, value in resources.items():
        normalized = str(name).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized not in names:
            continue
        try:
            quantity = float(value)
        except (TypeError, ValueError):
            quantity = 1.0 if bool(value) else 0.0
        if quantity > 0:
            total += quantity
    return total


@router.post("/v1/migrate/build-robot", status_code=202, tags=["USECT-MIGRATE"])
def build_robot_proposal(body: RobotBuildCompatInput, request: Request):
    """Produce a non-actuating blueprint proposal from declared resources or verified inventory."""
    user_id, error = _authorize(request, "robot_build", body.model_dump())
    if error is not None:
        return error

    if body.inventory_device_ids:
        for device_id in body.inventory_device_ids:
            try:
                device = _migrator().get_device(device_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=f"Device {device_id} is not enrolled.") from exc
            if device.owner_id != user_id:
                raise HTTPException(status_code=403, detail=f"Device {device_id} belongs to another user.")
        try:
            blueprint = _migrator().robot_blueprint(RobotBlueprintRequest(
                inventory_device_ids=body.inventory_device_ids,
                objective=body.objective,
                required_safety_controls=body.required_safety_controls,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "status": "proposal_only",
            "blueprint": blueprint.model_dump(mode="json"),
            "resource_claims_verified": True,
            "factory_created": False,
            "physical_actuation_enabled": False,
            "human_review_required": True,
        }

    declared = {str(k): v for k, v in body.resources.items()}
    has_compute = _declared_resource_count(declared, ("cpu", "gpu", "jetson", "compute", "compute_controller")) > 0
    has_camera = _declared_resource_count(declared, ("camera", "cameras", "vision", "vision_sensor")) > 0
    has_lidar = _declared_resource_count(declared, ("lidar", "lidars")) > 0
    has_motors = _declared_resource_count(declared, ("motor", "motors", "motor_controller", "motor_controllers")) > 0
    missing = []
    if not has_compute:
        missing.append("compute_controller")
    if not has_camera:
        missing.append("camera_or_vision_sensor")
    if not has_motors:
        missing.append("motor_and_motor_controller")
    if not has_lidar:
        missing.append("lidar_or_documented_alternative")
    missing.extend(["verified_emergency_stop", "operator_takeover", "collision_stop"])
    return {
        "status": "proposal_only",
        "blueprint_id": None,
        "objective": body.objective,
        "declared_resources": declared,
        "resource_claims_verified": False,
        "missing_capabilities": missing,
        "required_safety_controls": body.required_safety_controls,
        "production_line": ["requirements_review", "resource_verification", "safety_design", "human_approval", "bench_testing"],
        "factory_created": False,
        "seed_created": False,
        "remote_deployment_performed": False,
        "physical_actuation_enabled": False,
        "human_review_required": True,
        "message": (
            "This is a planning proposal from user-declared resources, not a verified bill of materials or deployed robot. "
            "Enroll devices and verify resource evidence to obtain an inventory-backed blueprint."
        ),
    }
