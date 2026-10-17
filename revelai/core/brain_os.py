"""Bounded Brain OS control plane for capability awareness, diagnostics and adaptation.

This module reports evidence-backed status. It never hot-patches code, restarts
production workers, changes firewall rules, or stores raw user conversation text.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import time
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"
TASK_CATEGORIES = {
    "general", "coding", "research", "community", "biashara",
    "shamba", "elimu", "scripture", "security", "engineering",
}
MAX_LATENCY_MS = 600_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capability_inventory() -> dict[str, Any]:
    """Inventory known subsystems and distinguish code presence from runtime proof."""
    modules = {
        "brain_os": "revelai.core.brain_os",
        "orchestrator": "ai.orchestrator",
        "adaptive_hub_router": "ai.intent_router",
        "global_brain_adapter": "ai.global_brain_adapter",
        "self_knowledge_manifest": "revelai.core.agi_manifest",
        "meta_engineer": "meta_engineer.introspector",
        "defensive_shield": "revelai.sci_core.defensive_shield",
        "disaster_diagnostics": "revelai.sci_core.disaster_manager",
        "research_engine": "revelai.sci_core.research_engine",
    }
    items = {}
    for name, module in modules.items():
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            present = False
        items[name] = {
            "module": module,
            "implemented_in_source": present,
            "configured": None,
            "tested": None,
            "runtime_healthy": None,
            "status": "present_unverified" if present else "missing",
        }
    items["text_provider"] = {
        "module": "ai.ai_client",
        "implemented_in_source": True,
        "configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "tested": None,
        "runtime_healthy": None,
        "status": "configured_unverified" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else "configuration_unknown_or_missing",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "runtime": {"python": platform.python_version(), "platform": platform.system()},
        "capabilities": items,
        "interpretation": "Source presence and configuration are not proof of successful live operation.",
    }


def record_outcome(category: str, success: bool, latency_ms: int | None = None,
                   feedback: str | None = None, actor: str | None = None) -> dict[str, Any]:
    """Persist a privacy-minimized task outcome; never stores prompts or response text."""
    category = str(category or "").strip().lower()
    if category not in TASK_CATEGORIES:
        raise ValueError("unsupported task category")
    if not isinstance(success, bool):
        raise ValueError("success must be boolean")
    if latency_ms is not None and (not isinstance(latency_ms, int) or not 0 <= latency_ms <= MAX_LATENCY_MS):
        raise ValueError("latency_ms must be an integer from 0 to 600000")
    if feedback is not None:
        feedback = str(feedback).strip().lower()
        if feedback not in {"helpful", "unhelpful", "correct", "incorrect", "resolved", "unresolved"}:
            raise ValueError("feedback_label must be a supported categorical label")
    record = {
        "category": category,
        "success": success,
        "latency_ms": latency_ms,
        "feedback_label": feedback,
        "actor": str(actor or "system")[:128],
        "created_at": _now(),
    }
    from revelai.sci_core.storage import collection
    collection("brain_outcomes").insert_one(record.copy())
    return {"recorded": True, "category": category, "success": success, "created_at": record["created_at"]}


def outcome_summary() -> dict[str, Any]:
    """Return aggregated success statistics without exposing actor identifiers."""
    from revelai.sci_core.storage import collection
    col = collection("brain_outcomes")
    grouped = {}
    for category in sorted(TASK_CATEGORIES):
        rows = list(col.find({"category": category}).sort("created_at", -1).limit(200))
        if rows:
            successes = sum(1 for row in rows if row.get("success") is True)
            latencies = [row.get("latency_ms") for row in rows if isinstance(row.get("latency_ms"), int)]
            grouped[category] = {
                "sample_size": len(rows),
                "success_rate": round(successes / len(rows), 3),
                "median_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
                "window": "latest up to 200 recorded outcomes",
            }
    return {"generated_at": _now(), "categories": grouped,
            "adaptation_policy": "Metrics inform future routing decisions; they do not change model weights or permissions automatically."}


def diagnose_and_recover() -> dict[str, Any]:
    """Run safe diagnostics and only bounded, non-destructive recovery checks."""
    started = time.monotonic()
    checks: list[dict[str, Any]] = []
    try:
        from revelai.sci_core.storage import database
        db = database()
        if db is None:
            raise RuntimeError("database_not_configured")
        db.command("ping")
        checks.append({"component": "mongodb", "status": "healthy", "evidence": "ping_succeeded"})
    except Exception as exc:
        checks.append({"component": "mongodb", "status": "degraded",
                       "evidence": type(exc).__name__,
                       "recovery": "verify MONGO_URI, network access, credentials and Atlas availability; no destructive retry performed"})
    try:
        from ai.ai_client import get_text_provider_status
        provider = get_text_provider_status()
        # Never echo provider configuration payloads: they may grow to include
        # environment-derived details. Report only the provider-status shape.
        provider_configured = bool(provider)
        checks.append({"component": "text_provider", "status": "configured_unverified" if provider_configured else "degraded",
                       "evidence": "provider_status_available" if provider_configured else "provider_not_confirmed"})
    except Exception as exc:
        checks.append({"component": "text_provider", "status": "degraded", "evidence": type(exc).__name__})
    overall = "healthy" if checks and all(item["status"] == "healthy" for item in checks) else "degraded_or_unverified"
    return {
        "status": overall, "checked_at": _now(), "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "checks": checks,
        "recovery_policy": {
            "automatic_actions": ["bounded read-only diagnostics"],
            "disabled_actions": ["production code mutation", "worker termination/restart", "firewall mutation", "database destructive changes"],
            "next_step": "Use platform health checks and reviewed deployment/rollback controls for recovery actions requiring infrastructure access.",
        },
    }


def engineering_guardrails() -> dict[str, Any]:
    """Describe enforceable engineering boundaries for the existing Meta-Engineer."""
    return {
        "status": "review_gated",
        "pipeline": ["read_only_introspection", "generate_proposal", "isolated_static_tests",
                     "security_review", "human_approval", "controlled_deployment", "post_deploy_health_check"],
        "production_write_enabled": False,
        "candidate_execution_enabled": False,
        "protected_areas": ["authentication", "authorization", "secrets", "core configuration", "security middleware"],
        "reason": "This deployment has no verified isolated build-and-deploy executor; source changes remain proposals until an approved CI/CD pipeline is connected.",
    }


def register_routes(bp) -> None:
    """Attach administrator-gated Brain OS routes to an existing Flask blueprint."""
    def require_admin():
        from routes.meta_engineer_routes import _authenticated_admin
        actor, error = _authenticated_admin()
        return actor, error

    @bp.get("/brain-os/status")
    def brain_os_status():
        actor, error = require_admin()
        if error:
            return error
        return __import__("flask").jsonify({
            "status": "ok", "brain_os": capability_inventory(),
            "outcomes": outcome_summary(), "engineering": engineering_guardrails(),
            "actor": actor,
        })

    @bp.post("/brain-os/outcomes")
    def brain_os_outcomes():
        actor, error = require_admin()
        if error:
            return error
        from flask import jsonify, request
        payload = request.get_json(silent=True) or {}
        try:
            result = record_outcome(payload.get("category"), payload.get("success"),
                                    payload.get("latency_ms"), payload.get("feedback_label"), actor)
            return jsonify(result), 201
        except ValueError as exc:
            return jsonify({"status": "error", "code": "invalid_outcome", "message": str(exc)}), 400
        except Exception:
            return jsonify({"status": "error", "code": "outcome_storage_unavailable"}), 503

    @bp.post("/brain-os/heal/diagnose")
    def brain_os_heal_diagnose():
        actor, error = require_admin()
        if error:
            return error
        from flask import jsonify
        try:
            result = diagnose_and_recover()
            result["actor"] = actor
            return jsonify(result), 200
        except Exception:
            return jsonify({"status": "error", "code": "diagnostics_failed"}), 503

    @bp.get("/brain-os/engineering/guardrails")
    def brain_os_engineering_guardrails():
        actor, error = require_admin()
        if error:
            return error
        from flask import jsonify
        result = engineering_guardrails()
        result["actor"] = actor
        return jsonify(result), 200
