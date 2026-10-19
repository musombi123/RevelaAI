"""Review-gated Meta-Engineer API for the existing Flask application."""
from __future__ import annotations
import os
import math
import importlib.util
from datetime import datetime, timezone
import requests
from flask import Blueprint, current_app, jsonify, request
from meta_engineer.generator import generate_feature
from meta_engineer.introspector import scan_architecture
from meta_engineer.integrator import audit, get_idea, save_idea, update_idea
from meta_engineer.pruner import audit_unused
from meta_engineer.sandbox_tester import test_feature

meta_engineer_bp = Blueprint("meta_engineer_bp", __name__)

_DEFAULT_BACKEND_URL = "https://revelacode-backend.onrender.com"
BACKEND_URL = (
    os.getenv("REVELACODE_BACKEND_URL", _DEFAULT_BACKEND_URL).strip().rstrip("/")
    or _DEFAULT_BACKEND_URL
)


def _configured_admin_timeout() -> float:
    """Bound verification waits while allowing Render cold starts and slow upstreams."""
    try:
        value = float(os.getenv("REVELACODE_ADMIN_VERIFY_TIMEOUT_SECONDS", "15"))
    except (TypeError, ValueError):
        return 15.0
    if not math.isfinite(value) or value < 5 or value > 30:
        return 15.0
    return value


ADMIN_TIMEOUT = _configured_admin_timeout()
PLATFORM_ADMIN_ROLES = frozenset({"admin", "platform_admin", "super_admin", "revelacode_admin"})


def _verification_unavailable():
    return None, (
        jsonify({
            "status": "error",
            "code": "admin_verification_unavailable",
            "message": "The authoritative administrator-verification service is unavailable. No privileged action was performed.",
        }),
        503,
    )


def _authenticated_admin():
    """Require the current RevelaCode administrator role; fail closed on uncertainty."""
    authorization = (request.headers.get("Authorization") or "").strip()
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        return None, (jsonify({"status": "error", "code": "authentication_required"}), 401)

    try:
        # Runtime import avoids a circular import while app.py registers this blueprint.
        from app import resolve_revelacode_user_id
        user_id = resolve_revelacode_user_id()
    except Exception:
        user_id = None
    if not user_id:
        return None, (jsonify({"status": "error", "code": "invalid_identity"}), 401)

    try:
        # The upstream service verifies the signed token and checks the current
        # role in its authoritative user store. Never trust frontend role claims.
        response = requests.get(
            BACKEND_URL + "/api/auth/verify-admin",
            headers={"Authorization": authorization},
            timeout=(3.05, ADMIN_TIMEOUT),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # Never log the bearer token or request headers. The exception class is
        # enough to distinguish a timeout/connection failure in server logs.
        current_app.logger.warning(
            "RevelaCode administrator verification request failed (%s).",
            type(exc).__name__,
        )
        return _verification_unavailable()

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 401:
        code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else "authentication_required"
        )
        if code not in {"authentication_required", "token_expired", "invalid_token", "invalid_user_identity"}:
            code = "authentication_required"
        return None, (jsonify({"status": "error", "code": code}), 401)

    if response.status_code == 403:
        upstream_code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else ""
        )
        code = (
            upstream_code
            if upstream_code in {"admin_required", "user_identity_mismatch"}
            else "admin_required"
        )
        return None, (jsonify({"status": "error", "code": code}), 403)

    if response.status_code == 404:
        # A real user lookup miss is an authorization failure. An HTML or
        # unstructured 404 can instead mean the configured endpoint is wrong.
        if isinstance(body, dict) and body.get("code") == "user_not_found":
            return None, (jsonify({"status": "error", "code": "user_not_found"}), 403)

        current_app.logger.warning(
            "RevelaCode administrator-verification endpoint returned an unexpected HTTP 404."
        )
        return _verification_unavailable()

    if response.status_code != 200:
        upstream_code = (
            body.get("code")
            if isinstance(body, dict) and isinstance(body.get("code"), str)
            else "unstructured_response"
        )
        # Log status and safe machine code only; never log credentials or the
        # full response body. For example, role_lookup_unavailable points to
        # the upstream user-store/database path.
        current_app.logger.warning(
            "RevelaCode administrator verification returned HTTP %s (code=%s).",
            response.status_code,
            upstream_code[:80],
        )
        return _verification_unavailable()

    if not isinstance(body, dict):
        current_app.logger.warning(
            "RevelaCode administrator verification returned HTTP 200 with non-object JSON."
        )
        return _verification_unavailable()

    raw_id = body.get("userId") or body.get("user_id") or body.get("id")
    raw_role = body.get("role")
    authorized = body.get("authorized")

    if (
        not isinstance(raw_id, str)
        or not raw_id.strip()
        or not isinstance(raw_role, str)
        or not raw_role.strip()
        or not isinstance(authorized, bool)
    ):
        current_app.logger.warning(
            "RevelaCode administrator verification returned an incomplete success payload."
        )
        return _verification_unavailable()

    canonical_id = raw_id.strip()
    role = raw_role.strip().lower()

    if canonical_id != str(user_id):
        return None, (jsonify({"status": "error", "code": "identity_mismatch"}), 403)

    if authorized is not True or role not in PLATFORM_ADMIN_ROLES:
        return None, (jsonify({"status": "error", "code": "admin_required"}), 403)

    return str(user_id), None

@meta_engineer_bp.get("/health")
def meta_health():
    """Report core prerequisites without exposing credentials or role details."""
    from meta_engineer.integrator import db

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
    return jsonify({
        "status": "ok" if ready else "degraded",
        "module": "meta-engineer",
        "mode": "target-aware-proposal-builder",
        "checks": checks,
        "candidate_execution": False,
        "auto_deploy": False,
        "auto_delete": False,
    })


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
        generated = generate_feature(spec, target=target)
        artifact_results = []
        for artifact in generated.get("files", [{"path": generated["code_path"], "content": generated["code"]}]):
            result = test_feature(artifact["path"], artifact["content"])
            artifact_results.append({
                "path": artifact["path"],
                "language": artifact.get("language", "unknown"),
                "role": artifact.get("role", "artifact"),
                "passed": bool(result.get("passed")),
                "coverage": result.get("coverage", 0.0),
                "logs": str(result.get("logs", ""))[:12000],
            })
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
        doc = {"spec": spec, "code_path": generated["code_path"], "generated_code": generated["code"], "generated_files": generated.get("files", []),
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
            target_path = (root / changelog_path).resolve()
            if root not in target_path.parents:
                raise ValueError("invalid changelog path")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(changelog, encoding="utf-8")
            return jsonify({"status": "ready for review", "ideaId": idea_id, "idea_status": status,
                "changelog_path": changelog_path, "changelog": changelog, "test_logs": tests.get("logs", ""),
                "code_path": generated["code_path"], "generated_code": generated["code"], "generated_files": generated.get("files", []), "auto_deploy": False}), 201
        return jsonify({"status": "failed_test", "ideaId": idea_id, "idea_status": status, "changelog_path": changelog_path,
            "test_logs": tests.get("logs", ""), "code_path": generated["code_path"], "generated_code": generated["code"], "generated_files": generated.get("files", []), "auto_deploy": False}), 422
    except ValueError as exc:
        return jsonify({"status": "error", "code": "invalid_spec", "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Meta-Engineer proposal pipeline failed")
        return jsonify({"status": "error", "code": "meta_engineer_failed",
            "message": "Build failed during validation or persistence. Check the server logs and Meta-Engineer health."}), 503

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
            doc.pop("generated_code", None); doc.pop("generated_files", None); doc.pop("changelog", None)
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
