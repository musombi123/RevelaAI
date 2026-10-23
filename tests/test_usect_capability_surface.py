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
        ("GET", "/v1/evolve/scans/latest"),
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
    assert "not proof" in report["interpretation"].lower()


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


def test_compliance_report_api_persists_pdf_and_verifies_exact_bytes(monkeypatch):
    previous_overrides = dict(platform.app.dependency_overrides)
    platform.app.dependency_overrides[platform.authenticated_user] = lambda: "user-report-test"
    monkeypatch.setattr(
        platform, "_active_license",
        lambda _session, _token, user_id, country=None, tool_id=None: (
            {"sub": user_id, "jti": "license-test", "plan": "enterprise"},
            object(),
        ),
    )
    monkeypatch.setattr(platform, "require_enterprise_claims", lambda claims, entitlement: claims)
    try:
        with TestClient(platform.app, raise_server_exceptions=False) as client:
            created = client.post(
                "/v1/auditor/reports/generate",
                headers={"X-Revela-License": "test-license"},
                json={
                    "report_kind": "CE",
                    "country": "KE",
                    "scope": "A sample low voltage control unit; no accredited testing supplied.",
                    "evidence_refs": ["local-reference://datasheet"],
                    "checks": ["Nameplate and datasheet review requested"],
                    "evidence_gaps": ["No accredited lab test report provided."],
                },
            )
            assert created.status_code == 201, created.text
            data = created.json()
            assert data["certification_issued"] is False
            assert data["status"] == "draft_readiness_report"
            assert data["report_sha256"]
            assert data["pdf_sha256"]

            verified = client.get(f"/v1/auditor/reports/{data['report_id']}/verify")
            assert verified.status_code == 200, verified.text
            assert verified.json()["valid"] is True
            assert verified.json()["certification_issued"] is False

            downloaded = client.get(
                f"/v1/auditor/reports/{data['report_id']}/pdf",
                headers={"Authorization": "Bearer test-token"},
            )
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.headers["content-type"].startswith("application/pdf")
            assert downloaded.content.startswith(b"%PDF-")
            assert __import__("hashlib").sha256(downloaded.content).hexdigest() == data["pdf_sha256"]

            # Tampering with the persisted bytes invalidates the QR verification.
            with platform.SessionLocal() as session:
                row = session.get(platform.ComplianceReportRecord, data["report_id"])
                row.pdf_bytes = row.pdf_bytes + b"tampered"
                session.commit()
            tampered = client.get(f"/v1/auditor/reports/{data['report_id']}/verify")
            assert tampered.status_code == 200
            assert tampered.json()["valid"] is False
    finally:
        platform.app.dependency_overrides.clear()
        platform.app.dependency_overrides.update(previous_overrides)


def test_orchestrator_executes_steps_in_declared_zero_one_two_order(monkeypatch):
    previous_overrides = dict(platform.app.dependency_overrides)
    platform.app.dependency_overrides[platform.authenticated_user] = lambda: "user-pipeline-test"
    monkeypatch.setattr(
        platform, "_active_license",
        lambda _session, _token, user_id, country=None, tool_id=None: (
            {"sub": user_id, "jti": "license-pipeline", "plan": "enterprise"},
            object(),
        ),
    )
    monkeypatch.setattr(platform, "require_enterprise_claims", lambda claims, entitlement: claims)
    monkeypatch.setattr(platform, "enforce_tool_creation_quota", lambda session, license_record: None)
    monkeypatch.setattr(platform, "_require_owned_factory_or_tool", lambda tool_id, user_id: (user_id, tool_id))
    order = []

    def fake_zero(operation, arguments=None):
        order.append(("zero", operation))
        return {"status": "success", "executed": True, "result": {"proposal_only": True}}

    def fake_genesis(demand, **kwargs):
        order.append(("one", demand))
        return {"status": "queued", "id": "queue-test"}

    def fake_mind(objective, tool_name):
        order.append(("two", tool_name))
        return {"status": "proposal_created", "target_modified": False}

    monkeypatch.setattr(platform, "execute_usect_zero_tool", fake_zero)
    monkeypatch.setattr(platform, "queue_genesis_demand", fake_genesis)
    monkeypatch.setattr(platform, "propose_mind_evolution", fake_mind)
    monkeypatch.setattr(platform, "_persist_usect_event", lambda *args, **kwargs: True)
    try:
        with TestClient(platform.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/v1/orchestrator/run",
                headers={"X-Revela-License": "test-license"},
                json={
                    "demand": "Build a safe asset inventory review tool",
                    "tool_id": "existing-tool",
                    "error": "A reviewed operation failed with a validation error.",
                    "objective": "Reduce errors without changing production behavior.",
                },
            )
        assert response.status_code == 202, response.text
        result = response.json()
        assert result["order"] == ["USECT-ZERO", "USECT-ONE", "USECT-TWO"]
        assert [item[0] for item in order] == ["zero", "zero", "one", "two"]
        assert result["automatic_execution"] is False
        assert result["human_approval_required"] is True
    finally:
        platform.app.dependency_overrides.clear()
        platform.app.dependency_overrides.update(previous_overrides)


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


def test_startup_rvx_dialect_reconciliation_rotates_only_when_stale(monkeypatch):
    monkeypatch.setattr(platform, "verify_dialect", lambda: {"valid": False, "reason": "Dialect obsolete"})
    monkeypatch.setattr(
        platform, "evolve_dialect",
        lambda **kwargs: {
            "day": "2026-10-23",
            "dialect_version": "rvx-test-day",
            "artifact_sha256": "a" * 64,
        },
    )

    class FakeLedger:
        def append(self, **kwargs):
            return {"recorded": True}

    monkeypatch.setattr(platform, "AuditLedger", FakeLedger)
    rotated = platform._ensure_current_rvx_dialect()
    assert rotated["status"] == "rotated"
    assert rotated["dialect_version"] == "rvx-test-day"

    monkeypatch.setattr(
        platform, "verify_dialect",
        lambda: {"valid": True, "day": "2026-10-23", "dialect_version": "rvx-test-day"},
    )
    monkeypatch.setattr(
        platform, "evolve_dialect",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("a current daily dialect must not rotate again")),
    )
    current = platform._ensure_current_rvx_dialect()
    assert current["status"] == "current"
    assert current["day"] == "2026-10-23"


def test_daily_twin_scan_schedule_and_latest_evidence_are_real(monkeypatch):
    from datetime import datetime, timezone

    morning = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)
    late = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
    assert platform._next_daily_twin_scan(morning) == datetime(2026, 10, 23, 2, 17, tzinfo=timezone.utc)
    assert platform._next_daily_twin_scan(late) == datetime(2026, 10, 24, 2, 17, tzinfo=timezone.utc)
    assert platform.DAILY_TWIN_SCAN_THRESHOLD == 0.80
    assert platform.DAILY_TWIN_SCAN_MAX_CANDIDATES == 100


def test_manual_twin_scan_stores_candidates_and_latest_route_returns_evidence(monkeypatch):
    monkeypatch.setattr(platform, "_claims_from_bearer", lambda _token: {"sub": "twin-scan-user", "jti": "test-jwt"})
    monkeypatch.setattr(
        platform, "_active_license",
        lambda _session, _token, user_id, country=None, tool_id=None: (
            {"sub": user_id, "jti": "twin-scan-license", "plan": "enterprise"},
            object(),
        ),
    )
    monkeypatch.setattr(platform, "require_enterprise_claims", lambda claims, entitlement: claims)
    monkeypatch.setattr(platform, "_persist_usect_event", lambda *args, **kwargs: True)
    platform.initialize_database()
    left_id = "twin-left-" + platform.uuid4().hex[:10]
    right_id = "twin-right-" + platform.uuid4().hex[:10]
    test_scan_id = None
    try:
        with platform.SessionLocal() as session:
            session.add_all([
                platform.ToolRecord(
                    id=left_id, creator_user_id="creator-1",
                    name="Garden Crop Sensor", description="Monitor crop soil moisture and garden irrigation",
                    industry="agriculture", country_origin="KE", endpoint="/v1/example/garden-a",
                    price_usd_cents=500, status="published", bom_by_country={}, guides_by_language={},
                ),
                platform.ToolRecord(
                    id=right_id, creator_user_id="creator-2",
                    name="Garden Crop Sensor Pro", description="Monitor crop soil moisture and garden irrigation with alerts",
                    industry="agriculture", country_origin="KE", endpoint="/v1/example/garden-b",
                    price_usd_cents=700, status="published", bom_by_country={}, guides_by_language={},
                ),
            ])
            session.commit()

        with TestClient(platform.app, raise_server_exceptions=False) as client:
            headers = {"Authorization": "Bearer test-token", "X-Revela-License": "test-license"}
            scanned = client.post(
                "/v1/evolve/scan",
                headers=headers,
                json={"min_similarity": 0.70, "max_candidates": 20},
            )
            assert scanned.status_code == 200, scanned.text
            result = scanned.json()
            test_scan_id = result["scan_id"]
            assert result["status"] == "completed"
            assert result["daily_schedule_configured"] is True
            assert result["daily_schedule"] == "02:17 UTC"
            assert result["similarity_method"] == "lexical-token-jaccard-v1"
            assert result["automatic_evolution"] is False
            assert any(
                {candidate["left_tool_id"], candidate["right_tool_id"]} == {left_id, right_id}
                for candidate in result["candidates"]
            )

            latest = client.get("/v1/evolve/scans/latest", headers=headers)
            assert latest.status_code == 200, latest.text
            assert latest.json()["scan_id"] == result["scan_id"]
            assert latest.json()["trigger"] == "manual"
            assert latest.json()["automatic_publication"] is False
            assert latest.json()["scheduler_configured"] is True
            assert latest.json()["scheduler_running"] is True

        with platform.SessionLocal() as session:
            saved = session.get(platform.EvolutionTwinScanRecord, result["scan_id"])
            assert saved is not None
            assert saved.candidate_count == len(result["candidates"])
    finally:
        with platform.SessionLocal() as session:
            session.query(platform.ToolRecord).filter(
                platform.ToolRecord.id.in_([left_id, right_id])
            ).delete(synchronize_session=False)
            if test_scan_id:
                test_row = session.get(platform.EvolutionTwinScanRecord, test_scan_id)
                if test_row is not None:
                    session.delete(test_row)
            session.commit()


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
