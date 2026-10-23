"""Regression tests for the end-to-end USECT surface and its evidence boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core_auditor.compliance_reports import (
    DRAFT_WARNING,
    build_compliance_readiness_pdf,
    canonical_sha256,
)
from core_inspector.inspector import inspect_capabilities, registered_routes
from revela_platform import fastapi_app as platform


def test_native_platform_entrypoint_exposes_billing_and_all_required_core_surfaces():
    routes = registered_routes(platform.app)
    required = {
        ("GET", "/v1/platform/health"),
        ("GET", "/v1/billing/plans"),
        ("POST", "/v1/billing/buy"),
        ("POST", "/v1/marketplace/publish"),
        ("GET", "/v1/meter/usage"),
        ("POST", "/v1/foundry/build"),
        ("POST", "/v1/seed/{build_id}"),
        ("GET", "/v1/auditor/verify"),
        ("POST", "/v1/zero/heal"),
        ("POST", "/v1/one/genesis"),
        ("POST", "/v1/two/improve/{tool_id}"),
        ("POST", "/v1/orchestrator/run"),
        ("POST", "/v1/evolve/scan"),
        ("POST", "/v1/evolve/evolve"),
        ("GET", "/v1/inspector/inspect"),
        ("POST", "/v1/inspector/produce"),
        ("POST", "/v1/auditor/reports/generate"),
        ("GET", "/v1/auditor/reports/{report_id}/verify"),
        ("GET", "/api/core-mesh/genesis/status"),
        ("GET", "/api/memory/{user_id}/history"),
    }
    missing = required - routes
    assert not missing, f"required USECT routes missing from deployed platform app: {sorted(missing)}"


def test_inspector_reports_structure_but_never_promises_production_readiness():
    report = inspect_capabilities(platform.app)
    assert report["schema_version"] == "usect-inspector.v1"
    assert report["repository"] == "RevelaAI"
    assert report["total_files"] > 0
    assert report["local_capabilities"] >= 15
    assert report["external_capabilities"] >= 1
    assert report["ready_for_production"] is False
    assert any(item["id"] == "elimu_external" and item["status"] == "external_not_checked" for item in report["checks"])
    assert "do not issue" not in report["interpretation"].lower()  # interpretation is an inventory note, not an invented status


def test_inspector_can_detect_missing_sources_routes_and_tests(tmp_path):
    class EmptyApplication:
        routes = []

    report = inspect_capabilities(EmptyApplication(), repository_root=tmp_path)
    assert report["structurally_covered"] is False
    assert report["ready_for_production"] is False
    assert all(item["status"] in {"missing", "test_gap", "external_not_checked"} for item in report["checks"])
    assert any(item["missing_source_files"] for item in report["checks"] if item["status"] != "external_not_checked")


def test_compliance_pdf_is_a_draft_with_a_verifiable_qr_target():
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "report_id": "cr_0123456789abcdef01234567",
        "owner_user_id": "user-1",
        "report_kind": "CE",
        "country": "KE",
        "scope": "A sample low-voltage control unit; no lab tests submitted.",
        "evidence_refs": ["https://example.invalid/test-report"],
        "checks": ["Requested datasheet review"],
        "evidence_gaps": ["Independent laboratory test is missing."],
        "created_at": now,
    }
    report["report_sha256"] = canonical_sha256(report)
    pdf = build_compliance_readiness_pdf(
        report,
        verification_url="https://revelacode.co.ke/v1/auditor/reports/cr_0123456789abcdef01234567/verify",
    )
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000
    assert "NOT A CERTIFICATE" in DRAFT_WARNING
    assert report["report_sha256"] == canonical_sha256({k: v for k, v in report.items() if k != "report_sha256"})


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/v1/zero/heal", "POST", "usect-zero-heal"),
        ("/v1/one/genesis", "POST", "usect-one-genesis"),
        ("/v1/two/improve/tool-a", "POST", "usect-two-improve"),
        ("/v1/orchestrator/run", "POST", "usect-orchestrator-run"),
        ("/v1/foundry/build", "POST", "usect-foundry-inspector"),
        ("/v1/seed/fab_0123456789abcdef01234567", "POST", "usect-seed"),
        ("/v1/auditor/verify", "GET", "usect-auditor"),
        ("/api/usect/migrate/plans", "POST", "usect-evolve-migrate"),
    ],
)
def test_canonical_usect_usage_meter_map_does_not_depend_on_request_body(path, method, expected):
    assert platform._usect_meter_key(path, method) == expected


def test_usage_meter_middleware_records_identity_not_prompt(monkeypatch):
    recorded = []
    monkeypatch.setattr(platform, "_claims_from_bearer", lambda _token: {"sub": "user-meter-1"})
    monkeypatch.setattr(
        platform, "_record_usage_safely",
        lambda **kwargs: recorded.append(kwargs),
    )
    client = TestClient(platform.app, raise_server_exceptions=False)
    response = client.get(
        "/v1/auditor/reports/does-not-exist/verify",
        headers={"Authorization": "Bearer test-token", "X-Country": "KE"},
    )
    assert response.status_code == 404
    assert len(recorded) == 1
    event = recorded[0]
    assert event["user_id"] == "user-meter-1"
    assert event["tool_id"] == "usect-auditor"
    assert event["country"] == "KE"
    assert event["success"] is False
    assert event["latency_ms"] >= 0
    assert "prompt" not in event
    assert "token" not in event
