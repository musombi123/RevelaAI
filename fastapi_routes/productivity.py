"""RevelaAI productivity tools: global research, Office exports and optional safe execution."""
from __future__ import annotations

import logging
import os
from datetime import datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from fastapi_routes.auth import authenticate_identity
from fastapi_routes.admin_auth import require_platform_admin
from services.revenue_entitlements import check_entitlement
from services.productivity_guard import ProductivitySafetyError, guard_productivity_tool
from services.productivity_service import (
    create_csv, create_powerpoint, create_spreadsheet, create_word_document,
    read_signed_file,
)
from research_global.engine import list_regions, search_global
from services.runtime_config import get_active_text_provider, get_active_text_model
from core_meter.meter import record_usage
from revela_platform.database import SessionLocal, UsageEvent, ProductivityToolControl

router = APIRouter(prefix="/api/productivity", tags=["Productivity"])
LOG = logging.getLogger("revelaai.productivity")

TOOL_CATALOG = [
    {"id":"research_global","label":"Deep Search","description":"Search global scientific, economic, government and news sources across regions and languages.","phase":1,"free":True,"plus":True},
    {"id":"spreadsheet","label":"Spreadsheets","description":"Create real XLSX workbooks with formulas, formatting, tables and CSV exports.","phase":1,"free":True,"plus":True},
    {"id":"word","label":"Word Documents","description":"Generate editable DOCX reports, proposals, letters and other structured documents.","phase":1,"free":True,"plus":True},
    {"id":"powerpoint","label":"PowerPoint","description":"Generate editable PPTX slide decks and PDF previews.","phase":1,"free":True,"plus":True},
    {"id":"sandbox_python","label":"Python Sandbox","description":"Run approved Python workloads in an isolated, no-network container.","phase":1,"free":True,"plus":True},
    {"id":"analytics","label":"Data Analytics","description":"Profile, clean, query and analyze CSV/XLSX/JSON data.","phase":2,"free":False,"plus":True},
    {"id":"accounting","label":"Accounting","description":"Double-entry accounting, financial statements, budgets and reconciliations.","phase":2,"free":False,"plus":True},
    {"id":"publications","label":"Publications","description":"Research writing, verified citations, BibTeX/RIS and manuscript exports.","phase":2,"free":False,"plus":True},
    {"id":"quantum","label":"Quantum Science","description":"Symbolic physics, quantum circuits, state vectors and simulation.","phase":3,"free":False,"plus":True},
    {"id":"robotics","label":"Robotics","description":"Kinematics, control design, URDF and safe robotics engineering.","phase":3,"free":False,"plus":True},
]

FREE_CAPS = {"research_global":5,"spreadsheet":2,"word":1,"powerpoint":1,"sandbox_python":1}
PLUS_CAPS = {"research_global":60,"spreadsheet":40,"word":20,"powerpoint":20,"sandbox_python":10}
PRO_CAPS = {"research_global":250,"spreadsheet":150,"word":80,"powerpoint":80,"sandbox_python":60}


def _identity(request: Request, payload: dict[str, Any] | None = None) -> tuple[str, str]:
    headers = dict(request.headers)
    oid, user_id, error = authenticate_identity(
        request.headers.get("Authorization", ""), headers, payload or {},
    )
    if error:
        raise HTTPException(status_code=401, detail="A valid RevelaCode login is required.")
    return str(oid or ""), str(user_id or "")


def _entitlement(request: Request) -> dict[str, Any]:
    info, _error = check_entitlement(
        request.headers.get("Authorization", ""),
        hub="smart_ai", feature="advanced_ai", timeout_seconds=2.5,
    )
    return info if isinstance(info, dict) else {"allowed": False, "tier": "free"}


def _plan_tier(entitlement: dict[str, Any]) -> str:
    if entitlement.get("allowed") is not True:
        return "free"
    subscription = entitlement.get("subscription")
    plan_code = ""
    if isinstance(subscription, dict):
        plan_code = str(subscription.get("plan_code") or subscription.get("plan") or "").lower()
    plan_code = plan_code or str(entitlement.get("plan_code") or "").lower()
    if "pro" in plan_code or "enterprise" in plan_code:
        return "pro"
    tier = str(entitlement.get("tier") or "").lower()
    return "plus" if tier in {"paid","trial"} or plan_code == "ai_plus" else "free"


def _tool_enabled(tool_id: str) -> bool:
    # A database value set by a platform administrator overrides the default.
    try:
        with SessionLocal() as session:
            row = session.get(ProductivityToolControl, tool_id)
            if row is not None:
                return bool(row.enabled)
    except Exception:
        LOG.exception("Could not read tool control; applying fail-closed state")
        return False
    raw = os.getenv("REVELAAI_TOOL_" + tool_id.upper() + "_ENABLED")
    if raw is not None:
        configured = raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        item = next((x for x in TOOL_CATALOG if x["id"] == tool_id), None)
        configured = bool(item and item.get("phase") == 1)
    if tool_id == "sandbox_python" and not os.getenv("SANDBOX_SERVICE_URL", "").strip():
        return False
    return configured


def _caps(tier: str) -> dict[str, int]:
    return dict(PRO_CAPS if tier == "pro" else PLUS_CAPS if tier == "plus" else FREE_CAPS)


def _usage_today(user_id: str, tool_id: str) -> int:
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    with SessionLocal() as session:
        return int(session.scalar(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.tool_id == tool_id,
                UsageEvent.created_at >= start,
            )
        ) or 0)


def _enforce_limit(user_id: str, tool_id: str, tier: str) -> int:
    if not _tool_enabled(tool_id):
        raise HTTPException(status_code=503, detail="This tool is currently disabled by a platform administrator.")
    limits = _caps(tier)
    limit = int(limits.get(tool_id, 0))
    used = _usage_today(user_id, tool_id)
    if limit <= 0:
        raise HTTPException(status_code=402, detail="This productivity tool is not enabled for your current plan.")
    if used >= limit:
        raise HTTPException(status_code=429, detail={
            "code":"DAILY_TOOL_QUOTA_REACHED",
            "message":f"Your {tier.title()} daily allowance for this tool has been used.",
            "tool":tool_id,"used":used,"daily_limit":limit,
            "upgrade":"Smart AI Plus or Pro increases the daily allowance.",
        })
    return limit


def _record(user_id: str, tool_id: str, country: str, started: float, success: bool) -> None:
    import time
    with SessionLocal() as session:
        record_usage(session,user_id=user_id,tool_id=tool_id,country=country or "KE",
                     latency_ms=(time.monotonic()-started)*1000,success=success)


class ResearchInput(BaseModel):
    query: str = Field(min_length=1,max_length=500)
    locale: str = Field(default="en-KE",max_length=20)
    language: str = Field(default="",max_length=12)
    country: str = Field(default="",max_length=2)
    region: str = Field(default="",max_length=40)
    source_country: str = Field(default="",max_length=2)
    limit: int = Field(default=8,ge=1,le=20)
    conflicting_views: bool = False


class GenerateInput(BaseModel):
    kind: str = Field(pattern="^(spreadsheet|word|powerpoint|csv)$")
    payload: dict[str,Any]


class SandboxInput(BaseModel):
    code: str = Field(min_length=1,max_length=30000)
    files: list[dict[str,str]] = Field(default_factory=list,max_length=10)
    timeout_seconds: int = Field(default=10,ge=1,le=30)


@router.get("/catalog")
async def productivity_catalog(request: Request):
    _, user_id = _identity(request)
    tier = _plan_tier(_entitlement(request))
    limits = _caps(tier)
    return {
        "status":"success","tier":tier,"daily_limits":limits,
        "model":{"provider":get_active_text_provider(),"model":get_active_text_model(),"status":"configured_not_health_checked"},
        "tools":[{**tool,"enabled":_tool_enabled(tool["id"]),
                  "locked":not _tool_enabled(tool["id"]) or (not tool["free"] and tier=="free"),
                  "daily_limit":limits.get(tool["id"],0),
                  "phase_status":"available" if tool["phase"]==1 and _tool_enabled(tool["id"]) else "planned"}
                 for tool in TOOL_CATALOG],
        "regions":list_regions(),
        "safety":{"meta_engineer":"required","sci_defender":"required"},
    }


@router.get("/regions")
async def research_regions():
    return {"regions":list_regions()}


@router.get("/admin/tools")
async def admin_productivity_tools(request: Request):
    actor, error = require_platform_admin(request.headers.get("Authorization", ""))
    if error:
        return error
    with SessionLocal() as session:
        rows = session.execute(select(ProductivityToolControl)).scalars().all()
        saved = {row.tool_id: row for row in rows}
        return {"tools":[{"id":tool["id"],"phase":tool["phase"],
                          "enabled":saved[tool["id"]].enabled if tool["id"] in saved else _tool_enabled(tool["id"]),
                          "updated_by":saved[tool["id"]].updated_by if tool["id"] in saved else None,
                          "updated_at":saved[tool["id"]].updated_at.isoformat() if tool["id"] in saved and saved[tool["id"]].updated_at else None}
                         for tool in TOOL_CATALOG]}


class AdminToolControlInput(BaseModel):
    enabled: bool
    note: str = Field(default="",max_length=500)


@router.patch("/admin/tools/{tool_id}")
async def admin_set_productivity_tool(tool_id: str, body: AdminToolControlInput, request: Request):
    actor, error = require_platform_admin(request.headers.get("Authorization", ""))
    if error:
        return error
    if not any(item["id"] == tool_id for item in TOOL_CATALOG):
        raise HTTPException(status_code=404,detail="Unknown productivity tool.")
    from datetime import datetime, timezone
    with SessionLocal() as session:
        row = session.get(ProductivityToolControl, tool_id)
        if row is None:
            row = ProductivityToolControl(tool_id=tool_id,enabled=body.enabled,updated_by=str(actor),note=body.note)
            session.add(row)
        else:
            row.enabled=body.enabled
            row.updated_by=str(actor)
            row.note=body.note
            row.updated_at=datetime.now(timezone.utc)
        session.commit()
    return {"tool_id":tool_id,"enabled":body.enabled,"updated_by":str(actor)}


@router.post("/research")
async def global_research(body: ResearchInput, request: Request):
    user_oid,user_id=_identity(request,body.model_dump())
    tier=_plan_tier(_entitlement(request))
    _enforce_limit(user_id,"research_global",tier)
    safety=guard_productivity_tool("research_global",body.model_dump())
    import time
    started=time.monotonic()
    try:
        result=search_global(**body.model_dump())
        _record(user_id,"research_global",body.country or "KE",started,True)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc:
        _record(user_id,"research_global",body.country or "KE",started,False)
        LOG.warning("Global research failed | type=%s",type(exc).__name__)
        raise HTTPException(status_code=503,detail="Global research providers are temporarily unavailable.") from exc
    result["safety"]=safety
    result["tier"]=tier
    result["quota_remaining"]=max(0,_caps(tier)["research_global"]-_usage_today(user_id,"research_global"))
    return result


@router.post("/generate")
async def generate_workspace_artifact(body: GenerateInput, request: Request):
    _oid,user_id=_identity(request,{"kind":body.kind})
    tool_id="spreadsheet" if body.kind=="csv" else body.kind
    tier=_plan_tier(_entitlement(request))
    _enforce_limit(user_id,tool_id,tier)
    safety=guard_productivity_tool(tool_id,body.payload)
    import time
    started=time.monotonic()
    try:
        if body.kind=="spreadsheet": result=create_spreadsheet(user_id,body.payload)
        elif body.kind=="word": result=create_word_document(user_id,body.payload)
        elif body.kind=="powerpoint": result=create_powerpoint(user_id,body.payload)
        else: result=create_csv(user_id,body.payload)
        _record(user_id,tool_id,request.headers.get("X-Country","KE"),started,True)
        result["safety"]=safety
        result["tier"]=tier
        result["quota_remaining"]=max(0,_caps(tier)[tool_id]-_usage_today(user_id,tool_id))
        return {"status":"success","artifact":result}
    except ValueError as exc:
        _record(user_id,tool_id,"KE",started,False)
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc:
        _record(user_id,tool_id,"KE",started,False)
        LOG.exception("Artifact generation failed | kind=%s",body.kind)
        raise HTTPException(status_code=500,detail="The requested file could not be generated.") from exc


@router.get("/files/{file_id}")
async def download_productivity_file(file_id: str, expires: int, sig: str):
    try:
        path,meta=read_signed_file(file_id,expires,sig)
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except (FileNotFoundError,ValueError) as exc:
        raise HTTPException(status_code=404,detail="File not found or expired.") from exc
    return FileResponse(path,filename=meta["filename"],media_type=meta["mime_type"])


@router.post("/sandbox")
async def run_sandbox(body: SandboxInput, request: Request):
    _oid,user_id=_identity(request,{"tool":"sandbox_python"})
    tier=_plan_tier(_entitlement(request))
    _enforce_limit(user_id,"sandbox_python",tier)
    payload=body.model_dump()
    safety=guard_productivity_tool("sandbox_python",payload)
    base=os.getenv("SANDBOX_SERVICE_URL","").strip().rstrip("/")
    secret=os.getenv("SANDBOX_SHARED_SECRET","").strip()
    if not base or len(secret.encode("utf-8"))<32:
        raise HTTPException(status_code=503,detail="The isolated execution service has not been provisioned. No code was executed.")
    import hashlib,hmac,json,requests,time
    started=time.monotonic()
    raw=json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    signature=hmac.new(secret.encode("utf-8"),raw,hashlib.sha256).hexdigest()
    try:
        response=requests.post(base+"/v1/execute",data=raw,headers={"Content-Type":"application/json","X-Revela-Sandbox-Signature":signature},timeout=(3,body.timeout_seconds+8),allow_redirects=False,proxies={"http":"","https":""})
        if response.status_code!=200:
            raise RuntimeError("sandbox rejected the job")
        result=response.json()
        _record(user_id,"sandbox_python","KE",started,True)
        return {"status":"success","result":result,"safety":safety,"tier":tier}
    except Exception as exc:
        _record(user_id,"sandbox_python","KE",started,False)
        LOG.warning("Sandbox request failed | type=%s",type(exc).__name__)
        raise HTTPException(status_code=503,detail="The isolated execution service is unavailable. The job was not completed.") from exc
