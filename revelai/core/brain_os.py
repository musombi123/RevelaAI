"""Bounded Brain OS control plane for capability awareness, diagnostics and adaptation.

This module reports evidence-backed status. It never hot-patches code, restarts
production workers, changes firewall rules, or stores raw user conversation text.
"""
from __future__ import annotations

import importlib.util
import math
import hashlib
import os
import platform
import re
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.1"
TASK_CATEGORIES = {
    "general", "coding", "research", "community", "biashara",
    "shamba", "elimu", "scripture", "security", "engineering",
}
MAX_LATENCY_MS = 600_000
FEEDBACK_LABELS = {"helpful", "unhelpful", "correct", "incorrect", "resolved", "unresolved"}
USER_FEEDBACK_LABELS = {"helpful", "unhelpful"}
QUALITY_LABELS = {"correct", "incorrect"}
RESOLUTION_LABELS = {"resolved", "unresolved"}
OUTCOME_SOURCES = {"manual", "chat_delivery", "admin_review", "validator", "user_feedback", "security_monitor", "scheduler", "system"}
ACTOR_TYPES = {"system", "chat_api", "admin_api", "validator", "admin_review", "user_feedback", "scheduler", "security_monitor", "test"}
DIMENSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/ -]{0,99}$")
INCIDENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
RECOVERY_ACTIONS = {
    "retry_provider_once": {
        "component": "text_provider",
        "risk": "low",
        "severity": "medium",
        "description": "Plan one bounded provider retry for a confirmed transient failure.",
        "required_evidence": {
            "component": "text_provider",
            "status": "degraded",
            "retry_budget_available": True,
        },
        "allowed_authorities": {"admin_api", "scheduler", "security_monitor", "test"},
        "cooldown_seconds": 300,
        "max_attempts": 2,
        "verification_required": True,
        "future_auto_candidate": True,
    },
    "open_provider_circuit": {
        "component": "text_provider",
        "risk": "medium",
        "severity": "high",
        "description": "Plan temporary traffic isolation after a confirmed provider failure threshold.",
        "required_evidence": {
            "component": "text_provider",
            "status": "degraded",
            "failure_threshold_exceeded": True,
        },
        "allowed_authorities": {"admin_api", "test"},
        "cooldown_seconds": 900,
        "max_attempts": 1,
        "verification_required": True,
        "future_auto_candidate": False,
    },
    "refresh_disposable_cache": {
        "component": "transient_cache",
        "risk": "low",
        "severity": "low",
        "description": "Plan a refresh of a disposable cache after staleness is confirmed.",
        "required_evidence": {
            "component": "transient_cache",
            "status": "stale",
        },
        "allowed_authorities": {"admin_api", "scheduler", "test"},
        "cooldown_seconds": 300,
        "max_attempts": 2,
        "verification_required": True,
        "future_auto_candidate": True,
    },
}
EVIDENCE_STRING_VALUES = {
    "component": {"text_provider", "transient_cache"},
    "status": {"healthy", "degraded", "stale", "unknown"},
}
EVIDENCE_BOOLEAN_KEYS = {"retry_budget_available", "failure_threshold_exceeded"}
EVIDENCE_KEYS = set(EVIDENCE_STRING_VALUES) | EVIDENCE_BOOLEAN_KEYS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capability_inventory() -> dict[str, Any]:
    """Inventory Python and native core components without claiming liveness."""
    modules = {
        "brain_os": "revelai.core.brain_os",
        "orchestrator": "ai.orchestrator",
        "adaptive_hub_router": "ai.intent_router",
        "global_brain_adapter": "ai.global_brain_adapter",
        "text_provider_client": "ai.ai_client",
        "ecosystem_registry": "ai.ecosystem.registry",
        "core_mesh_adapter": "ai.core_mesh",
        "conversation_store": "services.conversation_store",
        "memory_service": "services.memory_service",
        "memory_store": "services.memory_store",
        "self_knowledge_manifest": "revelai.core.agi_manifest",
        "core_auditor": "core_auditor.ledger",
        "core_billing": "core_billing.service",
        "core_evolve": "core_evolve.engine",
        "core_foundry": "core_foundry.factory.foundry_builder",
        "core_inspector": "core_inspector.inspector",
        "core_meter": "core_meter.meter",
        "core_migrate": "core_migrate.service",
        "core_seed": "core_seed.seed_runner",
        "core_uncopyable": "core_uncopyable.recipe_lock",
        "defensive_shield": "revelai.sci_core.defensive_shield",
        "disaster_diagnostics": "revelai.sci_core.disaster_manager",
        "research_engine": "revelai.sci_core.research_engine",
    }
    items: dict[str, dict[str, Any]] = {}
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

    root = Path(__file__).resolve().parents[2]
    native_sources = {
        "core_zero": root / "core-zero" / "cmd" / "usect-zero" / "main.go",
        "core_one_genesis": root / "core-one" / "cmd" / "genesis" / "main.go",
        "core_two_infinite_mind": root / "core-two" / "cmd" / "revela-mind" / "main.go",
    }
    native_components = {
        name: {
            "source_path": str(path.relative_to(root)),
            "implemented_in_source": path.is_file(),
            "configured": None,
            "tested": None,
            "runtime_healthy": None,
            "status": "present_unverified" if path.is_file() else "missing",
        }
        for name, path in native_sources.items()
    }

    try:
        from ai.ai_client import get_text_provider_status
        provider_status = get_text_provider_status()
        configured_providers = provider_status.get("providers", {})
        if not isinstance(configured_providers, dict):
            configured_providers = {}
        enabled_names = [
            name for name, item in configured_providers.items()
            if isinstance(item, dict) and item.get("enabled") is True
        ]
        validation = provider_status.get("gemini_model_validation", {})
        gemini_validated = (
            isinstance(validation, dict)
            and validation.get("reachable") is True
            and validation.get("model_valid") is True
        )
        items["text_provider"] = {
            "module": "ai.ai_client",
            "implemented_in_source": True,
            "configured": bool(enabled_names),
            "tested": gemini_validated,
            "runtime_healthy": None,
            "enabled_providers": enabled_names,
            "status": "configured_unverified" if enabled_names else "not_configured",
            "note": "A configured provider is not proof that a live generation request succeeded.",
        }
    except Exception as exc:
        items["text_provider"] = {
            "module": "ai.ai_client",
            "implemented_in_source": True,
            "configured": False,
            "tested": False,
            "runtime_healthy": False,
            "status": "diagnostic_failed",
            "error_type": type(exc).__name__,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "runtime": {"python": platform.python_version(), "platform": platform.system()},
        "capabilities": items,
        "native_cores": native_components,
        "interpretation": (
            "Source presence, credentials and model-list validation are separate evidence levels. "
            "Only a successful live operation establishes runtime health."
        ),
    }


def _normalize_dimension(value: Any, field: str) -> str | None:
    """Accept only bounded system identifiers, never arbitrary text as a metric dimension."""
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} must be a short system identifier")
    clean = str(value).strip()
    if not clean:
        return None
    if len(clean) > 100 or not DIMENSION_PATTERN.fullmatch(clean):
        raise ValueError(f"{field} must contain only safe identifier characters (max 100)")
    # Display names may contain spaces; normalize them to stable IDs. Symbols
    # such as @ are rejected to avoid persisting arbitrary identifiers.
    return re.sub(r"\s+", "-", clean).lower()


def _safe_actor(actor: str | None) -> str:
    """Store an actor class, never an arbitrary user/account identifier."""
    candidate = str(actor or "system").strip().lower()
    return candidate if candidate in ACTOR_TYPES else "system"


def record_outcome(
    category: str,
    success: bool,
    latency_ms: int | None = None,
    feedback: str | None = None,
    actor: str | None = None,
    *,
    task_success: bool | None = None,
    provider: str | None = None,
    route: str | None = None,
    outcome_source: str = "manual",
) -> dict[str, Any]:
    """Persist privacy-minimized evidence, separating delivery from task quality.

    The legacy success field is retained for compatibility and means technical
    delivery success. task_success is independent and may remain unknown.
    Feedback categories are stored in separate semantic fields.
    """
    category = str(category or "").strip().lower()
    if category not in TASK_CATEGORIES:
        raise ValueError("unsupported task category")
    if not isinstance(success, bool):
        raise ValueError("success must be boolean")
    if task_success is not None and not isinstance(task_success, bool):
        raise ValueError("task_success must be boolean or null")
    if latency_ms is not None and (
        not isinstance(latency_ms, int) or not 0 <= latency_ms <= MAX_LATENCY_MS
    ):
        raise ValueError("latency_ms must be an integer from 0 to 600000")
    if feedback is not None:
        feedback = str(feedback).strip().lower()
        if feedback not in FEEDBACK_LABELS:
            raise ValueError("feedback_label must be a supported categorical label")
    outcome_source = str(outcome_source or "manual").strip().lower()
    if outcome_source not in OUTCOME_SOURCES:
        raise ValueError("unsupported outcome_source")

    provider = _normalize_dimension(provider, "provider")
    route = _normalize_dimension(route, "route")
    user_feedback = feedback if feedback in USER_FEEDBACK_LABELS else None
    quality_label = feedback if feedback in QUALITY_LABELS else None
    resolution_label = feedback if feedback in RESOLUTION_LABELS else None

    record = {
        "schema_version": SCHEMA_VERSION,
        "category": category,
        # Keep the old field for existing dashboards/records; it is delivery only.
        "success": success,
        "delivery_success": success,
        "task_success": task_success,
        "latency_ms": latency_ms,
        "feedback_label": feedback,
        "user_feedback": user_feedback,
        "quality_label": quality_label,
        "resolution_label": resolution_label,
        "outcome_source": outcome_source,
        "provider": provider,
        "route": route,
        "actor": _safe_actor(actor),
        "created_at": _now(),
    }
    from revelai.sci_core.storage import collection
    collection("brain_outcomes").insert_one(record.copy())
    return {
        "recorded": True,
        "category": category,
        "success": success,
        "delivery_success": success,
        "task_success": task_success,
        "created_at": record["created_at"],
    }


def record_chat_outcome(
    hub: str,
    success: bool,
    started_at: float,
    provider: str | None = None,
    route: str | None = None,
) -> dict[str, Any] | None:
    """Record technical chat delivery only; quality is deliberately left unknown."""
    import time

    aliases = {
        "mkulima": "shamba", "farm": "shamba", "agriculture": "shamba",
        "mahubiri": "scripture", "faith": "scripture", "theology": "scripture",
        "business": "biashara", "education": "elimu", "social": "community",
    }
    category = str(hub or "general").strip().lower()
    category = aliases.get(category, category)
    if category not in TASK_CATEGORIES:
        category = "general"
    latency_ms = max(0, min(MAX_LATENCY_MS, int((time.monotonic() - started_at) * 1000)))
    return record_outcome(
        category,
        bool(success),
        latency_ms,
        None,
        "chat_api",
        task_success=None,
        provider=provider,
        route=route,
        outcome_source="chat_delivery",
    )


def _delivery_value(row: dict[str, Any]) -> bool | None:
    """Read the new delivery field and fall back to legacy success records."""
    value = row.get("delivery_success")
    if isinstance(value, bool):
        return value
    legacy = row.get("success")
    return legacy if isinstance(legacy, bool) else None


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    labeled = [row[field] for row in rows if isinstance(row.get(field), bool)]
    if not labeled:
        return None
    return round(sum(1 for value in labeled if value) / len(labeled), 3)


def _counts(rows: list[dict[str, Any]], field: str, legacy_feedback: set[str] | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        if value not in FEEDBACK_LABELS and legacy_feedback and row.get("feedback_label") in legacy_feedback:
            value = row.get("feedback_label")
        if isinstance(value, str) and value in FEEDBACK_LABELS:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _parse_outcome_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _wilson_interval(successes: int, total: int) -> dict[str, float] | None:
    """Return a 95% Wilson score interval for a Bernoulli success rate."""
    if total <= 0:
        return None
    z = 1.96
    p = successes / total
    denominator = 1 + (z * z / total)
    center = (p + (z * z / (2 * total))) / denominator
    margin = (
        z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return {"lower": round(max(0.0, center - margin), 4), "upper": round(min(1.0, center + margin), 4)}


def evaluate_routing_shadow(
    category: str,
    baseline_provider: str,
    candidate_provider: str,
) -> dict[str, Any]:
    """Compare providers using recent trusted task outcomes; never selects a live route."""
    category = str(category or "").strip().lower()
    if category not in TASK_CATEGORIES:
        raise ValueError("unsupported task category")
    baseline = _normalize_dimension(baseline_provider, "baseline_provider")
    candidate = _normalize_dimension(candidate_provider, "candidate_provider")
    if not baseline or not candidate:
        raise ValueError("baseline_provider and candidate_provider are required")
    if baseline == candidate:
        raise ValueError("baseline_provider and candidate_provider must differ")

    now = datetime.now(timezone.utc)
    max_age_hours = 72
    minimum_task_samples = 20
    trusted_sources = {"validator", "admin_review"}
    from revelai.sci_core.storage import collection
    col = collection("brain_outcomes")

    def provider_metrics(provider: str) -> dict[str, Any]:
        raw_rows = list(col.find({"category": category, "provider": provider}).limit(1000))
        recent: list[dict[str, Any]] = []
        stale_or_unparseable = 0
        for row in raw_rows:
            observed_at = _parse_outcome_time(row.get("created_at"))
            if observed_at is None or observed_at > now or (now - observed_at).total_seconds() > max_age_hours * 3600:
                stale_or_unparseable += 1
                continue
            recent.append(row)
        trusted = [
            row for row in recent
            if row.get("outcome_source") in trusted_sources
            and isinstance(row.get("task_success"), bool)
        ]
        successes = sum(1 for row in trusted if row["task_success"] is True)
        deliveries = [row for row in recent if _delivery_value(row) is not None]
        delivery_successes = sum(1 for row in deliveries if _delivery_value(row) is True)
        feedback = [row for row in recent if row.get("user_feedback") in USER_FEEDBACK_LABELS]
        helpful = sum(1 for row in feedback if row.get("user_feedback") == "helpful")
        latest = max((_parse_outcome_time(row.get("created_at")) for row in recent), default=None)
        return {
            "provider": provider,
            "recent_sample_size": len(recent),
            "stale_or_unparseable_sample_size": stale_or_unparseable,
            "task_sample_size": len(trusted),
            "task_successes": successes,
            "task_success_rate": round(successes / len(trusted), 4) if trusted else None,
            "task_success_interval_95": _wilson_interval(successes, len(trusted)),
            "delivery_sample_size": len(deliveries),
            "delivery_success_rate": round(delivery_successes / len(deliveries), 4) if deliveries else None,
            "user_feedback_sample_size": len(feedback),
            "user_helpful_rate": round(helpful / len(feedback), 4) if feedback else None,
            "latest_observation_at": latest.isoformat() if latest else None,
        }

    base_metrics = provider_metrics(baseline)
    candidate_metrics = provider_metrics(candidate)
    report: dict[str, Any] = {
        "policy_version": "routing-shadow-v1",
        "mode": "shadow_only",
        "live_route_changed": False,
        "category": category,
        "baseline": base_metrics,
        "candidate": candidate_metrics,
        "minimum_task_samples_per_provider": minimum_task_samples,
        "freshness_window_hours": max_age_hours,
        "baseline_delta_task_success_rate": None,
        "recommendation": "insufficient_evidence",
        "reason": "Each provider needs enough recent, trusted task-quality labels; delivery-only and unknown labels do not qualify.",
        "generated_at": _now(),
        "canary_or_live_changes_enabled": False,
    }
    if base_metrics["task_sample_size"] < minimum_task_samples or candidate_metrics["task_sample_size"] < minimum_task_samples:
        return report

    base_rate = base_metrics["task_success_rate"]
    candidate_rate = candidate_metrics["task_success_rate"]
    report["baseline_delta_task_success_rate"] = round(candidate_rate - base_rate, 4)
    base_delivery = base_metrics["delivery_success_rate"]
    candidate_delivery = candidate_metrics["delivery_success_rate"]
    delivery_conflict = (
        base_delivery is not None
        and candidate_delivery is not None
        and candidate_delivery < base_delivery - 0.05
    )
    base_interval = base_metrics["task_success_interval_95"]
    candidate_interval = candidate_metrics["task_success_interval_95"]
    if delivery_conflict:
        report["recommendation"] = "conflicting_evidence"
        report["reason"] = "Candidate task-quality labels may look better, but its delivery success is materially worse; no routing change is permitted."
    elif candidate_interval["lower"] > base_interval["upper"]:
        report["recommendation"] = "candidate_favored_for_further_offline_evaluation"
        report["reason"] = "Recent trusted task-quality evidence favors the candidate with non-overlapping 95% Wilson intervals; this is not authorization to change a live route."
    else:
        report["recommendation"] = "no_clear_winner"
        report["reason"] = "Current task-quality intervals overlap; keep the existing baseline and gather more evidence."
    return report


def outcome_summary() -> dict[str, Any]:
    """Summarize delivery, labeled task outcomes, feedback and provider samples separately."""
    from revelai.sci_core.storage import collection

    col = collection("brain_outcomes")
    grouped: dict[str, Any] = {}

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        delivery_rows = [
            {"_delivery_value": _delivery_value(row)}
            for row in rows
            if _delivery_value(row) is not None
        ]
        task_rows = [row for row in rows if isinstance(row.get("task_success"), bool)]
        latencies = [row.get("latency_ms") for row in rows if isinstance(row.get("latency_ms"), int)]
        task_by_source: dict[str, list[dict[str, Any]]] = {}
        for row in task_rows:
            source = str(row.get("outcome_source") or "legacy")
            task_by_source.setdefault(source, []).append(row)

        provider_rows: dict[str, list[dict[str, Any]]] = {}
        route_rows: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row.get("provider"):
                provider_rows.setdefault(str(row["provider"]), []).append(row)
            if row.get("route"):
                route_rows.setdefault(str(row["route"]), []).append(row)

        def summarized_dimensions(dimensions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, items in sorted(dimensions.items()):
                dimension_delivery_rows = [
                    {"delivery_value": _delivery_value(item)}
                    for item in items if _delivery_value(item) is not None
                ]
                result[key] = {
                    "sample_size": len(items),
                    "delivery_sample_size": len(dimension_delivery_rows),
                    "delivery_success_rate": _rate(dimension_delivery_rows, "delivery_value"),
                    "task_success_sample_size": sum(1 for item in items if isinstance(item.get("task_success"), bool)),
                    "task_success_rate": _rate(items, "task_success"),
                }
            return result

        delivery_rate = _rate(delivery_rows, "_delivery_value")
        observed_times = [
            parsed for row in rows
            if (parsed := _parse_outcome_time(row.get("created_at"))) is not None
        ]
        summary_now = datetime.now(timezone.utc)
        stale_sample_size = sum(
            1 for row in rows
            if (parsed := _parse_outcome_time(row.get("created_at"))) is None
            or parsed > summary_now
            or (summary_now - parsed).total_seconds() > 72 * 3600
        )
        latest_observation = max(observed_times, default=None)
        return {
            "sample_size": len(rows),
            "latest_observation_at": latest_observation.isoformat() if latest_observation else None,
            "freshness_window_hours": 72,
            "stale_sample_size": stale_sample_size,
            "delivery_sample_size": len(delivery_rows),
            "delivery_success_rate": delivery_rate,
            # Backward-compatible alias; success_rate always describes delivery.
            "success_rate": delivery_rate,
            "task_success_sample_size": len(task_rows),
            "task_success_rate": _rate(rows, "task_success"),
            "task_success_by_source": {
                source: {
                    "sample_size": len(items),
                    "success_rate": _rate(items, "task_success"),
                }
                for source, items in sorted(task_by_source.items())
            },
            "user_feedback_counts": _counts(rows, "user_feedback", USER_FEEDBACK_LABELS),
            "quality_label_counts": _counts(rows, "quality_label", QUALITY_LABELS),
            "resolution_label_counts": _counts(rows, "resolution_label", RESOLUTION_LABELS),
            "median_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
            "providers": summarized_dimensions(provider_rows),
            "routes": summarized_dimensions(route_rows),
            "window": "latest up to 200 recorded outcomes",
        }

    for category in sorted(TASK_CATEGORIES):
        rows = list(col.find({"category": category}).sort("created_at", -1).limit(200))
        if rows:
            grouped[category] = summarize(rows)
    return {
        "generated_at": _now(),
        "schema_version": SCHEMA_VERSION,
        "categories": grouped,
        "adaptation_policy": (
            "Delivery success, task outcomes and categorical feedback remain separate evidence. "
            "Metrics may inform evaluation; they do not change live routing, model weights or permissions automatically."
        ),
    }


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
        providers = provider.get("providers", {}) if isinstance(provider, dict) else {}
        provider_configured = any(
            isinstance(item, dict) and item.get("enabled") is True
            for item in providers.values()
        ) if isinstance(providers, dict) else False
        gemini = providers.get("gemini", {}) if isinstance(providers, dict) else {}
        gemini_validation = provider.get("gemini_model_validation", {}) if isinstance(provider, dict) else {}
        checks.append({
            "component": "text_provider",
            "status": "configured_unverified" if provider_configured else "degraded",
            "evidence": "provider_enabled_configuration_present" if provider_configured else "no_enabled_text_provider",
            "active_provider_candidates": [
                name for name, item in providers.items()
                if isinstance(item, dict) and item.get("enabled") is True
            ] if isinstance(providers, dict) else [],
            "gemini_model_list_validated": bool(
                isinstance(gemini_validation, dict)
                and gemini_validation.get("reachable") is True
                and gemini_validation.get("model_valid") is True
            ),
        })
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


def recovery_action_catalog() -> dict[str, Any]:
    """Return the reviewed simulation registry; this is not an executor."""
    return {
        "mode": "simulation_only",
        "execution_enabled": False,
        "actions": {
            action_id: {
                "action_id": action_id,
                "component": action["component"],
                "risk": action["risk"],
                "severity": action["severity"],
                "description": action["description"],
                "required_evidence": dict(action["required_evidence"]),
                "allowed_authorities": sorted(action["allowed_authorities"]),
                "cooldown_seconds": action["cooldown_seconds"],
                "max_attempts": action["max_attempts"],
                "verification_required": action["verification_required"],
                "future_auto_candidate": action["future_auto_candidate"],
                "execution_enabled": False,
                "human_approval_required_for_real_action": True,
            }
            for action_id, action in sorted(RECOVERY_ACTIONS.items())
        },
    }


def simulate_recovery_action(
    action_id: str,
    incident_id: str,
    evidence: dict[str, Any] | None = None,
    *,
    authority: str = "admin_api",
    now: datetime | None = None,
    simulated_verification: str = "not_run",
) -> dict[str, Any]:
    """Validate, rate-limit and audit a recovery plan without external side effects.

    The authority argument is an internal policy dimension, not authentication.
    External callers must pass through the administrator-gated route.
    """
    if not isinstance(action_id, str) or action_id not in RECOVERY_ACTIONS:
        raise ValueError("unknown recovery action")
    if not isinstance(incident_id, str):
        raise ValueError("incident_id must be a bounded internal identifier")
    incident_id = incident_id.strip()
    if not INCIDENT_PATTERN.fullmatch(incident_id):
        raise ValueError("incident_id must contain only safe identifier characters (max 100)")
    if not isinstance(authority, str) or authority not in ACTOR_TYPES:
        raise ValueError("unsupported authority class")
    if simulated_verification not in {"not_run", "passed", "failed", "unknown"}:
        raise ValueError("simulated_verification must be not_run, passed, failed or unknown")
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be an object")
    if set(evidence) - EVIDENCE_KEYS:
        raise ValueError("evidence contains unsupported fields")

    clean_evidence: dict[str, Any] = {}
    for key, value in evidence.items():
        if key in EVIDENCE_BOOLEAN_KEYS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean")
            clean_evidence[key] = value
        else:
            if not isinstance(value, str) or value.strip().lower() not in EVIDENCE_STRING_VALUES[key]:
                raise ValueError(f"{key} must be an approved categorical value")
            clean_evidence[key] = value.strip().lower()

    action = RECOVERY_ACTIONS[action_id]
    if authority not in action["allowed_authorities"]:
        raise PermissionError("authority is not allowed for this recovery action")
    required = action["required_evidence"]
    unmet = [key for key, expected in required.items() if clean_evidence.get(key) != expected]
    preconditions_met = not unmet
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    now_dt = now_dt.astimezone(timezone.utc)
    created_at = now_dt.isoformat()
    incident_ref = hashlib.sha256(incident_id.encode("utf-8")).hexdigest()[:24]

    from revelai.sci_core.storage import collection
    col = collection("brain_recovery_runs")
    previous = list(col.find({"action_id": action_id, "incident_ref": incident_ref}).limit(100))
    previous_attempts = [
        row for row in previous
        if row.get("attempt_consumed") is True
    ]
    last_attempt = None
    for row in previous_attempts:
        parsed = _parse_outcome_time(row.get("created_at"))
        if parsed and (last_attempt is None or parsed > last_attempt):
            last_attempt = parsed
    elapsed_since_last = (
        (now_dt - last_attempt).total_seconds() if last_attempt is not None else None
    )
    cooldown_active = (
        elapsed_since_last is not None
        and 0 <= elapsed_since_last < action["cooldown_seconds"]
    )
    retry_exhausted = len(previous_attempts) >= action["max_attempts"]
    if not preconditions_met:
        decision = "preconditions_not_met"
    elif retry_exhausted:
        decision = "retry_exhausted"
    elif cooldown_active:
        decision = "cooldown_active"
    elif simulated_verification == "failed":
        decision = "verification_failed_escalate"
    elif simulated_verification == "unknown":
        decision = "verification_unknown_escalate"
    elif simulated_verification == "passed":
        decision = "verification_passed_simulated"
    else:
        decision = "ready_for_approval_simulation"

    attempt_consumed = preconditions_met and not retry_exhausted and not cooldown_active
    audit_event = {
        "schema_version": "1.1",
        "incident_ref": incident_ref,
        "action_id": action_id,
        "authority": authority,
        "severity": action["severity"],
        "mode": "simulation_only",
        "policy_decision": decision,
        "simulation_result": "preconditions_met" if preconditions_met else "preconditions_not_met",
        "preconditions_met": preconditions_met,
        "unmet_preconditions": unmet,
        "attempt_count": len(previous_attempts) + int(attempt_consumed),
        "attempt_consumed": attempt_consumed,
        "cooldown_seconds": action["cooldown_seconds"],
        "max_attempts": action["max_attempts"],
        "simulated_verification": simulated_verification,
        "verification_required": action["verification_required"],
        "escalation_required": decision in {"verification_failed_escalate", "verification_unknown_escalate", "retry_exhausted"},
        "executed": False,
        "external_side_effects": False,
        "created_at": created_at,
    }
    # Fail closed: do not report a successful audit if persistence fails.
    col.insert_one(audit_event.copy())
    return {
        "status": "simulated",
        "action_id": action_id,
        "component": action["component"],
        "risk": action["risk"],
        "severity": action["severity"],
        "mode": "simulation_only",
        "policy_decision": decision,
        "simulation_result": audit_event["simulation_result"],
        "preconditions_met": preconditions_met,
        "unmet_preconditions": unmet,
        "attempt_count": audit_event["attempt_count"],
        "attempt_consumed": attempt_consumed,
        "cooldown_seconds": action["cooldown_seconds"],
        "max_attempts": action["max_attempts"],
        "simulated_verification": simulated_verification,
        "verification_required": action["verification_required"],
        "escalation_required": audit_event["escalation_required"],
        "executed": False,
        "external_side_effects": False,
        "execution_enabled": False,
        "human_approval_required_for_real_action": True,
        "audit_recorded": True,
        "incident_ref": incident_ref,
        "created_at": created_at,
    }


def engineering_guardrails() -> dict[str, Any]:
    """Describe enforceable engineering boundaries for the existing Meta-Engineer."""
    return {
        "status": "review_gated",
        "pipeline": ["read_only_introspection", "generate_proposal", "isolated_static_tests",
                     "security_review", "human_approval", "controlled_deployment", "post_deploy_health_check"],
        "production_write_enabled": False,
        "candidate_execution_enabled": False,
        "recovery_action_execution_enabled": False,
        "recovery_action_mode": "simulation_only",
        "protected_areas": ["authentication", "authorization", "secrets", "core configuration", "security middleware"],
        "reason": "This deployment has no verified isolated build-and-deploy executor; source changes remain proposals until an approved CI/CD pipeline is connected.",
    }
