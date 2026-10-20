"""Fail-closed device registry and migration planner.

No port scanning, silent enrollment, remote command execution, or physical actuation
is performed here. Devices enter the inventory through an authenticated enrollment
workflow, and migration produces a verifiable plan rather than silently deploying.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable

from .models import (
    DeviceEnrollment,
    HardwareResource,
    MigrationPlan,
    MigrationPlanRequest,
    MigrationTargetResult,
    RobotBlueprint,
    RobotBlueprintRequest,
)


class MigrationError(RuntimeError):
    """Invalid migration or inventory state."""


class MigrationService:
    def __init__(self, store_dir: str | Path | None = None) -> None:
        root = store_dir or os.getenv("REVELA_MIGRATE_STORE", ".revela/migrate")
        self.store_dir = Path(root).expanduser().resolve()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.inventory_path = self.store_dir / "inventory.json"
        self.plans_path = self.store_dir / "plans.json"
        self._inventory: dict[str, DeviceEnrollment] = {}
        self._plans: dict[str, MigrationPlan] = {}
        self._load()

    def _load(self) -> None:
        if self.inventory_path.exists():
            raw = json.loads(self.inventory_path.read_text(encoding="utf-8"))
            self._inventory = {key: DeviceEnrollment.model_validate(value) for key, value in raw.items()}
        if self.plans_path.exists():
            raw = json.loads(self.plans_path.read_text(encoding="utf-8"))
            self._plans = {key: MigrationPlan.model_validate(value) for key, value in raw.items()}

    def _persist(self) -> None:
        for path, payload in (
            (self.inventory_path, {key: value.model_dump(mode="json") for key, value in self._inventory.items()}),
            (self.plans_path, {key: value.model_dump(mode="json") for key, value in self._plans.items()}),
        ):
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            temp.replace(path)

    def enroll(self, device: DeviceEnrollment) -> DeviceEnrollment:
        self._inventory[device.device_id] = device
        self._persist()
        return device

    def list_devices(self) -> list[DeviceEnrollment]:
        return sorted(self._inventory.values(), key=lambda item: item.device_id)

    def get_device(self, device_id: str) -> DeviceEnrollment:
        device = self._inventory.get(device_id)
        if device is None:
            raise KeyError(device_id)
        return device

    def plan(self, request: MigrationPlanRequest) -> MigrationPlan:
        results: list[MigrationTargetResult] = []
        for device_id in request.target_device_ids:
            device = self._inventory.get(device_id)
            if device is None:
                results.append(MigrationTargetResult(
                    device_id=device_id, eligible=False,
                    reasons=["Device is not enrolled in this RevelaAI deployment."],
                    deployment_state="blocked",
                ))
                continue
            reasons: list[str] = []
            if not device.authorized_for_deployment:
                reasons.append("Device owner has not authorized deployment.")
            available = {cap for resource in device.resources if resource.verified for cap in resource.capabilities}
            available.update(resource.kind for resource in device.resources if resource.verified)
            missing = sorted(set(request.required_capabilities) - available)
            if missing:
                reasons.append("Missing verified capabilities: " + ", ".join(missing))
            if not device.resources:
                reasons.append("No hardware resource inventory has been verified.")
            eligible = not reasons
            if request.dry_run:
                state = "planned" if eligible else "blocked"
            elif eligible and not request.approval_id:
                reasons.append("A human approval_id is required before deployment.")
                eligible = False
                state = "awaiting_approval"
            elif eligible:
                # This organ deliberately emits a deployment plan only. A trusted,
                # enrolled device agent must verify the manifest before installing.
                state = "awaiting_approval"
                reasons.append("Plan is ready for the separately authenticated device agent; no remote execution occurred.")
            else:
                state = "blocked"
            results.append(MigrationTargetResult(
                device_id=device_id, eligible=eligible, reasons=reasons, deployment_state=state
            ))

        if all(target.eligible for target in results) and request.dry_run:
            status = "dry_run"
        elif any(target.deployment_state == "awaiting_approval" for target in results):
            status = "awaiting_approval"
        else:
            status = "blocked"
        plan = MigrationPlan(
            artifact_id=request.artifact_id,
            artifact_sha256=request.artifact_sha256.lower(),
            dry_run=request.dry_run,
            targets=results,
            status=status,
        )
        self._plans[plan.plan_id] = plan
        self._persist()
        return plan

    def robot_blueprint(self, request: RobotBlueprintRequest) -> RobotBlueprint:
        devices = [self._inventory.get(device_id) for device_id in request.inventory_device_ids]
        if any(device is None for device in devices):
            raise MigrationError("Robot planning accepts enrolled device inventory only.")
        resources: list[HardwareResource] = []
        for device in devices:
            assert device is not None
            resources.extend(resource for resource in device.resources if resource.verified)

        kinds = {resource.kind for resource in resources}
        capabilities = {cap for resource in resources for cap in resource.capabilities}
        missing: list[str] = []
        if not ({"cpu", "gpu", "jetson"} & kinds):
            missing.append("compute_controller")
        if "camera" not in kinds and "camera" not in capabilities:
            missing.append("camera_or_vision_sensor")
        if not ({"motor", "motor_controller"} & kinds or {"motor", "motor_controller"} & capabilities):
            missing.append("motor_and_motor_controller")
        if "emergency_stop" not in capabilities:
            missing.append("verified_emergency_stop")
        if "operator_takeover" not in capabilities:
            missing.append("operator_takeover")
        return RobotBlueprint(
            objective=request.objective,
            resources_found=resources,
            missing_capabilities=sorted(set(missing)),
            required_safety_controls=request.required_safety_controls,
            status="proposal_only",
            physical_actuation_enabled=False,
        )

    @staticmethod
    def verify_artifact(path: str | Path, expected_sha256: str) -> bool:
        artifact = Path(path)
        if not artifact.is_file() or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
            return False
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return digest.lower() == expected_sha256.lower()
