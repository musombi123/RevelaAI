"""MongoDB-backed evidence ledger for the RevelaAI Evolver.

This module deliberately reuses Sci-Core's single MongoDB connection. It refuses
Sci-Core's temporary LocalCollection fallback: learning evidence must be durable.
Raw objectives, prompts, generated source and user identifiers are never stored.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

class EvolutionLearningUnavailable(RuntimeError):
    """The durable MongoDB learning store is unavailable or not configured."""


_SYSTEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EVENT_TYPES = {
    "proposal_created",
    "proposal_evaluated",
    "tool_invention_requested",
    "tool_invention_created",
    "tool_published",
}


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
) -> None:
    """Persist non-content metadata for Genesis invention and publication events."""
    if event_type not in {"tool_invention_requested", "tool_invention_created", "tool_published"}:
        raise ValueError("Unsupported tool evolution event.")
    if tool_name is not None and not _TOOL_NAME_RE.fullmatch(tool_name):
        raise ValueError("Invalid Genesis tool identifier.")
    if artifact_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
        raise ValueError("Invalid signed artifact digest.")
    if risk_tier is not None and (type(risk_tier) is not int or risk_tier not in {0, 1, 2}):
        raise ValueError("Invalid tool risk tier.")

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


def learning_snapshot(system_id: str, limit: int = 8) -> dict[str, Any]:
    evaluations = recent_evaluations(system_id, limit)
    metric_rows: dict[str, list[bool]] = {}
    for evaluation in evaluations:
        for metric in evaluation["metrics"]:
            metric_rows.setdefault(metric["name"], []).append(metric["passed"])
    return {
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
