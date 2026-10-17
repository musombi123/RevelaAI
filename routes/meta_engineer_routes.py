"""Review-gated Meta-Engineer API for the existing Flask application."""
from __future__ import annotations
import os
from datetime import datetime, timezone
import requests
from flask import Blueprint, jsonify, request
from meta_engineer.generator import generate_feature
from meta_engineer.introspector import scan_architecture
from meta_engineer.integrator import audit, get_idea, save_idea, update_idea
from meta_engineer.pruner import audit_unused
from meta_engineer.sandbox_tester import test_feature

meta_engineer_bp = Blueprint("meta_engineer_bp", __name__)
BACKEND_URL = os.getenv("REVELACODE_BACKEND_URL", "https://revelacode-backend.onrender.com").rstrip("/")
ADMIN_TIMEOUT = 4

def _authenticated_admin():
    """Use the existing JWT resolver and authoritative backend role; fail closed."""
    authorization = (request.headers.get("Authorization") or "").strip()
    if not authorization.startswith("Bearer "):
        return None, (jsonify({"status": "error", "code": "authentication_required"}), 401)
    try:
        # Runtime import prevents a circular import while app.py registers this blueprint.
        from app import resolve_revelacode_user_id
        user_id = resolve_revelacode_user_id()
    except Exception:
        user_id = None
    if not user_id:
        return None, (jsonify({"status": "error", "code": "invalid_identity"}), 401)
    try:
        response = requests.get(BACKEND_URL + "/api/auth/me",
            headers={"Authorization": authorization}, timeout=ADMIN_TIMEOUT)
        if response.status_code != 200:
            return None, (jsonify({"status": "error", "code": "admin_verification_unavailable"}), 503)
        body = response.json()
        candidates = [body]
        for key in ("data", "user", "profile"):
            if isinstance(body.get(key), dict): candidates.append(body[key])
        backend_ids = {str(item.get("userId") or item.get("user_id") or item.get("id") or item.get("_id") or "").strip() for item in candidates}
        if str(user_id) not in backend_ids:
            return None, (jsonify({"status": "error", "code": "identity_mismatch"}), 403)
        # The existing /api/auth/me endpoint confirms identity but deliberately
        # does not expose role. Require a server-side allowlist of known admins.
        # Never trust a caller-supplied userId or role field.
        allowed_admins = {item.strip() for item in os.getenv("META_ENGINEER_ADMIN_USER_IDS", "").split(",") if item.strip()}
        if not allowed_admins:
            return None, (jsonify({"status": "error", "code": "admin_allowlist_not_configured"}), 503)
        if str(user_id) not in allowed_admins:
            return None, (jsonify({"status": "error", "code": "admin_required"}), 403)
        return str(user_id), None
    except (requests.RequestException, ValueError):
        return None, (jsonify({"status": "error", "code": "admin_verification_unavailable"}), 503)

@meta_engineer_bp.get("/health")
def meta_health():
    return jsonify({"status": "ok", "module": "meta-engineer", "mode": "proposal-only",
                    "auto_deploy": False, "auto_delete": False})

@meta_engineer_bp.get("/scan")
def scan():
    """Return a read-only architecture map for the authenticated platform admin."""
    actor, error = _authenticated_admin()
    if error: return error
    try:
        result = scan_architecture()
        module_count = sum(len(paths) for paths in result.get("structure", {}).values())
        scanned_at = datetime.now(timezone.utc).isoformat()
        return jsonify({
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
        })
    except Exception:
        return jsonify({"status": "error", "code": "architecture_scan_failed"}), 503


@meta_engineer_bp.post("/propose")
def propose():
    actor, error = _authenticated_admin()
    if error: return error
    payload = request.get_json(silent=True) or {}
    spec = " ".join(str(payload.get("spec") or "").split())
    target = str(payload.get("target") or "fullstack").strip().lower()
    if target not in {"backend", "frontend", "database", "fullstack"}:
        return jsonify({"status": "error", "code": "invalid_target"}), 400
    requested_id = str(payload.get("userId") or "").strip()
    if requested_id and requested_id != actor:
        return jsonify({"status": "error", "code": "user_identity_mismatch"}), 403
    if not spec or len(spec) > 1000:
        return jsonify({"status": "error", "code": "invalid_spec", "message": "spec must be 1–1000 characters"}), 400
    try:
        architecture = scan_architecture()
        generated = generate_feature("Target surface: " + target + ". Feature specification: " + spec)
        tests = test_feature(generated["code_path"], generated["code"])
        status = "awaiting_approval" if tests.get("passed") else "failed_test"
        now = datetime.now(timezone.utc)
        changelog_path = "changelog/meta_engineer/" + generated["feature"] + "_" + now.strftime("%Y%m%dT%H%M%SZ") + ".md"
        changelog = ("# Meta-Engineer Proposal\n\n"
            + "- Feature: " + generated["feature"] + "\n"
            + "- Spec: " + spec + "\n"
            + "- Target: " + target + "\n"
            + "- Artifact: " + generated["code_path"] + "\n"
            + "- Status: " + status + "\n"
            + "- Created: " + now.isoformat() + "\n"
            + "- Tests passed: " + str(tests.get("passed")) + "\n\n"
            + "## Test logs\n\n" + str(tests.get("logs", ""))[:12000]
            + "\n\n## Safety\nNo production file changed. Candidate source was not executed. Human review is required.\n")
        doc = {"spec": spec, "code_path": generated["code_path"], "generated_code": generated["code"],
            "test_result": tests, "status": status, "createdAt": now, "updatedAt": now,
            "actor": actor, "target": target, "feature": generated["feature"], "kind": generated["kind"],
            "changelog_path": changelog_path, "changelog": changelog,
            "architecture_summary": {"structure_roots": list(architecture.get("structure", {}).keys()),
                "free_slots": architecture.get("free_slots", []), "read_only": True}}
        idea_id = save_idea(doc)
        if not tests.get("passed") and "KILL SWITCH" in str(tests.get("logs", "")):
            incident = {"type": "kill_switch", "reason": "Sandbox resource limit exceeded",
                "status": "incident", "spec": spec, "code_path": generated["code_path"],
                "createdAt": now, "actor": actor, "test_result": tests}
            save_idea(incident)
            audit("kill_switch", spec, generated["code_path"], tests, actor, {"ideaId": idea_id})
        audit("feature_proposed", spec, generated["code_path"], tests, actor,
              {"ideaId": idea_id, "target": target, "status": status, "changelog_path": changelog_path,
               "changelog": changelog})
        if tests.get("passed"):
            # Only Markdown is written; generated source never enters the live import path.
            from pathlib import Path
            root = Path(__file__).resolve().parents[1]
            target = (root / changelog_path).resolve()
            if root not in target.parents:
                raise ValueError("invalid changelog path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(changelog, encoding="utf-8")
            return jsonify({"status": "ready for review", "ideaId": idea_id, "idea_status": status,
                "changelog_path": changelog_path, "changelog": changelog, "test_logs": tests.get("logs", ""),
                "code_path": generated["code_path"], "generated_code": generated["code"], "auto_deploy": False}), 201
        return jsonify({"status": "failed_test", "ideaId": idea_id, "changelog_path": changelog_path,
            "test_logs": tests.get("logs", ""), "auto_deploy": False}), 422
    except ValueError as exc:
        return jsonify({"status": "error", "code": "invalid_spec", "message": str(exc)}), 400
    except Exception:
        return jsonify({"status": "error", "code": "meta_engineer_failed",
            "message": "Proposal could not be persisted or audited."}), 503

@meta_engineer_bp.post("/approve/<idea_id>")
def approve(idea_id):
    actor, error = _authenticated_admin()
    if error: return error
    try:
        idea = get_idea(idea_id)
        if not idea: return jsonify({"status": "error", "code": "idea_not_found"}), 404
        if idea.get("status") != "awaiting_approval":
            return jsonify({"status": "error", "code": "idea_not_awaiting_approval"}), 409
        now = datetime.now(timezone.utc)
        changed = update_idea(idea_id, {"$set": {"status": "approved", "approvedAt": now,
            "approvedBy": actor, "updatedAt": now, "integration": "approved_for_manual_integration"}})
        result = {"passed": True, "logs": "Human approval recorded; live registration remains a separate deployment step."}
        audit("feature_approved", str(idea.get("spec", "")), idea.get("code_path"), result, actor,
              {"ideaId": idea_id, "live_hot_swap": False})
        return jsonify({"status": "approved_for_manual_integration" if changed else "unchanged",
            "ideaId": idea_id, "auto_deploy": False,
            "message": "Approval recorded. No live code or router registration was changed."})
    except Exception:
        return jsonify({"status": "error", "code": "approval_failed"}), 503

@meta_engineer_bp.get("/audit/<idea_id>/status")
def idea_status(idea_id):
    """Return the persisted proposal and its real sandbox state for live UI polling."""
    actor, error = _authenticated_admin()
    if error: return error
    try:
        idea = get_idea(idea_id)
        if not idea:
            return jsonify({"status": "error", "code": "idea_not_found"}), 404
        if str(idea.get("actor") or "") != actor:
            return jsonify({"status": "error", "code": "idea_not_found"}), 404
        def clean(value):
            from bson import ObjectId
            if isinstance(value, ObjectId): return str(value)
            if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
            if isinstance(value, list): return [clean(v) for v in value]
            if hasattr(value, "isoformat"): return value.isoformat()
            return value
        payload = clean(dict(idea))
        payload["ideaId"] = str(payload.pop("_id", idea_id))
        payload["test_logs"] = (idea.get("test_result") or {}).get("logs", "")
        payload["test_status"] = "passed" if (idea.get("test_result") or {}).get("passed") else "failed"
        return jsonify({"status": "ok", "idea": payload})
    except Exception:
        return jsonify({"status": "error", "code": "idea_status_unavailable"}), 503


@meta_engineer_bp.get("/audit")
def list_audit():
    actor, error = _authenticated_admin()
    if error: return error
    try:
        from meta_engineer.integrator import db
        if db is None: return jsonify({"status": "error", "code": "database_unavailable"}), 503
        limit = min(max(int(request.args.get("limit", "50")), 1), 200)
        records = list(db["changelogs"].find({}).sort("timestamp", -1).limit(limit))
        ideas = list(db["ideas"].find({"actor": actor}).sort("createdAt", -1).limit(limit))
        def clean(doc):
            doc = dict(doc); doc["_id"] = str(doc.get("_id", ""))
            for key in ("timestamp", "createdAt", "updatedAt", "approvedAt"):
                if doc.get(key) is not None and hasattr(doc[key], "isoformat"): doc[key] = doc[key].isoformat()
            doc.pop("generated_code", None); doc.pop("changelog", None)
            return doc
        return jsonify({"status": "ok", "audit": [clean(x) for x in records],
                        "ideas": [clean(x) for x in ideas], "limit": limit})
    except Exception:
        return jsonify({"status": "error", "code": "audit_unavailable"}), 503

@meta_engineer_bp.post("/pruner/audit")
def run_pruner():
    actor, error = _authenticated_admin()
    if error: return error
    result = audit_unused()
    audit("pruner_audit", "audit_unused", None, {"passed": result.get("status") == "ok", "logs": str(result)}, actor)
    return jsonify(result)
