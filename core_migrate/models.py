"""Typed contracts for enrolled devices, hardware resources and migration plans."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HardwareResource(StrictModel):
    kind: Literal["cpu", "gpu", "jetson", "camera", "lidar", "motor_controller", "motor", "storage", "network", "other"]
    label: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=1000)
    capabilities: list[str] = Field(default_factory=list, max_length=40)
    verified: bool = False


class DeviceEnrollment(StrictModel):
    device_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    owner_id: str = Field(min_length=1, max_length=120)
    platform: Literal["linux", "windows", "macos", "android", "raspberry_pi", "jetson", "robot", "container", "other"]
    architecture: str = Field(min_length=1, max_length=60)
    agent_version: str = Field(min_length=1, max_length=40)
    resources: list[HardwareResource] = Field(default_factory=list, max_length=100)
    authorized_for_deployment: bool = False
    allow_robot_actuation: bool = False
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MigrationPlanRequest(StrictModel):
    artifact_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    target_device_ids: list[str] = Field(min_length=1, max_length=50)
    artifact_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    required_capabilities: list[str] = Field(default_factory=list, max_length=50)
    dry_run: bool = True
    approval_id: str | None = Field(default=None, max_length=160)

    @field_validator("target_device_ids")
    @classmethod
    def unique_devices(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("target_device_ids must be unique")
        return values


class DeviceHeartbeat(StrictModel):
    device_id: str
    reported_resources: list[HardwareResource] = Field(default_factory=list, max_length=100)
    available_storage_mb: int = Field(ge=0, le=10_000_000)
    load_percent: float = Field(ge=0, le=100)
    agent_ready: bool


class MigrationTargetResult(StrictModel):
    device_id: str
    eligible: bool
    reasons: list[str]
    deployment_state: Literal["planned", "awaiting_approval", "blocked"]


class MigrationPlan(StrictModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    artifact_id: str
    artifact_sha256: str
    dry_run: bool
    targets: list[MigrationTargetResult]
    status: Literal["dry_run", "awaiting_approval", "blocked"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RobotBlueprintRequest(StrictModel):
    inventory_device_ids: list[str] = Field(min_length=1, max_length=50)
    objective: str = Field(min_length=10, max_length=1000)
    required_safety_controls: list[str] = Field(
        default_factory=lambda: ["emergency_stop", "speed_limit", "operator_takeover", "collision_stop"],
        min_length=1,
        max_length=20,
    )


class RobotBlueprint(StrictModel):
    blueprint_id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    resources_found: list[HardwareResource]
    missing_capabilities: list[str]
    required_safety_controls: list[str]
    status: Literal["proposal_only"] = "proposal_only"
    physical_actuation_enabled: bool = False
