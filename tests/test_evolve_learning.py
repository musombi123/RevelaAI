"""Tests for the Evolver's MongoDB-only learning and feedback loop."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.learning import (
    EvolutionLearningUnavailable,
    learning_snapshot,
    recent_evaluations,
)
from core_evolve.models import EvolutionEvaluationInput, EvolutionRequest, MetricTarget
from revelai.sci_core.storage import LocalCollection


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, field, direction=-1):
        self.rows.sort(key=lambda row: row.get(field) or datetime.min.replace(tzinfo=timezone.utc), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeMongoCollection:
    backend = "mongodb"

    def __init__(self):
        self.documents = []

    def insert_one(self, document):
        self.documents.append(deepcopy(document))
        return type("InsertResult", (), {"inserted_id": str(len(self.documents))})()

    def find(self, query=None):
        query = query or {}
        return FakeCursor([
            deepcopy(item)
            for item in self.documents
            if all(item.get(key) == value for key, value in query.items())
        ])


def evolution_request() -> EvolutionRequest:
    return EvolutionRequest(
        system_id="tool.factory",
        objective="Reduce latency while preserving safety and output quality.",
        metrics=[
            MetricTarget(name="latency_ms", direction="minimize", baseline=100, target=50, unit="ms"),
            MetricTarget(name="success_rate", direction="maximize", baseline=0.95, target=0.99),
        ],
        evidence_refs=["benchmark://baseline-v1"],
        requested_depth=2,
    )


def patch_mongo(monkeypatch, collection):
    monkeypatch.setattr(
        "revelai.sci_core.storage.collection",
        lambda name: collection if name == "evolution_runs" else (_ for _ in ()).throw(ValueError(name)),
    )


def test_learning_refuses_temporary_local_cache(monkeypatch):
    patch_mongo(monkeypatch, LocalCollection("evolution_runs"))
    with pytest.raises(EvolutionLearningUnavailable, match="MongoDB is required"):
        recent_evaluations("tool.factory")


def test_proposal_ledger_hashes_objective_and_omits_raw_prompt(monkeypatch, tmp_path):
    collection = FakeMongoCollection()
    patch_mongo(monkeypatch, collection)
    engine = EvolutionEngine(tmp_path, durable_learning=True)
    proposal = engine.propose(evolution_request())
    assert collection.documents[0]["event_type"] == "proposal_created"
    assert collection.documents[0]["objective_sha256"]
    assert collection.documents[0]["proposal_state"]["objective"].startswith("sha256:")
    assert collection.documents[0]["proposal_state"]["evidence_refs"] == []
    assert "Reduce latency while preserving safety and output quality." not in str(collection.documents)
    assert proposal.learning_context == []


def test_evaluation_is_persisted_and_reused_by_next_generation(monkeypatch, tmp_path):
    collection = FakeMongoCollection()
    patch_mongo(monkeypatch, collection)
    engine = EvolutionEngine(tmp_path, durable_learning=True)

    proposal = engine.propose(evolution_request())
    # A fresh engine instance must recover the proposal from MongoDB, not local JSON.
    restarted_engine = EvolutionEngine(tmp_path / "restarted", durable_learning=True)
    report = restarted_engine.evaluate(
        proposal.proposal_id,
        EvolutionEvaluationInput(
            proposal_id=proposal.proposal_id,
            observations={"latency_ms": 40, "success_rate": 0.995},
            test_passed=True,
            security_review_passed=True,
            evidence_refs=["benchmark://candidate-v1", "tests://ci/run-101"],
        ),
    )
    assert report.eligible_for_review is True
    assert collection.documents[-1]["event_type"] == "proposal_evaluated"

    next_proposal = engine.propose(evolution_request())
    assert len(next_proposal.learning_context) >= 2
    assert any("latency_ms" in signal and "observed 40" in signal for signal in next_proposal.learning_context)
    assert any("success_rate" in signal and "observed 0.995" in signal for signal in next_proposal.learning_context)


def test_evaluation_requires_candidate_evidence_not_only_baseline_reference(tmp_path):
    engine = EvolutionEngine(tmp_path)
    proposal = engine.propose(evolution_request())
    report = engine.evaluate(
        proposal.proposal_id,
        EvolutionEvaluationInput(
            proposal_id=proposal.proposal_id,
            observations={"latency_ms": 40, "success_rate": 0.995},
            test_passed=True,
            security_review_passed=True,
            evidence_refs=[],
        ),
    )
    assert report.evidence_complete is False
    assert report.eligible_for_review is False


def test_production_proposal_is_not_accepted_when_mongo_is_unavailable(monkeypatch, tmp_path):
    patch_mongo(monkeypatch, LocalCollection("evolution_runs"))
    engine = EvolutionEngine(tmp_path, durable_learning=True)
    with pytest.raises(EvolutionError, match="MongoDB learning history is unavailable"):
        engine.propose(evolution_request())
    assert list(tmp_path.glob("*.json")) == []


def test_learning_snapshot_returns_aggregate_metric_signals(monkeypatch):
    collection = FakeMongoCollection()
    collection.documents.extend([
        {
            "event_type": "proposal_evaluated",
            "system_id": "tool.factory",
            "proposal_id": "proposal-1",
            "generation": 1,
            "status": "candidate_for_human_review",
            "eligible_for_review": True,
            "metrics": [
                {"name": "latency_ms", "direction": "minimize", "baseline": 100, "observed": 40, "target": 50, "passed": True, "unit": "ms"}
            ],
            "evaluated_at": datetime.now(timezone.utc),
        },
        {
            "event_type": "proposal_evaluated",
            "system_id": "tool.factory",
            "proposal_id": "proposal-2",
            "generation": 2,
            "status": "regression",
            "eligible_for_review": False,
            "metrics": [
                {"name": "latency_ms", "direction": "minimize", "baseline": 100, "observed": 60, "target": 50, "passed": False, "unit": "ms"}
            ],
            "evaluated_at": datetime.now(timezone.utc),
        },
    ])
    patch_mongo(monkeypatch, collection)
    snapshot = learning_snapshot("tool.factory")
    assert snapshot["source"] == "mongodb"
    assert snapshot["evaluation_count"] == 2
    assert snapshot["metric_signals"]["latency_ms"] == {
        "samples": 2, "pass_count": 1, "pass_rate": 0.5
    }
    assert snapshot["raw_prompts_included"] is False
