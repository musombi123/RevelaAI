"""Authenticated FastAPI routes for USECT-EVOLVE and USECT-MIGRATE."""
from __future__ import annotations

import hmac
import os
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException

from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.models import EvolutionEvaluationInput, EvolutionRequest
from core_migrate.models import DeviceEnrollment, MigrationPlanRequest, RobotBlueprintRequest
from core_migrate.service import MigrationError, MigrationService

router = APIRouter(prefix="/api/usect", tags=["USECT-EVOLVE-MIGRATE"])


@lru_cache(maxsize=1)
def _evolver() -> EvolutionEngine:
    return EvolutionEngine()


@lru_cache(maxsize=1)
def _migrator() -> MigrationService:
    return MigrationService()


def _require_organ_token(token: str | None) -> None:
    expected = os.getenv("REVELA_ORGAN_ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Organ administration is not configured.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid organ administrator token required.")


@router.get("/evolve/health")
async def evolve_health() -> dict[str, str]:
    return {"status": "ok", "organ": "USECT-EVOLVE", "mode": "proposal-and-evidence-only"}


@router.post("/evolve/proposals", status_code=201)
async def create_evolution_proposal(
    body: EvolutionRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    try:
        proposal = _evolver().propose(body)
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json"), "deployment_authorized": False}


@router.post("/evolve/proposals/{proposal_id}/children", status_code=201)
async def recursively_improve_evolver(
    proposal_id: str,
    body: EvolutionRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    try:
        proposal = _evolver().propose(body, parent_proposal_id=proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parent proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json"), "deployment_authorized": False}


@router.post("/evolve/proposals/{proposal_id}/evaluate")
async def evaluate_evolution_proposal(
    proposal_id: str,
    body: EvolutionEvaluationInput,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    try:
        report = _evolver().evaluate(proposal_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"evaluation": report.model_dump(mode="json")}


@router.get("/migrate/devices")
async def list_enrolled_devices(
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    return {"devices": [device.model_dump(mode="json") for device in _migrator().list_devices()]}


@router.post("/migrate/devices/enroll", status_code=201)
async def enroll_device(
    body: DeviceEnrollment,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    device = _migrator().enroll(body)
    return {"device": device.model_dump(mode="json"), "remote_access_enabled": False}


@router.post("/migrate/plans", status_code=201)
async def create_migration_plan(
    body: MigrationPlanRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    return {"plan": _migrator().plan(body).model_dump(mode="json"), "remote_execution_performed": False}


@router.post("/migrate/robot-blueprints", status_code=201)
async def create_robot_blueprint(
    body: RobotBlueprintRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    try:
        blueprint = _migrator().robot_blueprint(body)
    except MigrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"blueprint": blueprint.model_dump(mode="json"), "physical_actuation_enabled": False}
