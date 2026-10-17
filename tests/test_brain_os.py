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
    recovery_action_catalog,
    simulate_recovery_action,
    evaluate_routing_shadow,
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
    assert coding["freshness_window_hours"] == 72
    assert coding["stale_sample_size"] == 3
    assert coding["latest_observation_at"] is not None
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


def test_recovery_catalog_is_simulation_only_and_has_no_executable_handlers():
    catalog = recovery_action_catalog()
    assert catalog["mode"] == "simulation_only"
    assert catalog["execution_enabled"] is False
    assert len(catalog["actions"]) >= 3
    assert all(action["execution_enabled"] is False for action in catalog["actions"].values())
    assert all(action["human_approval_required_for_real_action"] is True for action in catalog["actions"].values())


def test_recovery_simulation_checks_preconditions_and_writes_privacy_safe_audit():
    fake = FakeCollection()
    evidence = {
        "component": "text_provider",
        "status": "degraded",
        "retry_budget_available": True,
    }
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = simulate_recovery_action("retry_provider_once", "INC-123", evidence)
    assert result["status"] == "simulated"
    assert result["preconditions_met"] is True
    assert result["simulation_result"] == "preconditions_met"
    assert result["executed"] is False
    assert result["external_side_effects"] is False
    assert result["execution_enabled"] is False
    assert result["audit_recorded"] is True
    assert len(fake.rows) == 1
    audit = fake.rows[0]
    assert audit["action_id"] == "retry_provider_once"
    assert audit["executed"] is False
    assert "INC-123" not in str(audit)
    assert audit["incident_ref"] == result["incident_ref"]


def test_recovery_simulation_blocks_unmet_preconditions_and_unknown_actions():
    fake = FakeCollection()
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = simulate_recovery_action(
            "retry_provider_once",
            "INC-124",
            {"component": "text_provider", "status": "healthy", "retry_budget_available": False},
        )
    assert result["preconditions_met"] is False
    assert result["executed"] is False
    assert "status" in result["unmet_preconditions"]
    assert "retry_budget_available" in result["unmet_preconditions"]
    assert fake.rows[0]["simulation_result"] == "preconditions_not_met"
    with pytest.raises(ValueError):
        simulate_recovery_action("run_shell_command", "INC-125", {})


def test_recovery_simulation_rejects_unbounded_input_and_fails_closed_on_audit_error():
    with pytest.raises(ValueError):
        simulate_recovery_action("retry_provider_once", "incident with spaces", {})
    with pytest.raises(ValueError):
        simulate_recovery_action("retry_provider_once", "INC-126", {"raw_prompt": "do something"})
    with patch("revelai.sci_core.storage.collection", side_effect=OSError("audit unavailable")):
        with pytest.raises(OSError):
            simulate_recovery_action(
                "retry_provider_once", "INC-127",
                {"component": "text_provider", "status": "degraded", "retry_budget_available": True},
            )


def _routing_fixture(provider, task_successes, delivery_successes=None, age_hours=1, source="validator"):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    rows = []
    delivery_successes = delivery_successes if delivery_successes is not None else task_successes
    for index, outcome in enumerate(task_successes):
        delivery = delivery_successes[index] if index < len(delivery_successes) else True
        rows.append({
            "category": "coding",
            "provider": provider,
            "task_success": bool(outcome),
            "delivery_success": bool(delivery),
            "success": bool(delivery),
            "outcome_source": source,
            "created_at": (now + timedelta(seconds=index)).isoformat(),
        })
    return rows


def test_routing_shadow_requires_minimum_recent_trusted_quality_samples():
    fake = FakeCollection()
    fake.rows.extend(_routing_fixture("baseline", [True] * 5))
    fake.rows.extend(_routing_fixture("candidate", [True] * 5))
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = evaluate_routing_shadow("coding", "baseline", "candidate")
    assert result["mode"] == "shadow_only"
    assert result["live_route_changed"] is False
    assert result["recommendation"] == "insufficient_evidence"
    assert result["baseline"]["task_sample_size"] == 5


def test_routing_shadow_ignores_delivery_only_unknown_and_stale_labels():
    fake = FakeCollection()
    fake.rows.extend(_routing_fixture("baseline", [True] * 25, age_hours=120))
    fake.rows.extend(_routing_fixture("candidate", [True] * 25, age_hours=120))
    fake.rows.extend(_routing_fixture("baseline", [True] * 25, source="chat_delivery"))
    fake.rows.extend(_routing_fixture("candidate", [True] * 25, source="chat_delivery"))
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = evaluate_routing_shadow("coding", "baseline", "candidate")
    assert result["recommendation"] == "insufficient_evidence"
    assert result["baseline"]["task_sample_size"] == 0
    assert result["baseline"]["stale_or_unparseable_sample_size"] == 25


def test_routing_shadow_reports_conflicting_delivery_and_task_quality():
    fake = FakeCollection()
    fake.rows.extend(_routing_fixture("baseline", [False] * 25, [True] * 25))
    fake.rows.extend(_routing_fixture("candidate", [True] * 25, [False] * 25))
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = evaluate_routing_shadow("coding", "baseline", "candidate")
    assert result["baseline_delta_task_success_rate"] == 1.0
    assert result["recommendation"] == "conflicting_evidence"
    assert result["live_route_changed"] is False
    assert result["canary_or_live_changes_enabled"] is False


def test_routing_shadow_can_favor_candidate_only_for_further_offline_evaluation():
    fake = FakeCollection()
    fake.rows.extend(_routing_fixture("baseline", [False] * 25, [True] * 25))
    fake.rows.extend(_routing_fixture("candidate", [True] * 25, [True] * 25))
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = evaluate_routing_shadow("coding", "baseline", "candidate")
    assert result["recommendation"] == "candidate_favored_for_further_offline_evaluation"
    assert result["policy_version"] == "routing-shadow-v1"
    assert result["candidate"]["task_sample_size"] == 25
    assert result["candidate"]["task_success_interval_95"]["lower"] > result["baseline"]["task_success_interval_95"]["upper"]
    assert result["live_route_changed"] is False


def test_routing_shadow_rejects_same_or_invalid_providers():
    with pytest.raises(ValueError):
        evaluate_routing_shadow("coding", "baseline", "baseline")
    with pytest.raises(ValueError):
        evaluate_routing_shadow("not-a-category", "baseline", "candidate")


def test_defensive_monitor_deduplicates_sent_incidents_and_uses_alert_sink():
    from unittest.mock import Mock
    from revelai.sci_core import monitor_runner

    fake = FakeCollection()
    alert_response = Mock()
    alert_response.raise_for_status.return_value = None
    post = Mock(return_value=alert_response)
    finding = {
        "type": "vulnerable_pattern",
        "severity": "high",
        "file": "revelai/example.py",
        "line": 12,
        "fix_suggestion": "Review the pattern.",
    }
    with (
        patch("revelai.sci_core.storage.collection", return_value=fake),
        patch.object(monitor_runner.requests, "post", post),
    ):
        first = monitor_runner.monitor_once(
            alert_url="https://alerts.example.test/webhook",
            checks={"code": [finding], "auth": [], "dependencies": []},
        )
        second = monitor_runner.monitor_once(
            alert_url="https://alerts.example.test/webhook",
            checks={"code": [finding], "auth": [], "dependencies": []},
        )
    assert first["status"] == "ok"
    assert first["alerts_sent"] == 1
    assert second["alerts_sent"] == 0
    assert second["duplicates_suppressed"] == 1
    assert post.call_count == 1
    payload = post.call_args.kwargs["json"]
    assert payload["incidents"][0]["severity"] == "high"
    assert "raw_prompt" not in str(payload)
    assert len(fake.rows) == 1


def test_defensive_monitor_fails_clearly_when_alert_adapter_is_unconfigured():
    from revelai.sci_core import monitor_runner

    fake = FakeCollection()
    with patch("revelai.sci_core.storage.collection", return_value=fake):
        result = monitor_runner.monitor_once(
            alert_url="",
            checks={"code": [], "auth": [], "dependencies": []},
        )
    assert result["status"] == "misconfigured"
    assert result["alert_adapter"]["configured"] is False
    assert result["alert_adapter"]["delivery_status"] == "not_configured"


def test_defensive_monitor_controlled_incident_maps_severity_and_hashes_source():
    from revelai.sci_core import monitor_runner
    fake = FakeCollection()
    with (
        patch("revelai.sci_core.storage.collection", return_value=fake),
        patch.object(monitor_runner.requests, "post") as post,
    ):
        post.return_value.raise_for_status.return_value = None
        result = monitor_runner.monitor_once(
            alert_url="https://alerts.example.test/webhook",
            checks={
                "code": [],
                "auth": [{
                    "type": "brute_force_attempt",
                    "severity": "high",
                    "ip": "192.0.2.10",
                    "count": 75,
                    "action": "blocklist_recommendation_only",
                }],
                "dependencies": [],
            },
        )
    assert result["status"] == "ok"
    sent_payload = post.call_args.kwargs["json"]
    incident = sent_payload["incidents"][0]
    assert incident["severity"] == "high"
    assert "192.0.2.10" not in str(sent_payload)
    assert fake.rows[0]["fingerprint"]


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

def test_chat_endpoint_succeeds_when_brain_os_telemetry_storage_fails():
    import sys
    import types
    from flask import Flask

    # Keep this regression test isolated from optional provider/scraper SDKs.
    # The chat route dependencies are replaced with narrow import-time stubs.
    stubs = {}

    def stub_module(name, **attributes):
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        stubs[name] = module
        return module

    stub_module("ai.intent_router", classify_intent=lambda message: "general")
    stub_module(
        "ai.global_brain_adapter",
        build_global_context=lambda **kwargs: (
            {"role": "system", "content": "test"},
            {
                "hub": "general", "hubRequested": "auto", "hubDetected": "general",
                "interactionTone": "clear", "capabilities": [],
            },
        ),
    )
    stub_module(
        "ai.hub_prompts",
        HUB_LABELS={"general": "General"},
        get_identity_answer=lambda *args, **kwargs: None,
    )
    stub_module(
        "revelai.core.agi_manifest",
        get_self_description_answer=lambda *args, **kwargs: None,
    )
    stub_module(
        "services.ai_service",
        process_message=lambda **kwargs: {
            "response": "The test response is available.",
            "confidence": "high", "intent": "general",
            "provider": "test-provider", "model": "test-model",
        },
    )
    stub_module(
        "routes.memory_routes",
        _record_messages=lambda **kwargs: {},
        _require_identity=lambda: ("oid-test", "user-test", None),
        memories=lambda: None,
    )
    with patch.dict(sys.modules, stubs):
        from routes import chat_routes

    app = Flask(__name__)
    app.register_blueprint(chat_routes.chat_bp, url_prefix="/api/chat")
    app.config["TESTING"] = True

    interaction = {
        "hub": "general",
        "hubRequested": "auto",
        "hubDetected": "general",
        "interactionTone": "clear",
        "capabilities": [],
    }
    with (
        patch.object(chat_routes, "_require_identity", return_value=("oid-test", "user-test", None)),
        patch.object(chat_routes, "_load_personalization_context", return_value=None),
        patch.object(chat_routes, "_persist_turn"),
        patch("revelai.core.brain_os.record_chat_outcome", side_effect=OSError("telemetry database unavailable")),
    ):
        response = app.test_client().post(
            "/api/chat",
            json={"message": "Please answer this test", "hub": "auto"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["reply"].endswith("The test response is available.")
