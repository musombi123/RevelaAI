"""Tests for the bounded Brain OS control plane."""
from unittest.mock import patch

import pytest

from revelai.core.brain_os import (
    capability_inventory,
    diagnose_and_recover,
    engineering_guardrails,
    outcome_summary,
    record_outcome,
)
from revelai.routers.agi_router import agi_router


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, key, direction=-1):
        self.rows.sort(key=lambda row: str(row.get(key, "")), reverse=direction < 0)
        return self

    def limit(self, amount):
        self.rows = self.rows[:amount]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self):
        self.rows = []

    def insert_one(self, row):
        self.rows.append(dict(row))

    def find(self, query=None):
        query = query or {}
        return FakeCursor([row for row in self.rows if all(row.get(k) == v for k, v in query.items())])


def test_capability_inventory_distinguishes_presence_from_runtime_health():
    result = capability_inventory()
    assert result["capabilities"]["brain_os"]["implemented_in_source"] is True
    assert result["capabilities"]["meta_engineer"]["runtime_healthy"] is None
    assert "interpretation" in result


def test_outcome_recording_stores_no_prompt_or_response_content():
    fake = FakeCollection()
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = record_outcome("coding", True, 120, "helpful", "admin-1")
    assert result["recorded"] is True
    assert fake.rows[0]["category"] == "coding"
    assert "prompt" not in fake.rows[0]
    assert "response" not in fake.rows[0]
    assert fake.rows[0]["feedback_label"] == "helpful"


def test_outcome_recording_rejects_freeform_feedback_and_invalid_latency():
    with pytest.raises(ValueError):
        record_outcome("coding", True, 10, "Here is private conversation text")
    with pytest.raises(ValueError):
        record_outcome("coding", True, 600001)


def test_outcome_summary_reports_aggregates_without_actor_ids():
    fake = FakeCollection()
    fake.rows.extend([
        {"category": "coding", "success": True, "latency_ms": 100, "actor": "secret-user", "created_at": "2026-10-01"},
        {"category": "coding", "success": False, "latency_ms": 200, "actor": "secret-user", "created_at": "2026-10-02"},
    ])
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = outcome_summary()
    assert result["categories"]["coding"]["success_rate"] == 0.5
    assert "secret-user" not in str(result)


def test_engineering_guardrails_keep_production_mutation_disabled():
    result = engineering_guardrails()
    assert result["production_write_enabled"] is False
    assert result["candidate_execution_enabled"] is False
    assert "human_approval" in result["pipeline"]


def test_diagnostics_are_bounded_and_never_claim_automatic_recovery():
    result = diagnose_and_recover()
    assert result["status"] in {"healthy", "degraded_or_unverified"}
    assert "production code mutation" in result["recovery_policy"]["disabled_actions"]
    assert all("recovered" not in item or item["recovered"] is False for item in result["checks"])


def test_brain_os_routes_are_registered():
    assert len(agi_router.deferred_functions) >= 6
