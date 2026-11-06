"""MongoDB-backed evidence ledger for the RevelaAI Evolver.

This module deliberately reuses Sci-Core's single MongoDB connection. It refuses
Sci-Core's temporary LocalCollection fallback: learning evidence must be durable.
Raw objectives, prompts, generated source and user identifiers are never stored.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any

class EvolutionLearningUnavailable(RuntimeError):
    """The durable MongoDB learning store is unavailable or not configured."""


_SYSTEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EVENT_TYPES = {
    "proposal_created",
    "proposal_evaluated",
    "proposal_decided",
    "tool_invention_requested",
    "tool_invention_created",
    "tool_published",
    "tool_improvement_proposed",
}
_INDEX_LOCK = Lock()
_INDEXES_READY = False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mongo_collection():
    """Get the canonical collection and reject temporary/ephemeral fallback."""
    try:
        from revelai.sci_core.storage import collection

        store = collection("evolution_runs")
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "MongoDB evolution learning storage is unavailable."
        ) from exc

    if getattr(store, "backend", None) == "local_cache":
        raise EvolutionLearningUnavailable(
            "MongoDB is required for durable evolution learning; local cache is not accepted."
        )
    if not callable(getattr(store, "insert_one", None)) or not callable(getattr(store, "find", None)):
        raise EvolutionLearningUnavailable(
            "MongoDB evolution collection does not expose the required persistence contract."
        )

    global _INDEXES_READY
    create_index = getattr(store, "create_index", None)
    if callable(create_index) and not _INDEXES_READY:
        with _INDEX_LOCK:
            if not _INDEXES_READY:
                try:
                    create_index(
                        [("proposal_id", 1), ("event_type", 1)],
                        name="evolution_proposal_lookup",
                    )
                    create_index(
                        [("system_id", 1), ("event_type", 1), ("evaluated_at", -1)],
                        name="evolution_system_history",
                    )
                except Exception as exc:
                    raise EvolutionLearningUnavailable(
                        "MongoDB evolution indexes could not be initialized."
                    ) from exc
                _INDEXES_READY = True
    return store


def ensure_available() -> None:
    """Fail before starting an operation if durable learning storage is unavailable."""
    _mongo_collection()


def record_proposal(proposal: Any) -> None:
    system_id = str(proposal.system_id)
    if not _SYSTEM_ID_RE.fullmatch(system_id):
        raise ValueError("Invalid evolution system identifier.")

    metrics = [
        {
            "name": metric.name,
            "direction": metric.direction,
            "baseline": metric.baseline,
            "target": metric.target,
            "unit": metric.unit,
        }
        for metric in proposal.success_metrics
    ]
    document = {
        "schema_version": "revela.evolution-ledger.v1",
        "event_type": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "system_id": system_id,
        "parent_proposal_id": proposal.parent_proposal_id,
        "generation": proposal.generation,
        "status": "proposed",
        "objective_sha256": _sha256(proposal.objective),
        "proposal_state": {
            "proposal_id": proposal.proposal_id,
            "system_id": system_id,
            "parent_proposal_id": proposal.parent_proposal_id,
            "generation": proposal.generation,
            "objective": "sha256:" + _sha256(proposal.objective),
            "hypotheses": list(proposal.hypotheses[:40]),
            "proposed_changes": list(proposal.proposed_changes[:40]),
            "success_metrics": [metric.model_dump(mode="python") for metric in proposal.success_metrics],
            "guardrails": list(proposal.guardrails[:40]),
            "evidence_refs": [],
            "brain_category": proposal.brain_category,
            "learning_context": list(proposal.learning_context[:12]),
            "status": "proposed",
            "created_at": proposal.created_at,
        },
        "metrics": metrics,
        "evidence_ref_sha256": [_sha256(str(ref)) for ref in proposal.evidence_refs],
        "created_at": datetime.now(timezone.utc),
    }
    try:
        _mongo_collection().insert_one(document)
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "MongoDB refused the evolution proposal ledger write."
        ) from exc



def objective_matches_proposal(proposal: Any, objective: str) -> bool:
    """Verify the caller re-submitted the original objective for a hashed proposal."""
    if not isinstance(objective, str) or not 3 <= len(objective) <= 2000:
        return False
    expected = "sha256:" + _sha256(objective)
    stored = str(getattr(proposal, "objective", "") or "")
    return bool(re.fullmatch(r"sha256:[0-9a-f]{64}", stored)) and hmac.compare_digest(stored, expected)


def get_proposal(proposal_id: str):
    """Load a proposal from MongoDB without recovering the original objective or evidence URLs."""
    if not isinstance(proposal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", proposal_id):
        raise ValueError("Invalid proposal identifier.")
    try:
        cursor = (
            _mongo_collection()
            .find({"proposal_id": proposal_id, "event_type": "proposal_created"})
            .sort("created_at", -1)
            .limit(1)
        )
        row = next(iter(cursor), None)
        if row is None:
            raise KeyError(proposal_id)
        state = row.get("proposal_state")
        if not isinstance(state, dict):
            raise EvolutionLearningUnavailable("The durable proposal record is incomplete.")
        from .models import CandidateProposal
        return CandidateProposal.model_validate(state)
    except KeyError:
        raise
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable("MongoDB proposal state could not be loaded.") from exc


def record_evaluation(proposal: Any, report: Any, evaluation: Any) -> None:
    system_id = str(proposal.system_id)
    document = {
        "schema_version": "revela.evolution-ledger.v1",
        "event_type": "proposal_evaluated",
        "proposal_id": proposal.proposal_id,
        "system_id": system_id,
        "parent_proposal_id": proposal.parent_proposal_id,
        "generation": proposal.generation,
        "status": report.verdict,
        "eligible_for_review": bool(report.eligible_for_review),
        "evidence_complete": bool(report.evidence_complete),
        "test_passed": bool(evaluation.test_passed),
        "security_review_passed": bool(evaluation.security_review_passed),
        "metrics": [
            {
                "name": metric.name,
                "direction": metric.direction,
                "baseline": metric.baseline,
                "observed": metric.observed,
                "target": metric.target,
                "passed": metric.passed,
                "unit": next(
                    (target.unit for target in proposal.success_metrics if target.name == metric.name),
                    "",
                ),
            }
            for metric in report.metrics
        ],
        "evidence_ref_sha256": [_sha256(str(ref)) for ref in evaluation.evidence_refs],
        "evaluated_at": datetime.now(timezone.utc),
    }
    try:
        _mongo_collection().insert_one(document)
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "MongoDB refused the evolution evaluation ledger write."
        ) from exc


def recent_evaluations(system_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return bounded, privacy-minimized performance evidence for future proposals."""
    if not _SYSTEM_ID_RE.fullmatch(str(system_id or "")):
        raise ValueError("Invalid evolution system identifier.")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit must be an integer from 1 to 20")
    try:
        cursor = (
            _mongo_collection()
            .find({"system_id": system_id, "event_type": "proposal_evaluated"})
            .sort("evaluated_at", -1)
            .limit(limit)
        )
        rows: list[dict[str, Any]] = []
        for row in cursor:
            metrics = row.get("metrics", [])
            safe_metrics = []
            if isinstance(metrics, list):
                for metric in metrics[:12]:
                    if not isinstance(metric, dict):
                        continue
                    safe_metrics.append({
                        "name": str(metric.get("name") or "")[:80],
                        "direction": metric.get("direction"),
                        "baseline": metric.get("baseline"),
                        "observed": metric.get("observed"),
                        "target": metric.get("target"),
                        "passed": metric.get("passed") is True,
                        "unit": str(metric.get("unit") or "")[:24],
                    })
            evaluated_at = row.get("evaluated_at")
            rows.append({
                "proposal_id": str(row.get("proposal_id") or "")[:100],
                "generation": row.get("generation"),
                "status": str(row.get("status") or "")[:64],
                "eligible_for_review": row.get("eligible_for_review") is True,
                "metrics": safe_metrics,
                "evaluated_at": evaluated_at.isoformat() if hasattr(evaluated_at, "isoformat") else None,
            })
        return rows
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "MongoDB evolution history could not be read."
        ) from exc


def record_tool_event(
    event_type: str,
    *,
    demand: str,
    tool_name: str | None = None,
    status: str | None = None,
    artifact_hash: str | None = None,
    version: str | None = None,
    risk_tier: int | None = None,
    sandbox_passed: bool | None = None,
    evolver_proposal_id: str | None = None,
    mind_proposal_id: str | None = None,
) -> None:
    """Persist privacy-minimized metadata for Genesis and Infinite Mind events."""
    if event_type not in {"tool_invention_requested", "tool_invention_created", "tool_published", "tool_improvement_proposed"}:
        raise ValueError("Unsupported tool evolution event.")
    if tool_name is not None and not _TOOL_NAME_RE.fullmatch(tool_name):
        raise ValueError("Invalid Genesis tool identifier.")
    if artifact_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
        raise ValueError("Invalid signed artifact digest.")
    if risk_tier is not None and (type(risk_tier) is not int or risk_tier not in {0, 1, 2}):
        raise ValueError("Invalid tool risk tier.")
    for proposal_ref in (evolver_proposal_id, mind_proposal_id):
        if proposal_ref is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", proposal_ref):
            raise ValueError("Invalid evolution proposal reference.")

    document = {
        "schema_version": "revela.evolution-ledger.v1",
        "event_type": event_type,
        "demand_sha256": _sha256(demand),
        "tool_name": tool_name,
        "status": str(status or "")[:64],
        "artifact_sha256": artifact_hash,
        "tool_version": str(version or "")[:64] or None,
        "risk_tier": risk_tier,
        "sandbox_passed": sandbox_passed,
        "evolver_proposal_id": evolver_proposal_id,
        "mind_proposal_id": mind_proposal_id,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        _mongo_collection().insert_one(document)
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "MongoDB refused the tool evolution ledger write."
        ) from exc



def recent_proposals(system_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Return privacy-minimized proposal/evaluation/decision summaries from MongoDB."""
    if not _SYSTEM_ID_RE.fullmatch(str(system_id or "")):
        raise ValueError("Invalid evolution system identifier.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    try:
        rows = list(
            _mongo_collection()
            .find({"system_id": system_id})
            .limit(500)
        )
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable("MongoDB proposal history could not be read.") from exc

    def event_time(row: dict[str, Any]):
        return (
            row.get("decided_at")
            or row.get("evaluated_at")
            or row.get("created_at")
            or datetime.min.replace(tzinfo=timezone.utc)
        )

    rows.sort(key=event_time, reverse=True)
    proposals: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_type = row.get("event_type")
        proposal_id = row.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            continue
        if event_type == "proposal_created":
            state = row.get("proposal_state")
            if not isinstance(state, dict) or proposal_id in proposals:
                continue
            created_at = state.get("created_at") or row.get("created_at")
            proposals[proposal_id] = {
                "proposal_id": proposal_id,
                "system_id": system_id,
                "parent_proposal_id": state.get("parent_proposal_id"),
                "generation": state.get("generation"),
                "objective_fingerprint": state.get("objective"),
                "brain_category": state.get("brain_category"),
                "hypotheses": list(state.get("hypotheses") or [])[:40],
                "proposed_changes": list(state.get("proposed_changes") or [])[:40],
                "success_metrics": list(state.get("success_metrics") or [])[:12],
                "guardrails": list(state.get("guardrails") or [])[:40],
                "learning_context": list(state.get("learning_context") or [])[:12],
                "status": "proposed",
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
                "latest_evaluation": None,
                "human_decision": None,
            }
        elif event_type == "proposal_evaluated" and proposal_id in proposals:
            if proposals[proposal_id]["latest_evaluation"] is None:
                proposals[proposal_id]["latest_evaluation"] = {
                    "status": row.get("status"),
                    "eligible_for_review": row.get("eligible_for_review") is True,
                    "evidence_complete": row.get("evidence_complete") is True,
                    "test_passed": row.get("test_passed") is True,
                    "security_review_passed": row.get("security_review_passed") is True,
                    "metrics": list(row.get("metrics") or [])[:12],
                    "evaluated_at": event_time(row).isoformat() if hasattr(event_time(row), "isoformat") else None,
                }
                proposals[proposal_id]["status"] = str(row.get("status") or "evaluated")
        elif event_type == "proposal_decided" and proposal_id in proposals:
            if proposals[proposal_id]["human_decision"] is None:
                proposals[proposal_id]["human_decision"] = {
                    "decision": row.get("decision"),
                    "rationale_fingerprint": row.get("rationale_sha256"),
                    "decided_at": event_time(row).isoformat() if hasattr(event_time(row), "isoformat") else None,
                }
                proposals[proposal_id]["status"] = str(row.get("decision") or proposals[proposal_id]["status"])
    result = list(proposals.values())
    result.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return result[:limit]


def record_human_decision(
    proposal_id: str,
    decision: str,
    rationale: str,
    reviewer_id: str,
) -> dict[str, Any]:
    """Append a human decision; approval advances to review only, never deploys."""
    if decision not in {"approve_for_next_stage", "reject"}:
        raise ValueError("Unsupported human decision.")
    rationale = " ".join(str(rationale or "").split())
    if not 3 <= len(rationale) <= 1000:
        raise ValueError("A decision rationale between 3 and 1000 characters is required.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(proposal_id or "")):
        raise ValueError("Invalid evolution proposal reference.")
    reviewer_hash = _sha256(str(reviewer_id or ""))
    if not str(reviewer_id or "").strip():
        raise ValueError("Verified reviewer identity is required.")

    store = _mongo_collection()
    latest_evaluation = next(iter(
        store.find({
            "proposal_id": proposal_id,
            "event_type": "proposal_evaluated",
        }).sort("evaluated_at", -1).limit(1)
    ), None)
    if decision == "approve_for_next_stage":
        if not isinstance(latest_evaluation, dict) or not (
            latest_evaluation.get("eligible_for_review") is True
            and latest_evaluation.get("evidence_complete") is True
            and latest_evaluation.get("test_passed") is True
            and latest_evaluation.get("security_review_passed") is True
        ):
            raise ValueError(
                "Only a candidate with complete evidence and passed test/security reviews can be approved for the next stage."
            )

    document = {
        "schema_version": "revela.evolution-ledger.v1",
        "event_type": "proposal_decided",
        "proposal_id": proposal_id,
        "system_id": str(latest_evaluation.get("system_id") or "") if latest_evaluation else "",
        "decision": decision,
        "rationale_sha256": _sha256(rationale),
        "reviewer_sha256": reviewer_hash,
        "decided_at": datetime.now(timezone.utc),
        "production_deployment_authorized": False,
        "automatic_merge": False,
    }
    try:
        store.insert_one(document)
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable("MongoDB refused the human decision ledger write.") from exc
    return {
        "proposal_id": proposal_id,
        "decision": decision,
        "next_stage_review_authorized": decision == "approve_for_next_stage",
        "production_deployment_authorized": False,
        "automatic_merge": False,
        "rationale_persisted_as": "sha256_fingerprint_only",
    }



_BRAIN_CATEGORIES = {
    "general", "coding", "research", "community", "biashara",
    "shamba", "elimu", "scripture", "security", "engineering",
}


def recent_brain_outcomes(category: str, limit: int = 200) -> dict[str, Any]:
    """Aggregate privacy-minimized Brain OS outcomes for one declared domain."""
    if category not in _BRAIN_CATEGORIES:
        raise ValueError("Unsupported Brain OS category.")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    try:
        from revelai.sci_core.storage import collection
        store = collection("brain_outcomes")
        if getattr(store, "backend", None) == "local_cache":
            raise EvolutionLearningUnavailable(
                "MongoDB is required for durable Brain OS learning evidence."
            )
        rows = list(
            store.find({"category": category})
            .sort("created_at", -1)
            .limit(limit)
        )
    except EvolutionLearningUnavailable:
        raise
    except Exception as exc:
        raise EvolutionLearningUnavailable(
            "Brain OS outcome history is unavailable from MongoDB."
        ) from exc

    delivery: list[bool] = []
    task_quality: list[bool] = []
    latencies: list[int] = []
    feedback: dict[str, int] = {}
    providers: dict[str, int] = {}
    for row in rows:
        delivered = row.get("delivery_success")
        if not isinstance(delivered, bool):
            delivered = row.get("success")
        if isinstance(delivered, bool):
            delivery.append(delivered)
        task_success = row.get("task_success")
        if isinstance(task_success, bool):
            task_quality.append(task_success)
        latency = row.get("latency_ms")
        if type(latency) is int and 0 <= latency <= 600000:
            latencies.append(latency)
        label = row.get("feedback_label")
        if isinstance(label, str) and label in {"helpful", "unhelpful", "correct", "incorrect", "resolved", "unresolved"}:
            feedback[label] = feedback.get(label, 0) + 1
        provider = row.get("provider")
        if isinstance(provider, str) and provider:
            providers[provider[:80]] = providers.get(provider[:80], 0) + 1

    latencies.sort()
    median_latency = None
    if latencies:
        middle = len(latencies) // 2
        median_latency = (
            latencies[middle] if len(latencies) % 2
            else round((latencies[middle - 1] + latencies[middle]) / 2)
        )
    return {
        "category": category,
        "sample_count": len(rows),
        "delivery_samples": len(delivery),
        "delivery_rate": round(sum(delivery) / len(delivery), 3) if delivery else None,
        "task_quality_samples": len(task_quality),
        "task_success_rate": round(sum(task_quality) / len(task_quality), 3) if task_quality else None,
        "median_latency_ms": median_latency,
        "feedback_counts": feedback,
        "provider_counts": providers,
        "source": "brain_os_mongodb",
        "raw_user_content_included": False,
    }



def learning_snapshot(system_id: str, limit: int = 8, brain_category: str | None = None) -> dict[str, Any]:
    evaluations = recent_evaluations(system_id, limit)
    metric_rows: dict[str, list[bool]] = {}
    for evaluation in evaluations:
        for metric in evaluation["metrics"]:
            metric_rows.setdefault(metric["name"], []).append(metric["passed"])
    snapshot = {
        "system_id": system_id,
        "evaluation_count": len(evaluations),
        "recent_evaluations": evaluations,
        "metric_signals": {
            name: {
                "samples": len(values),
                "pass_count": sum(values),
                "pass_rate": round(sum(values) / len(values), 3),
            }
            for name, values in sorted(metric_rows.items())
        },
        "source": "mongodb",
        "raw_prompts_included": False,
        "generated_source_included": False,
    }
    if brain_category is not None:
        snapshot["brain_os"] = recent_brain_outcomes(brain_category)
    return snapshot
