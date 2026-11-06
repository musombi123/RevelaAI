"""Authenticated FastAPI routes for USECT-EVOLVE and USECT-MIGRATE."""
from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.models import EvolutionEvaluationInput, EvolutionRequest, ToolInventionRequest
from core_evolve.learning import (
    EvolutionLearningUnavailable, ensure_available, learning_snapshot, record_tool_event,
)
from core_migrate.models import DeviceEnrollment, MigrationPlanRequest, RobotBlueprintRequest
from core_migrate.service import MigrationError, MigrationService
from core_billing.licensing import LicenseError
from core_uncopyable.license_lock import require_entitlement

logger = logging.getLogger("revelaai.evolver")

router = APIRouter(prefix="/api/usect", tags=["USECT-EVOLVE-MIGRATE"])


@lru_cache(maxsize=1)
def _evolver() -> EvolutionEngine:
    return EvolutionEngine()


@lru_cache(maxsize=1)
def _migrator() -> MigrationService:
    return MigrationService()


def _require_organ_token(token: str | None) -> None:
    expected = os.getenv("REVELA_ORGAN_ADMIN_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="Organ administration is not configured.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid organ administrator token required.")


def _require_enterprise_license(token: str | None, entitlement: str) -> None:
    try:
        require_entitlement(token or "", entitlement)
    except LicenseError as exc:
        message = str(exc)
        status = 503 if "not configured" in message.lower() or "unavailable" in message.lower() else 402
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/evolve/health")
async def evolve_health() -> dict[str, object]:
    try:
        ensure_available()
    except EvolutionLearningUnavailable:
        return {
            "status": "blocked",
            "organ": "USECT-EVOLVE",
            "mode": "evidence-driven-proposals",
            "learning_store": "unavailable",
            "durable_learning": False,
            "tool_invention_dependency": "Genesis/Core-One",
        }
    return {
        "status": "ready_for_metric_evolution",
        "organ": "USECT-EVOLVE",
        "mode": "evidence-driven-proposals",
        "learning_store": "mongodb",
        "durable_learning": True,
        "tool_invention_dependency": "Genesis/Core-One",
        "tool_activation_control": "Genesis signed registry",
    }


@router.post("/evolve/proposals", status_code=201)
async def create_evolution_proposal(
    body: EvolutionRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
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
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
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
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        report = _evolver().evaluate(proposal_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"evaluation": report.model_dump(mode="json")}


@router.get("/evolve/learning/{system_id}")
async def get_evolution_learning(
    system_id: str,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        snapshot = learning_snapshot(system_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"learning": snapshot}


@router.post("/evolve/tools", status_code=202)
async def propose_evolved_tool(
    body: ToolInventionRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    """Create a Genesis invention proposal and persist its audit metadata in MongoDB."""
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        ensure_available()
        record_tool_event(
            "tool_invention_requested",
            demand=body.demand,
            status="requested",
        )
        from ai.core_mesh import propose_genesis_invention

        proposal = await run_in_threadpool(
            propose_genesis_invention,
            body.demand,
            body.country,
            body.language,
        )
        tool_name = proposal.get("name") or proposal.get("tool_name")
        record_tool_event(
            "tool_invention_created",
            demand=body.demand,
            tool_name=str(tool_name) if tool_name else None,
            status=str(proposal.get("status") or "await_merge"),
        )
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        # Do not leak upstream tokens, internal URLs, or raw exception contents.
        logger.warning("Genesis invention request failed | error_type=%s", type(exc).__name__)
        status = getattr(exc, "status_code", 502)
        raise HTTPException(
            status_code=status if isinstance(status, int) and 400 <= status <= 599 else 502,
            detail="Genesis could not complete the invention proposal. Check the Core-One status and retry.",
        ) from exc
    return {
        "proposal": proposal,
        "factory": "Genesis",
        "learning_ledger": "mongodb",
        "human_approval_required": True,
        "automatic_merge": False,
        "production_deployment": False,
        "physical_actuation_enabled": False,
    }


@router.post("/evolve/tools/{name}/publish", status_code=201)
async def sandbox_and_publish_evolved_tool(
    name: str,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    """Run Genesis Guardian/sandbox and publish a signed, immutable candidate."""
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        ensure_available()
        from ai.tool_registry import publish_signed_tool

        published = await run_in_threadpool(publish_signed_tool, name)
        artifact = published.get("artifact", {}) if isinstance(published, dict) else {}
        manifest = artifact.get("manifest", {}) if isinstance(artifact, dict) else {}
        evidence = artifact.get("sandbox_evidence", {}) if isinstance(artifact, dict) else {}
        artifact_hash = artifact.get("artifact_hash") if isinstance(artifact, dict) else None
        version = artifact.get("version") if isinstance(artifact, dict) else None
        risk_tier = manifest.get("risk_tier") if isinstance(manifest, dict) else None
        sandbox_passed = evidence.get("passed") if isinstance(evidence, dict) else None
        record_tool_event(
            "tool_published",
            demand="",
            tool_name=name,
            status=str(published.get("status") or "signed"),
            artifact_hash=str(artifact_hash) if artifact_hash else None,
            version=str(version) if version else None,
            risk_tier=risk_tier if type(risk_tier) is int else None,
            sandbox_passed=sandbox_passed if isinstance(sandbox_passed, bool) else None,
        )
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        error_code = getattr(exc, "code", "")
        status = getattr(exc, "status_code", 502)
        if error_code:
            raise HTTPException(
                status_code=status if isinstance(status, int) and 400 <= status <= 599 else 502,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Genesis Guardian or sandbox publication failed; no tool was reported as published.",
        ) from exc
    return {
        "publication": published,
        "learning_ledger": "mongodb",
        "execution_performed": False,
        "production_deployment": False,
        "tier_1_and_2_activation_requires_owner_approval": True,
        "tier_2_actions_require_separate_action_approval": True,
    }


@router.get("/migrate/devices")
async def list_enrolled_devices(
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "migrate")
    return {"devices": [device.model_dump(mode="json") for device in _migrator().list_devices()]}


@router.post("/migrate/devices/enroll", status_code=201)
async def enroll_device(
    body: DeviceEnrollment,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "migrate")
    device = _migrator().enroll(body)
    return {"device": device.model_dump(mode="json"), "remote_access_enabled": False}


@router.post("/migrate/plans", status_code=201)
async def create_migration_plan(
    body: MigrationPlanRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "migrate")
    return {"plan": _migrator().plan(body).model_dump(mode="json"), "remote_execution_performed": False}


@router.post("/migrate/robot-blueprints", status_code=201)
async def create_robot_blueprint(
    body: RobotBlueprintRequest,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    _require_organ_token(x_organ_admin_token)
    _require_enterprise_license(x_revela_license, "robot_build")
    try:
        blueprint = _migrator().robot_blueprint(body)
    except MigrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"blueprint": blueprint.model_dump(mode="json"), "physical_actuation_enabled": False}
