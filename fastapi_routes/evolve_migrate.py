"""Authenticated FastAPI routes for USECT-EVOLVE and USECT-MIGRATE."""
from __future__ import annotations

import hmac
import logging
import os
import re
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.models import (
    EvolutionDecisionInput, EvolutionEvaluationInput, EvolutionRequest, ToolInventionRequest, ToolMindReviewRequest,
)
from core_evolve.learning import (
    EvolutionLearningUnavailable, ensure_available, learning_snapshot, recent_proposals,
    record_human_decision, record_tool_event,
)
from core_migrate.models import DeviceEnrollment, MigrationPlanRequest, RobotBlueprintRequest
from core_migrate.service import MigrationError, MigrationService
from core_billing.licensing import LicenseError
from core_uncopyable.license_lock import require_entitlement
from ai.core_mesh import core_mesh_operator_allowed
from fastapi_routes.auth import resolve_revelacode_user

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


async def _require_factory_operator(request: Request) -> str:
    """Authenticate with the existing RevelaCode session and Core Mesh operator allowlist."""
    authorization = request.headers.get("Authorization", "")
    try:
        user_id, auth_error = await run_in_threadpool(
            resolve_revelacode_user, authorization
        )
    except Exception as exc:
        logger.warning("Factory operator authentication could not be verified | error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Core Mesh identity verification is unavailable.") from exc
    if auth_error is not None or not user_id:
        status = getattr(auth_error, "status_code", 401) if auth_error is not None else 401
        raise HTTPException(
            status_code=status if isinstance(status, int) and 400 <= status <= 599 else 401,
            detail="A valid RevelaCode session is required for Evolver administration.",
        )
    configured = (
        os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
        or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    ).strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Configure CORE_MESH_ADMIN_USER_IDS server-side before enabling Evolver administration.",
        )
    if not core_mesh_operator_allowed(user_id):
        raise HTTPException(
            status_code=403,
            detail="This account is not allowlisted as a Core Mesh operator.",
        )
    return str(user_id)


def _require_enterprise_license(token: str | None, entitlement: str) -> None:
    try:
        require_entitlement(token or "", entitlement)
    except LicenseError as exc:
        message = str(exc)
        status = 503 if "not configured" in message.lower() or "unavailable" in message.lower() else 402
        raise HTTPException(status_code=status, detail=message) from exc


class FactoryPreflightBlocked(RuntimeError):
    """Meta-Engineer or Sci Defender rejected the current factory preflight."""


def _factory_preflight() -> dict[str, object]:
    """Run read-only Meta-Engineer architecture and Sci Defender checks."""
    from meta_engineer.introspector import scan_architecture
    from revelai.sci_core.defensive_shield import scan_codebase

    try:
        architecture = scan_architecture()
    except Exception as exc:
        raise FactoryPreflightBlocked("Meta-Engineer architecture preflight failed.") from exc
    if not isinstance(architecture, dict) or architecture.get("read_only") is not True:
        raise FactoryPreflightBlocked("Meta-Engineer architecture preflight is unavailable.")
    dependencies = architecture.get("dependencies", {})
    relevant = (
        "core_evolve/engine.py",
        "core_evolve/learning.py",
        "fastapi_routes/evolve_migrate.py",
    )
    parse_errors = []
    for path in relevant:
        imports = dependencies.get(path, []) if isinstance(dependencies, dict) else []
        if any(str(item).startswith("parse-error:") for item in imports):
            parse_errors.append(path)
    if parse_errors:
        raise FactoryPreflightBlocked(
            "Meta-Engineer found syntax/parse failures in factory modules: " + ", ".join(parse_errors)
        )

    try:
        findings = scan_codebase()
    except Exception as exc:
        raise FactoryPreflightBlocked("Sci Defender security preflight failed.") from exc
    if not isinstance(findings, list):
        raise FactoryPreflightBlocked("Sci Defender did not return a valid security scan.")
    blocking = [
        item for item in findings
        if isinstance(item, dict) and str(item.get("severity", "")).lower() in {"critical", "high"}
    ]
    if blocking:
        categories = sorted({str(item.get("type") or "security_finding") for item in blocking})
        raise FactoryPreflightBlocked(
            "Sci Defender blocked factory work because critical/high findings remain: "
            + ", ".join(categories)
        )
    return {
        "meta_engineer": {
            "status": "passed",
            "read_only": True,
            "scanned_module_count": sum(
                len(paths) for paths in architecture.get("structure", {}).values()
                if isinstance(paths, list)
            ),
        },
        "sci_defender": {
            "status": "passed",
            "findings_reviewed": len(findings),
            "blocking_findings": 0,
            "scope": "RevelaAI Python codebase; Genesis separately screens candidate source",
        },
    }

@router.get("/evolve/capabilities")
async def get_factory_capabilities(
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    from core_evolve.capabilities import capability_registry
    return capability_registry()


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
            "capabilities": {
                "metric_evolution": "blocked",
                "brain_os_learning": "blocked",
                "genesis_invention": "dependency_not_probed",
                "signed_tool_publication": "dependency_not_probed",
                "production_self_modification": "disabled",
                "physical_actuation": "disabled",
            },
            "tool_invention_dependency": "Genesis/Core-One",
        }
    return {
        "status": "learning_store_ready",
        "organ": "USECT-EVOLVE",
        "mode": "evidence-driven-proposals",
        "learning_store": "mongodb",
        "durable_learning": True,
        "capabilities": {
            "metric_evolution": "available",
            "brain_os_learning": "available_when_category_is_declared",
            "genesis_invention": "requires_live_core_one",
            "signed_tool_publication": "requires_live_core_one_guardian_and_sandbox",
            "production_self_modification": "disabled",
            "physical_actuation": "disabled",
        },
        "tool_invention_dependency": "Genesis/Core-One",
        "tool_activation_control": "Genesis signed registry",
    }


@router.post("/evolve/proposals", status_code=201)
async def create_evolution_proposal(
    body: EvolutionRequest,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        proposal = _evolver().propose(body)
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json"), "deployment_authorized": False}


@router.get("/evolve/proposals")
async def list_evolution_proposals(
    request: Request,
    system_id: str,
    limit: int = 25,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        proposals = recent_proposals(system_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "proposals": proposals,
        "source": "mongodb",
        "original_objectives_included": False,
        "production_actions_authorized": False,
    }


@router.post("/evolve/proposals/{proposal_id}/decision")
async def decide_evolution_proposal(
    proposal_id: str,
    body: EvolutionDecisionInput,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    reviewer_id = await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        proposal = _evolver().get(proposal_id)
        result = record_human_decision(
            proposal_id,
            proposal.system_id,
            body.decision,
            body.rationale,
            reviewer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evolution proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "proposal": {
            "proposal_id": proposal.proposal_id,
            "system_id": proposal.system_id,
            "generation": proposal.generation,
        },
        "decision": result,
    }


@router.post("/evolve/proposals/{proposal_id}/children", status_code=201)
async def recursively_improve_evolver(
    proposal_id: str,
    body: EvolutionRequest,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        proposal = _evolver().propose(body, parent_proposal_id=proposal_id)
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parent proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json"), "deployment_authorized": False}


@router.post("/evolve/proposals/{proposal_id}/evaluate")
async def evaluate_evolution_proposal(
    proposal_id: str,
    body: EvolutionEvaluationInput,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        report = _evolver().evaluate(proposal_id, body)
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"evaluation": report.model_dump(mode="json")}


def _active_tool_baseline(records: list[dict], tool_name: str) -> dict[str, object] | None:
    """Return the exact verified active Genesis artifact used as the evolution baseline."""
    for item in records:
        if not isinstance(item, dict) or item.get("active") is not True:
            continue
        manifest = item.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("name") != tool_name:
            continue
        artifact_hash = item.get("artifact_hash")
        version = item.get("version")
        risk_tier = item.get("risk_tier")
        if (
            not isinstance(artifact_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_hash)
            or not isinstance(version, str)
            or not version
            or type(risk_tier) is not int
            or risk_tier not in {0, 1, 2}
        ):
            continue
        return {
            "tool_name": tool_name,
            "version": version,
            "artifact_hash": artifact_hash,
            "risk_tier": risk_tier,
        }
    return None



@router.post("/evolve/proposals/{proposal_id}/mind-review", status_code=202)
async def review_evolution_with_infinite_mind(
    proposal_id: str,
    body: ToolMindReviewRequest,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    """Ask the existing Infinite Mind core to review an Evolver proposal."""
    reviewer_id = await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        ensure_available()
        proposal = _evolver().get(proposal_id)
        if proposal.system_id not in {body.tool_name, "tool." + body.tool_name}:
            raise HTTPException(
                status_code=409,
                detail="The Evolver proposal is not scoped to the named tool.",
            )
        from core_evolve.learning import objective_matches_proposal
        if not objective_matches_proposal(proposal, body.objective):
            raise HTTPException(
                status_code=409,
                detail="The supplied objective does not match the immutable proposal fingerprint.",
            )
        preflight = await run_in_threadpool(_factory_preflight)
        from ai.tool_registry import list_active_tools
        active_tools = await run_in_threadpool(list_active_tools)
        baseline = _active_tool_baseline(active_tools, body.tool_name)
        if baseline is None:
            raise HTTPException(
                status_code=409,
                detail="Infinite Mind review requires a verified active signed Genesis tool as its baseline.",
            )
        from ai.core_mesh import propose_mind_evolution

        mind_proposal = await run_in_threadpool(
            propose_mind_evolution,
            body.objective,
            body.tool_name,
        )
        raw_mind_id = mind_proposal.get("id") or mind_proposal.get("proposal_id")
        mind_proposal_id = (
            raw_mind_id
            if isinstance(raw_mind_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", raw_mind_id)
            else None
        )
        try:
            record_tool_event(
                "tool_improvement_proposed",
                demand=body.objective,
                tool_name=body.tool_name,
                status=str(mind_proposal.get("status") or "await_merge"),
                artifact_hash=str(baseline["artifact_hash"]),
                version=str(baseline["version"]),
                risk_tier=baseline["risk_tier"],
                evolver_proposal_id=proposal_id,
                mind_proposal_id=mind_proposal_id,
            )
        except EvolutionLearningUnavailable:
            logger.exception("Infinite Mind created an improvement proposal but MongoDB could not record the link")
            return JSONResponse(
                {
                    "status": "partial_success",
                    "evolver_proposal_id": proposal_id,
                    "infinite_mind": mind_proposal,
                    "baseline": baseline,
                    "learning_ledger": "write_failed",
                    "warning": "Infinite Mind created its proposal, but the association event was not written to MongoDB. Verify the Mind proposal before retrying.",
                    "candidate_generation": "proposal_only",
                    "production_changes": False,
                    "automatic_merge": False,
                    "preflight": preflight,
                },
                status_code=202,
            )
    except FactoryPreflightBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evolution proposal not found.") from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Infinite Mind evolution review failed | error_type=%s", type(exc).__name__)
        status = getattr(exc, "status_code", 502)
        raise HTTPException(
            status_code=status if isinstance(status, int) and 400 <= status <= 599 else 502,
            detail="Infinite Mind could not review the evolution proposal. Check Core-Two availability and retry.",
        ) from exc
    return {
        "evolver_proposal_id": proposal_id,
        "infinite_mind": mind_proposal,
        "baseline": baseline,
        "learning_ledger": "mongodb",
        "candidate_generation": "proposal_only",
        "human_approval_required": True,
        "automatic_merge": False,
        "production_changes": False,
        "preflight": preflight,
    }


@router.get("/evolve/learning/{system_id}")
async def get_evolution_learning(
    system_id: str,
    request: Request,
    brain_category: str | None = None,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        snapshot = learning_snapshot(system_id, brain_category=brain_category)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvolutionLearningUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"learning": snapshot}


@router.post("/evolve/tools", status_code=202)
async def propose_evolved_tool(
    body: ToolInventionRequest,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    """Create a Genesis invention proposal and persist its audit metadata in MongoDB."""
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        ensure_available()
        preflight = await run_in_threadpool(_factory_preflight)
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
        try:
            record_tool_event(
                "tool_invention_created",
                demand=body.demand,
                tool_name=str(tool_name) if tool_name else None,
                status=str(proposal.get("status") or "await_merge"),
            )
        except EvolutionLearningUnavailable:
            logger.exception("Genesis created an invention but MongoDB could not record the completion event")
            return JSONResponse(
                {
                    "status": "partial_success",
                    "proposal": proposal,
                    "factory": "Genesis",
                    "operation_created": True,
                    "learning_ledger": "write_failed",
                    "warning": "Genesis created the proposal, but its completion event could not be written to MongoDB. Do not resubmit the same invention blindly.",
                    "human_approval_required": True,
                    "automatic_merge": False,
                    "production_deployment": False,
                    "physical_actuation_enabled": False,
                    "preflight": preflight,
                },
                status_code=202,
            )
    except FactoryPreflightBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        "preflight": preflight,
    }


@router.post("/evolve/tools/{name}/publish", status_code=201)
async def sandbox_and_publish_evolved_tool(
    name: str,
    request: Request,
    x_revela_license: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict:
    """Run Genesis Guardian/sandbox and publish a signed, immutable candidate."""
    await _require_factory_operator(request)
    _require_enterprise_license(x_revela_license, "evolve")
    try:
        ensure_available()
        preflight = await run_in_threadpool(_factory_preflight)
        from ai.tool_registry import get_signed_tool_version, publish_signed_tool

        published = await run_in_threadpool(publish_signed_tool, name)
        artifact = published.get("artifact", {}) if isinstance(published, dict) else {}
        manifest = artifact.get("manifest", {}) if isinstance(artifact, dict) else {}
        evidence = artifact.get("sandbox_evidence", {}) if isinstance(artifact, dict) else {}
        artifact_hash = artifact.get("artifact_hash") if isinstance(artifact, dict) else None
        version = artifact.get("version") if isinstance(artifact, dict) else None
        if (
            published.get("status") != "signed"
            or not isinstance(version, str)
            or not isinstance(artifact_hash, str)
            or not isinstance(manifest, dict)
            or not isinstance(evidence, dict)
            or evidence.get("passed") is not True
        ):
            raise RuntimeError("Genesis publication response did not contain verified sandbox evidence.")
        # Fetch the immutable version again through the existing verifier; do not
        # trust a publication response merely because the service returned HTTP 201.
        verified = await run_in_threadpool(
            get_signed_tool_version, name, version, artifact_hash
        )
        manifest = verified["manifest"]
        evidence = verified["sandbox_evidence"]
        risk_tier = manifest.get("risk_tier")
        sandbox_passed = evidence.get("passed")
        try:
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
        except EvolutionLearningUnavailable:
            logger.exception("Genesis published a signed tool but MongoDB could not record the publication event")
            return JSONResponse(
                {
                    "status": "partial_success",
                    "publication": published,
                    "publication_completed": True,
                    "learning_ledger": "write_failed",
                    "warning": "Genesis signed and published the artifact, but MongoDB did not record the completion event. Verify the signed registry before retrying.",
                    "execution_performed": False,
                    "production_deployment": False,
                    "preflight": preflight,
                },
                status_code=201,
            )
    except FactoryPreflightBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        "preflight": preflight,
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
