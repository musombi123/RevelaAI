"""Native FastAPI port of the administrator-only Sci-Core dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.admin_auth import require_platform_admin
from revelai.sci_core.storage import collection

router = APIRouter(prefix="/api/sci", tags=["Sci-Core"])


def _dashboard(authorization: str):
    _actor, error = require_platform_admin(authorization)
    if error:
        return error
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return {
            "threats_last_24h": collection("threats").count_documents(
                {"timestamp": {"$gte": since.isoformat()}}
            ),
            "shields_active": 1,
            "disasters_handled": collection("disasters").count_documents({}),
            "research_count": collection("research").count_documents({}),
            "defensive_only": True,
        }
    except Exception:
        return {
            "status": "degraded",
            "error": "Sci-Core dashboard unavailable",
        }


@router.get("/shield/dashboard")
async def dashboard(request: Request):
    result = await run_in_threadpool(
        _dashboard, request.headers.get("Authorization", "")
    )
    if isinstance(result, dict) and result.get("status") == "degraded":
        from fastapi.responses import JSONResponse
        return JSONResponse(result, status_code=503)
    return result



def _authorized(request: Request):
    return require_platform_admin(request.headers.get("Authorization", ""))


def _research_sync(payload: dict):
    _actor, error = require_platform_admin(payload.pop("_authorization", ""))
    if error:
        return error
    query = str(payload.get("query") or "").strip()
    topic = str(payload.get("topic") or "general").strip()[:80]
    if not query or len(query) > 500:
        return JSONResponse(
            {"error": "query must be 1–500 characters"},
            status_code=400,
        )
    from revelai.sci_core.research_engine import run_research
    try:
        return run_research(query, topic)
    except Exception as exc:
        if getattr(exc, "code", None) == 403:
            return JSONResponse(
                {"error": "RevelaAI Sci-Core is defensive & civilian research only"},
                status_code=403,
            )
        return JSONResponse(
            {"error": "Research request could not be completed"},
            status_code=503,
        )


@router.post("/research")
async def research(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["_authorization"] = request.headers.get("Authorization", "")
    return await run_in_threadpool(_research_sync, payload)


def _shield_status():
    from revelai.sci_core.defensive_shield import firewall_recommendations
    try:
        counts = {
            name: collection(name).count_documents({})
            for name in ("threats", "shields", "disasters", "research")
        }
        return {
            "status": "shield_active",
            "defensive_only": True,
            "counts": counts,
            "firewall_recommendations": firewall_recommendations(),
        }
    except Exception:
        return JSONResponse(
            {"status": "degraded", "error": "MongoDB shield status unavailable"},
            status_code=503,
        )


@router.get("/shield/status")
async def shield_status(request: Request):
    _actor, error = _authorized(request)
    if error:
        return error
    return await run_in_threadpool(_shield_status)


def _shield_scan():
    from revelai.sci_core.defensive_shield import run_scan
    try:
        return run_scan()
    except Exception:
        return JSONResponse(
            {
                "status": "degraded",
                "error": "Scan incomplete; inspect service logs and MongoDB configuration",
            },
            status_code=503,
        )


@router.post("/shield/scan")
async def shield_scan(request: Request):
    _actor, error = _authorized(request)
    if error:
        return error
    return await run_in_threadpool(_shield_scan)


def _simulate_disaster(payload: dict):
    from revelai.sci_core.disaster_manager import simulate
    try:
        return simulate(str(payload.get("type") or ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse(
            {"error": "Disaster simulation could not be persisted"},
            status_code=503,
        )


@router.post("/disaster/simulate")
async def disaster_simulate(request: Request):
    _actor, error = _authorized(request)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run_in_threadpool(_simulate_disaster, payload)


def _prototype(payload: dict):
    from revelai.sci_core.hardware_lab import build_prototype
    domain = str(payload.get("domain") or "").lower()
    spec = str(payload.get("spec") or "").strip()
    if domain not in {"software", "hardware", "electronics"}:
        return JSONResponse(
            {"error": "domain must be software, hardware, or electronics"},
            status_code=400,
        )
    if not spec or len(spec) > 800:
        return JSONResponse(
            {"error": "spec must be 1–800 characters"},
            status_code=400,
        )
    try:
        return JSONResponse(build_prototype(domain, spec), status_code=201)
    except Exception as exc:
        if getattr(exc, "code", None) == 403:
            return JSONResponse(
                {"error": "RevelaAI Sci-Core is defensive & civilian research only"},
                status_code=403,
            )
        return JSONResponse(
            {"error": "Prototype generation or audit storage failed"},
            status_code=503,
        )


@router.post("/lab/prototype")
async def prototype(request: Request):
    _actor, error = _authorized(request)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run_in_threadpool(_prototype, payload)


def _request_client_ip(request: Request) -> str | None:
    from revelai.sci_core.ip_guard import client_ip_from_headers
    peer = request.client.host if request.client else None
    return client_ip_from_headers(request.headers, peer)


def _ip_guard_snapshot(request: Request) -> dict:
    from revelai.sci_core.ip_guard import (
        IPGuardStoreUnavailable,
        ensure_indexes,
        list_active_blocks,
        list_recent_auth_failures,
        list_recent_events,
        protection_status,
    )

    state = protection_status()
    payload = {
        **state,
        "client_ip": _request_client_ip(request),
        "active_blocks": [],
        "recent_events": [],
        "recent_auth_failures": [],
        "defensive_only": True,
    }
    if not state.get("persistent"):
        return payload
    try:
        ensure_indexes()
        payload["active_blocks"] = list_active_blocks(100)
        payload["recent_events"] = list_recent_events(50)
        payload["recent_auth_failures"] = list_recent_auth_failures(50)
        payload["active_block_count"] = len(payload["active_blocks"])
        return payload
    except IPGuardStoreUnavailable as exc:
        payload.update({
            "status": "degraded",
            "persistent": False,
            "error": str(exc),
        })
        return payload


@router.get("/ip-guard/status")
async def ip_guard_status(request: Request):
    _actor, error = _authorized(request)
    if error:
        return error
    return await run_in_threadpool(_ip_guard_snapshot, request)


def _manual_block(payload: dict, actor: str, current_ip: str | None):
    from revelai.sci_core.ip_guard import IPGuardStoreUnavailable, block_ip

    if payload.get("confirm") is not True:
        return JSONResponse(
            {"error": "Explicit confirmation is required before blocking an IP."},
            status_code=400,
        )
    if not current_ip:
        return JSONResponse(
            {
                "error": "The administrator's public client IP could not be verified. Configure the trusted Render proxy header before creating an IP block.",
                "blocked": False,
            },
            status_code=503,
        )
    try:
        result = block_ip(
            payload.get("ip"),
            actor=actor,
            reason=payload.get("reason", ""),
            duration_minutes=payload.get("duration_minutes", 60),
            source="manual",
            current_ip=current_ip,
        )
        return JSONResponse(
            {
                **result,
                "enforcement": "application_edge",
                "message": "The IP is now blocked by the RevelaAI ASGI application edge.",
                "host_firewall_changed": False,
            },
            status_code=201,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except IPGuardStoreUnavailable as exc:
        return JSONResponse(
            {"error": str(exc), "status": "degraded", "blocked": False},
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {"error": "Persistent IP block storage is unavailable; no block was confirmed.", "status": "degraded", "blocked": False},
            status_code=503,
        )


@router.post("/ip-guard/block")
async def ip_guard_block(request: Request):
    actor, error = _authorized(request)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run_in_threadpool(
        _manual_block, payload, actor or "unknown", _request_client_ip(request)
    )


def _manual_unblock(payload: dict, actor: str):
    from revelai.sci_core.ip_guard import IPGuardStoreUnavailable, unblock_ip

    reason = str(payload.get("reason") or "Administrator released the block").strip()
    try:
        if len(reason) < 8 or len(reason) > 300:
            raise ValueError("Enter an unblock reason between 8 and 300 characters.")
        result = unblock_ip(
            payload.get("ip"),
            actor=actor,
            reason=reason,
        )
        return {
            **result,
            "enforcement": "application_edge",
            "message": "The active RevelaAI application-edge block has been released.",
            "host_firewall_changed": False,
        }
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except IPGuardStoreUnavailable as exc:
        return JSONResponse(
            {"error": str(exc), "status": "degraded"},
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {"error": "Persistent IP block storage is unavailable; unblock status could not be verified.", "status": "degraded"},
            status_code=503,
        )


@router.post("/ip-guard/unblock")
async def ip_guard_unblock(request: Request):
    actor, error = _authorized(request)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run_in_threadpool(_manual_unblock, payload, actor or "unknown")
