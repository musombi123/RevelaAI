"""Tests for the bounded Brain OS control plane."""
from unittest.mock import patch

import pytest

from revelai.core.brain_os import (
    capability_inventory,
    diagnose_and_recover,
    engineering_guardrails,
    outcome_summary,
    record_outcome,
    record_chat_outcome,
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


def test_outcome_recording_stores_privacy_minimized_separate_evidence():
    fake = FakeCollection()
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = record_outcome(
            "coding", True, 120, "helpful", "admin_api",
            task_success=None, provider="test-provider", route="coding-primary",
            outcome_source="admin_review",
        )
    assert result["recorded"] is True
    row = fake.rows[0]
    assert row["category"] == "coding"
    assert row["success"] is True
    assert row["delivery_success"] is True
    assert row["task_success"] is None
    assert row["user_feedback"] == "helpful"
    assert row["quality_label"] is None
    assert row["outcome_source"] == "admin_review"
    assert row["provider"] == "test-provider"
    assert row["route"] == "coding-primary"
    assert row["actor"] == "admin_api"
    assert "prompt" not in row and "response" not in row
    assert "user_id" not in row and "userId" not in row


def test_outcome_recording_rejects_freeform_feedback_and_invalid_latency():
    with pytest.raises(ValueError):
        record_outcome("coding", True, 10, "Here is private conversation text")
    with pytest.raises(ValueError):
        record_outcome("coding", True, 600001)


def test_chat_reliability_telemetry_normalizes_hub_and_keeps_quality_unknown(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr("revelai.sci_core.storage.collection", lambda name: fake)
    monkeypatch.setattr("time.monotonic", lambda: 1.25)
    result = record_chat_outcome(
        "mahubiri", True, 1.0,
        provider="Gemini 2.5 Flash", route="primary-model-route",
    )
    assert result["recorded"] is True
    row = fake.rows[0]
    assert row["category"] == "scripture"
    assert row["actor"] == "chat_api"
    assert row["latency_ms"] == 250
    assert row["delivery_success"] is True
    assert row["task_success"] is None
    assert row["outcome_source"] == "chat_delivery"
    assert row["provider"] == "gemini-2.5-flash"
    assert row["route"] == "primary-model-route"
    assert row["user_feedback"] is None
    assert "prompt" not in row and "response" not in row


def test_outcome_summary_separates_delivery_quality_feedback_and_provider_metrics():
    fake = FakeCollection()
    fake.rows.extend([
        {
            "category": "coding", "success": True, "delivery_success": True,
            "task_success": True, "latency_ms": 100, "provider": "primary",
            "route": "route-a", "feedback_label": "helpful", "user_feedback": "helpful",
            "outcome_source": "validator", "actor": "private-account-id", "created_at": "2026-10-01",
        },
        {
            "category": "coding", "success": False, "delivery_success": False,
            "task_success": False, "latency_ms": 200, "provider": "primary",
            "route": "route-a", "feedback_label": "incorrect", "quality_label": "incorrect",
            "outcome_source": "validator", "actor": "private-account-id", "created_at": "2026-10-02",
        },
        {
            "category": "coding", "success": True, "latency_ms": 150,
            "actor": "private-account-id", "created_at": "2026-10-03",
        },
    ])
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = outcome_summary()
    coding = result["categories"]["coding"]
    assert coding["sample_size"] == 3
    assert coding["delivery_sample_size"] == 3
    assert coding["delivery_success_rate"] == round(2 / 3, 3)
    assert coding["success_rate"] == coding["delivery_success_rate"]
    assert coding["task_success_sample_size"] == 2
    assert coding["task_success_rate"] == 0.5
    assert coding["task_success_by_source"]["validator"]["sample_size"] == 2
    assert coding["user_feedback_counts"] == {"helpful": 1}
    assert coding["quality_label_counts"] == {"incorrect": 1}
    assert coding["providers"]["primary"]["sample_size"] == 2
    assert coding["providers"]["primary"]["delivery_success_rate"] == 0.5
    assert coding["routes"]["route-a"]["sample_size"] == 2
    assert "private-account-id" not in str(result)


def test_outcome_recording_rejects_invalid_quality_and_dimensions():
    with pytest.raises(ValueError):
        record_outcome("coding", True, task_success="yes")
    with pytest.raises(ValueError):
        record_outcome("coding", True, provider="email@example.com")
    with pytest.raises(ValueError):
        record_outcome("coding", True, outcome_source="untrusted-arbitrary-source")


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
