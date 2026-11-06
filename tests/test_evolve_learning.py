"""Tests for the Evolver's MongoDB-only learning and feedback loop."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from core_evolve.engine import EvolutionEngine
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
        self.indexes = []

    def create_index(self, keys, name=None):
        self.indexes.append((keys, name))
        return name

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


def evolution_request(brain_category: str | None = None) -> EvolutionRequest:
    return EvolutionRequest(
        system_id="tool.factory",
        objective="Reduce latency while preserving safety and output quality.",
        metrics=[
            MetricTarget(name="latency_ms", direction="minimize", baseline=100, target=50, unit="ms"),
            MetricTarget(name="success_rate", direction="maximize", baseline=0.95, target=0.99),
        ],
        evidence_refs=["benchmark://baseline-v1"],
        requested_depth=2,
        brain_category=brain_category,
    )


def patch_mongo(monkeypatch, collection, brain_collection=None):
    def resolve(name):
        if name == "evolution_runs":
            return collection
        if name == "brain_outcomes" and brain_collection is not None:
            return brain_collection
        raise ValueError(name)
    monkeypatch.setattr("revelai.sci_core.storage.collection", resolve)


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
    with pytest.raises(EvolutionLearningUnavailable, match="MongoDB is required"):
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


def test_mongodb_learning_initializes_query_indexes(monkeypatch):
    collection = FakeMongoCollection()
    patch_mongo(monkeypatch, collection)
    from core_evolve.learning import ensure_available, _INDEXES_READY, _INDEX_LOCK
    with _INDEX_LOCK:
        # Reset module state only within this isolated test.
        import core_evolve.learning as learning
        learning._INDEXES_READY = False
    ensure_available()
    assert [name for _keys, name in collection.indexes] == [
        "evolution_proposal_lookup",
        "evolution_system_history",
    ]


def test_brain_os_outcomes_inform_evolver_and_survive_proposal_reload(monkeypatch, tmp_path):
    evolution_store = FakeMongoCollection()
    brain_store = FakeMongoCollection()
    brain_store.documents.extend([
        {
            "category": "engineering",
            "delivery_success": True,
            "task_success": True,
            "latency_ms": 200,
            "feedback_label": "helpful",
            "provider": "gemini",
        },
        {
            "category": "engineering",
            "delivery_success": False,
            "task_success": False,
            "latency_ms": 400,
            "feedback_label": "incorrect",
            "provider": "hf",
        },
    ])
    patch_mongo(monkeypatch, evolution_store, brain_store)
    engine = EvolutionEngine(tmp_path, durable_learning=True)
    proposal = engine.propose(evolution_request("engineering"))

    assert proposal.brain_category == "engineering"
    assert any("delivery_rate=0.5" in signal for signal in proposal.learning_context)
    assert any("task_success_rate=0.5" in signal for signal in proposal.learning_context)
    assert evolution_store.documents[0]["proposal_state"]["brain_category"] == "engineering"

    restarted = EvolutionEngine(tmp_path / "restarted", durable_learning=True)
    loaded = restarted.get(proposal.proposal_id)
    assert loaded.brain_category == "engineering"


def test_brain_os_learning_refuses_local_cache(monkeypatch):
    from core_evolve.learning import recent_brain_outcomes
    patch_mongo(monkeypatch, FakeMongoCollection(), LocalCollection("brain_outcomes"))
    with pytest.raises(EvolutionLearningUnavailable, match="MongoDB is required"):
        recent_brain_outcomes("engineering")
