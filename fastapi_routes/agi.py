"""Native FastAPI routes for AGI manifest, Brain OS and runtime status."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.admin_auth import require_platform_admin
from revelai.core.agi_manifest import get_manifest, get_status_summary
from revelai.core import brain_os
from revelai.sci_core.storage import collection, database

router = APIRouter(prefix="/api/agi", tags=["AGI Manifest", "Brain OS"])


def _persist_manifest() -> dict[str, Any]:
    payload = get_manifest()
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    try:
        db = database()
        if db is None:
            raise RuntimeError("MONGO_URI is not configured")
        db.command("ping")
        db["agi_manifest"].replace_one(
            {"_id": "canonical"},
            {"_id": "canonical", **payload},
            upsert=True,
        )
        return {"persisted": True, "backend": "mongodb", "collection": "agi_manifest"}
    except Exception:
        try:
            col = collection("agi_manifest")
            col.insert_one({"kind": "manifest_snapshot", **payload})
            return {
                "persisted": True,
                "backend": getattr(col, "backend", "local_cache"),
                "collection": "agi_manifest",
            }
        except Exception:
            return {"persisted": False, "backend": "unavailable", "collection": "agi_manifest"}


def _manifest():
    payload = get_manifest()
    payload["persistence"] = _persist_manifest()
    return JSONResponse(payload, status_code=200)


def _status():
    result = get_status_summary()
    result["database"] = {
        "configured": False,
        "reachable": False,
        "collection": "agi_manifest",
        "persisted": False,
    }
    try:
        db = database()
        if db is not None:
            db.command("ping")
            db["agi_manifest"].replace_one(
                {"_id": "canonical"},
                {
                    "_id": "canonical",
                    **get_manifest(),
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                },
                upsert=True,
            )
            result["database"] = {
                "configured": True,
                "reachable": True,
                "collection": "agi_manifest",
                "persisted": True,
            }
    except Exception:
        result["database"] = {
            "configured": bool(os.getenv("MONGO_URI")),
            "reachable": False,
            "collection": "agi_manifest",
            "persisted": False,
        }
    result["status"] = (
        "ok"
        if result.get("all_modules_present") and result["database"]["reachable"]
        else "degraded"
    )
    return JSONResponse(result, status_code=200)


def _admin(request: Request):
    return require_platform_admin(request.headers.get("Authorization", ""))


async def _payload(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/manifest")
async def manifest():
    return await run_in_threadpool(_manifest)


@router.get("/status")
async def status():
    return await run_in_threadpool(_status)


@router.get("/brain-os/status")
async def brain_os_status(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    return {
        "status": "ok",
        "brain_os": brain_os.capability_inventory(),
        "outcomes": brain_os.outcome_summary(),
        "engineering": brain_os.engineering_guardrails(),
        "actor": actor,
    }


def _record_outcome(actor: str, payload: dict[str, Any]):
    try:
        result = brain_os.record_outcome(
            payload.get("category"),
            payload.get("success"),
            payload.get("latency_ms"),
            payload.get("feedback_label"),
            "admin_api",
            task_success=payload.get("task_success"),
            provider=payload.get("provider"),
            route=payload.get("route"),
            outcome_source="admin_review",
        )
        return JSONResponse(result, status_code=201)
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "code": "invalid_outcome", "message": str(exc)},
            status_code=400,
        )
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "outcome_storage_unavailable"},
            status_code=503,
        )


@router.post("/brain-os/outcomes")
async def brain_os_outcomes(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    return await run_in_threadpool(_record_outcome, actor, await _payload(request))


def _evaluate_routing(payload: dict[str, Any], actor: str):
    try:
        result = brain_os.evaluate_routing_shadow(
            payload.get("category"),
            payload.get("baseline_provider"),
            payload.get("candidate_provider"),
        )
        result["actor"] = actor
        return result
    except ValueError as exc:
        return JSONResponse(
            {
                "status": "error",
                "code": "invalid_routing_evaluation",
                "message": str(exc),
            },
            status_code=400,
        )
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "routing_evaluation_unavailable"},
            status_code=503,
        )


@router.post("/brain-os/routing/shadow-evaluate")
async def brain_os_routing_shadow_evaluate(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    return await run_in_threadpool(
        _evaluate_routing, await _payload(request), actor
    )


@router.get("/brain-os/heal/actions")
async def brain_os_heal_actions(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    result = await run_in_threadpool(brain_os.recovery_action_catalog)
    result["actor"] = actor
    return result


def _simulate_recovery(payload: dict[str, Any], actor: str):
    try:
        result = brain_os.simulate_recovery_action(
            payload.get("action_id"),
            payload.get("incident_id"),
            payload.get("evidence"),
        )
        result["actor"] = actor
        return result
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "code": "invalid_recovery_plan", "message": str(exc)},
            status_code=400,
        )
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "recovery_audit_unavailable"},
            status_code=503,
        )


@router.post("/brain-os/heal/actions/simulate")
async def brain_os_heal_actions_simulate(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    return await run_in_threadpool(
        _simulate_recovery, await _payload(request), actor
    )


@router.post("/brain-os/heal/diagnose")
async def brain_os_heal_diagnose(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    try:
        result = await run_in_threadpool(brain_os.diagnose_and_recover)
        result["actor"] = actor
        return result
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "diagnostics_failed"},
            status_code=503,
        )


@router.get("/brain-os/engineering/guardrails")
async def brain_os_engineering_guardrails(request: Request):
    actor, error = _admin(request)
    if error:
        return error
    result = brain_os.engineering_guardrails()
    result["actor"] = actor
    return result
