"""Native FastAPI routes for Meta-Engineer health and review-gated workflows."""
from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.admin_auth import require_platform_admin
from meta_engineer.generator import generate_feature
from meta_engineer.fieldkit_adapter import FieldKitFindingError, prepare_review_record
from meta_engineer.introspector import scan_architecture
from meta_engineer.integrator import audit, db, get_idea, save_idea, update_idea
from meta_engineer.pruner import audit_unused
from meta_engineer.sandbox_tester import test_feature

router = APIRouter(prefix="/api/meta-engineer", tags=["Meta-Engineer"])
logger = logging.getLogger("revelaai.fastapi.meta_engineer")


def _authorized(headers):
    authorization = next(
        (str(value) for key, value in headers.items() if str(key).casefold() == "authorization"),
        "",
    )
    return require_platform_admin(authorization)


def _health():
    pytest_available = importlib.util.find_spec("pytest") is not None
    psutil_available = importlib.util.find_spec("psutil") is not None
    storage = "not_configured"
    if db is not None:
        try:
            db.command("ping")
            storage = "connected"
        except Exception:
            storage = "unreachable"

    checks = {
        "proposal_generator": "ready",
        "sandbox_pytest": "available" if pytest_available else "missing",
        "sandbox_memory_monitor": "available" if psutil_available else "missing",
        "audit_storage": storage,
    }
    ready = pytest_available and psutil_available and storage == "connected"
    return {
        "status": "ok" if ready else "degraded",
        "module": "meta-engineer",
        "mode": "target-aware-proposal-builder",
        "checks": checks,
        "candidate_execution": False,
        "auto_deploy": False,
        "auto_delete": False,
    }


def _scan():
    try:
        result = scan_architecture()
        module_count = sum(len(paths) for paths in result.get("structure", {}).values())
        scanned_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "ok",
            "scanned_at": scanned_at,
            "module_count": module_count,
            "free_slots": result.get("free_slots", []),
            "architecture": result,
            "metrics": {
                "last_scan": scanned_at,
                "module_count": module_count,
                "free_slots": len(result.get("free_slots", [])),
            },
            "read_only": True,
        }
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "architecture_scan_failed"},
            status_code=503,
        )


def _propose(actor: str, payload: dict[str, Any]):
    spec = " ".join(str(payload.get("spec") or "").split())
    target = str(payload.get("target") or "fullstack").strip().lower()
    if target not in {"backend", "frontend", "database", "fullstack"}:
        return JSONResponse(
            {"status": "error", "code": "invalid_target"}, status_code=400
        )
    requested_id = str(payload.get("userId") or "").strip()
    if requested_id and requested_id != actor:
        return JSONResponse(
            {"status": "error", "code": "user_identity_mismatch"}, status_code=403
        )
    if not spec or len(spec) > 1000:
        return JSONResponse(
            {
                "status": "error",
                "code": "invalid_spec",
                "message": "spec must be 1–1000 characters",
            },
            status_code=400,
        )

    try:
        architecture = scan_architecture()
        generated = generate_feature(spec, target=target)
        artifact_results = []
        for artifact in generated.get(
            "files",
            [{"path": generated["code_path"], "content": generated["code"]}],
        ):
            result = test_feature(artifact["path"], artifact["content"])
            artifact_results.append(
                {
                    "path": artifact["path"],
                    "language": artifact.get("language", "unknown"),
                    "role": artifact.get("role", "artifact"),
                    "passed": bool(result.get("passed")),
                    "coverage": result.get("coverage", 0.0),
                    "logs": str(result.get("logs", ""))[:12000],
                }
            )

        tests = {
            "passed": bool(artifact_results) and all(item["passed"] for item in artifact_results),
            "logs": "\n\n".join(
                "=== " + item["path"] + " (" + ("PASS" if item["passed"] else "FAIL") + ") ===\n" + item["logs"]
                for item in artifact_results
            )[:40000],
            "coverage": 0.0,
            "coverage_note": "Static contracts only; generated candidate code is not imported or executed.",
            "files": artifact_results,
        }
        status = "awaiting_approval" if tests.get("passed") else "failed_test"
        now = datetime.now(timezone.utc)
        changelog_path = (
            "changelog/meta_engineer/"
            + generated["feature"]
            + "_"
            + now.strftime("%Y%m%dT%H%M%SZ")
            + ".md"
        )
        changelog = (
            "# Meta-Engineer Proposal\n\n"
            + "- Feature: " + generated["feature"] + "\n"
            + "- Spec: " + spec + "\n"
            + "- Target: " + target + "\n"
            + "- Artifact: " + generated["code_path"] + "\n"
            + "- Status: " + status + "\n"
            + "- Created: " + now.isoformat() + "\n"
            + "- Tests passed: " + str(tests.get("passed")) + "\n\n"
            + "## Test logs\n\n" + str(tests.get("logs", ""))[:12000]
            + "\n\n## Safety\nNo production file changed. Candidate source was not executed. Human review is required.\n"
        )
        doc = {
            "spec": spec,
            "code_path": generated["code_path"],
            "generated_code": generated["code"],
            "generated_files": generated.get("files", []),
            "test_result": tests,
            "status": status,
            "createdAt": now,
            "updatedAt": now,
            "actor": actor,
            "target": target,
            "feature": generated["feature"],
            "kind": generated["kind"],
            "changelog_path": changelog_path,
            "changelog": changelog,
            "architecture_summary": {
                "structure_roots": list(architecture.get("structure", {}).keys()),
                "free_slots": architecture.get("free_slots", []),
                "read_only": True,
            },
        }
        idea_id = save_idea(doc)
        if not tests.get("passed") and "KILL SWITCH" in str(tests.get("logs", "")):
            incident = {
                "type": "kill_switch",
                "reason": "Sandbox resource limit exceeded",
                "status": "incident",
                "spec": spec,
                "code_path": generated["code_path"],
                "createdAt": now,
                "actor": actor,
                "test_result": tests,
            }
            save_idea(incident)
            audit("kill_switch", spec, generated["code_path"], tests, actor, {"ideaId": idea_id})
        audit(
            "feature_proposed",
            spec,
            generated["code_path"],
            tests,
            actor,
            {
                "ideaId": idea_id,
                "target": target,
                "status": status,
                "changelog_path": changelog_path,
                "changelog": changelog,
            },
        )
        if tests.get("passed"):
            # Only a Markdown review artifact is written. Generated source never
            # enters the live import path or gets executed by this endpoint.
            root = Path(__file__).resolve().parents[1]
            target_path = (root / changelog_path).resolve()
            if root not in target_path.parents:
                raise ValueError("invalid changelog path")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(changelog, encoding="utf-8")
            return JSONResponse(
                {
                    "status": "ready for review",
                    "ideaId": idea_id,
                    "idea_status": status,
                    "changelog_path": changelog_path,
                    "changelog": changelog,
                    "test_logs": tests.get("logs", ""),
                    "code_path": generated["code_path"],
                    "generated_code": generated["code"],
                    "generated_files": generated.get("files", []),
                    "auto_deploy": False,
                },
                status_code=201,
            )
        return JSONResponse(
            {
                "status": "failed_test",
                "ideaId": idea_id,
                "idea_status": status,
                "changelog_path": changelog_path,
                "test_logs": tests.get("logs", ""),
                "code_path": generated["code_path"],
                "generated_code": generated["code"],
                "generated_files": generated.get("files", []),
                "auto_deploy": False,
            },
            status_code=422,
        )
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "code": "invalid_spec", "message": str(exc)},
            status_code=400,
        )
    except Exception:
        logger.exception("Meta-Engineer proposal pipeline failed")
        return JSONResponse(
            {
                "status": "error",
                "code": "meta_engineer_failed",
                "message": "Build failed during validation or persistence. Check the server logs and Meta-Engineer health.",
            },
            status_code=503,
        )


def _approve(actor: str, idea_id: str):
    try:
        idea = get_idea(idea_id)
        if not idea:
            return JSONResponse({"status": "error", "code": "idea_not_found"}, status_code=404)
        if idea.get("status") != "awaiting_approval":
            return JSONResponse(
                {"status": "error", "code": "idea_not_awaiting_approval"},
                status_code=409,
            )
        now = datetime.now(timezone.utc)
        changed = update_idea(
            idea_id,
            {
                "$set": {
                    "status": "approved",
                    "approvedAt": now,
                    "approvedBy": actor,
                    "updatedAt": now,
                    "integration": "approved_for_manual_integration",
                }
            },
        )
        result = {
            "passed": True,
            "logs": "Human approval recorded; live registration remains a separate deployment step.",
        }
        audit(
            "feature_approved",
            str(idea.get("spec", "")),
            idea.get("code_path"),
            result,
            actor,
            {"ideaId": idea_id, "live_hot_swap": False},
        )
        return {
            "status": "approved_for_manual_integration" if changed else "unchanged",
            "ideaId": idea_id,
            "auto_deploy": False,
            "message": "Approval recorded. No live code or router registration was changed.",
        }
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "approval_failed"}, status_code=503
        )


def _clean(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _idea_status(actor: str, idea_id: str):
    try:
        idea = get_idea(idea_id)
        if not idea or str(idea.get("actor") or "") != actor:
            return JSONResponse(
                {"status": "error", "code": "idea_not_found"}, status_code=404
            )
        payload = _clean(dict(idea))
        payload["ideaId"] = str(payload.pop("_id", idea_id))
        payload["test_logs"] = (idea.get("test_result") or {}).get("logs", "")
        payload["test_status"] = (
            "passed" if (idea.get("test_result") or {}).get("passed") else "failed"
        )
        return {"status": "ok", "idea": payload}
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "idea_status_unavailable"}, status_code=503
        )


def _list_audit(actor: str, limit_value: str):
    try:
        if not str(limit_value).isdigit():
            raise ValueError("limit must be an integer")
        limit = min(max(int(limit_value), 1), 200)
        if db is None:
            return JSONResponse(
                {"status": "error", "code": "database_unavailable"},
                status_code=503,
            )
        records = list(db["changelogs"].find({}).sort("timestamp", -1).limit(limit))
        ideas = list(db["ideas"].find({"actor": actor}).sort("createdAt", -1).limit(limit))

        def clean_doc(document):
            document = dict(document)
            document["_id"] = str(document.get("_id", ""))
            for key in ("timestamp", "createdAt", "updatedAt", "approvedAt"):
                if document.get(key) is not None and hasattr(document[key], "isoformat"):
                    document[key] = document[key].isoformat()
            document.pop("generated_code", None)
            document.pop("generated_files", None)
            document.pop("changelog", None)
            return document

        return {
            "status": "ok",
            "audit": [clean_doc(item) for item in records],
            "ideas": [clean_doc(item) for item in ideas],
            "limit": limit,
        }
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "audit_unavailable"}, status_code=503
        )


def _pruner_audit(actor: str):
    result = audit_unused()
    audit(
        "pruner_audit",
        "audit_unused",
        None,
        {"passed": result.get("status") == "ok", "logs": str(result)},
        actor,
    )
    return result


async def _body(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


@router.get("/health")
async def meta_health():
    return await run_in_threadpool(_health)


@router.get("/scan")
async def scan(request: Request):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    return await run_in_threadpool(_scan)


@router.post("/propose")
async def propose(request: Request):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    payload = await _body(request)
    return await run_in_threadpool(_propose, actor, payload)



@router.post("/fieldkit/findings")
async def ingest_fieldkit_finding(request: Request):
    """Receive one versioned Field Engine finding as a review-only Meta-Engineer item."""
    actor, error = _authorized(dict(request.headers))
    if error:
        return error

    try:
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 65536:
                return JSONResponse({"status": "error", "code": "payload_too_large"}, status_code=413)
            chunks.append(chunk)
        raw = b"".join(chunks)
    except Exception:
        return JSONResponse({"status": "error", "code": "invalid_body"}, status_code=400)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"status": "error", "code": "invalid_json"}, status_code=400)

    try:
        record = prepare_review_record(payload, actor)
    except FieldKitFindingError as exc:
        return JSONResponse(
            {"status": "error", "code": "invalid_fieldkit_finding", "message": str(exc)},
            status_code=422,
        )

    now = datetime.now(timezone.utc)
    finding_id = record["finding_id"]
    code_path = "fieldkit/" + finding_id + ".json"
    validation = {
        "passed": True,
        "validation_only": True,
        "coverage": 0.0,
        "logs": (
            "Field Finding contract validation passed. No remediation code was generated or executed. "
            "A repair-specific candidate test is still required before any repair can be approved."
        ),
    }
    if db is not None:
        try:
            existing = db["ideas"].find_one({"fieldkit_review.finding_id": finding_id})
            if existing:
                return JSONResponse(
                    {
                        "status": "already_received",
                        "ideaId": str(existing.get("_id", "")),
                        "findingId": finding_id,
                        "approval_required": True,
                        "auto_execution": False,
                        "message": "This finding is already present in the Meta-Engineer review queue.",
                    },
                    status_code=200,
                )
        except Exception:
            logger.exception("Field Engine finding idempotency check failed")
            return JSONResponse(
                {"status": "error", "code": "fieldkit_idempotency_check_failed"},
                status_code=503,
            )

    doc = {
        "spec": record["spec"],
        "code_path": code_path,
        "generated_code": None,
        "generated_files": [],
        "test_result": validation,
        "status": "awaiting_approval",
        "createdAt": now,
        "updatedAt": now,
        "actor": actor,
        "target": "security",
        "feature": "fieldkit_finding_review",
        "kind": "fieldkit_security_review",
        "source": "revela-field-engine",
        "fieldkit_review": record,
        "changelog_path": None,
        "changelog": (
            "# Field Engine Security Review\n\n"
            + "- Finding: " + finding_id + "\n"
            + "- Severity: " + record["severity"] + "\n"
            + "- Scope: " + record["scope"] + "\n"
            + "- Simulated: " + str(record["simulated"]) + "\n"
            + "- Status: awaiting_approval\n\n"
            + "No host change or remediation was executed. Human review is required."
        ),
        "approval_required": True,
        "auto_execution": False,
        "auto_deploy": False,
    }

    try:
        idea_id = save_idea(doc)
        audit(
            "fieldkit_finding_ingested",
            record["spec"],
            code_path,
            validation,
            actor,
            {
                "ideaId": idea_id,
                "findingId": finding_id,
                "scope": record["scope"],
                "simulated": record["simulated"],
                "auto_execution": False,
            },
        )
        return JSONResponse(
            {
                "status": "awaiting_review",
                "ideaId": str(idea_id),
                "findingId": finding_id,
                "approval_required": True,
                "auto_execution": False,
                "auto_deploy": False,
                "message": "Finding recorded for human review. No repair has been executed.",
            },
            status_code=202,
        )
    except Exception:
        logger.exception("Field Engine finding ingestion failed")
        return JSONResponse(
            {"status": "error", "code": "fieldkit_ingest_failed"},
            status_code=503,
        )


@router.post("/approve/{idea_id}")
async def approve(idea_id: str, request: Request):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    return await run_in_threadpool(_approve, actor, idea_id)


@router.get("/audit/{idea_id}/status")
async def idea_status(idea_id: str, request: Request):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    return await run_in_threadpool(_idea_status, actor, idea_id)


@router.get("/audit")
async def list_audit(request: Request, limit: str = "50"):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    return await run_in_threadpool(_list_audit, actor, limit)


@router.post("/pruner/audit")
async def run_pruner(request: Request):
    actor, error = _authorized(dict(request.headers))
    if error:
        return error
    return await run_in_threadpool(_pruner_audit, actor)
