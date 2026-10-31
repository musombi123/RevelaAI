"""API integration tests for Field Engine -> Meta Engineer review ingestion."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from fastapi_routes import meta_engineer as routes


def sample_finding(simulated=True):
    return {
        "schema_version": "1.0",
        "id": "field-0123456789abcdef",
        "source": "revela-field-engine",
        "observed_at": "2026-10-31T12:00:00Z",
        "target": "isolated synthetic fixture" if simulated else "C:/authorised/lab",
        "category": "identity_monitoring",
        "severity": "informational",
        "title": "Synthetic authentication-failure burst",
        "summary": "A synthetic fixture represents repeated failed authentication events.",
        "evidence": [{"kind": "synthetic_event", "ref": "scenario://auth-failure-burst"}],
        "recommendation": "Review alert thresholds and MFA coverage.",
        "scope": "lab" if simulated else "local",
        "simulated": simulated,
        "techniques": [{"framework": "MITRE ATT&CK Enterprise v20.0", "name": "Brute Force", "tactic": "Credential Access"}],
    }


def client():
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_fieldkit_finding_enters_existing_review_store(monkeypatch):
    saved = {}
    audited = []

    monkeypatch.setattr(routes, "_authorized", lambda _headers: ("admin-1", None))

    def fake_save(doc):
        saved["doc"] = doc
        return "idea-123"

    monkeypatch.setattr(routes, "save_idea", fake_save)
    monkeypatch.setattr(routes, "audit", lambda *args, **kwargs: audited.append(args))

    response = client().post("/api/meta-engineer/fieldkit/findings", json=sample_finding())

    assert response.status_code == 202
    assert response.json()["status"] == "awaiting_review"
    assert response.json()["ideaId"] == "idea-123"
    assert response.json()["auto_execution"] is False
    assert saved["doc"]["status"] == "awaiting_approval"
    assert saved["doc"]["kind"] == "fieldkit_security_review"
    assert saved["doc"]["fieldkit_review"]["simulated"] is True
    assert saved["doc"]["test_result"]["validation_only"] is True
    assert saved["doc"]["test_result"]["passed"] is True
    assert audited and audited[0][0] == "fieldkit_finding_ingested"


def test_fieldkit_ingestion_requires_admin(monkeypatch):
    called = False

    def deny(_headers):
        return None, JSONResponse({"status": "error", "code": "admin_required"}, status_code=403)

    def unexpected(_doc):
        nonlocal called
        called = True
        raise AssertionError("storage must not run before admin auth")

    monkeypatch.setattr(routes, "_authorized", deny)
    monkeypatch.setattr(routes, "save_idea", unexpected)

    response = client().post("/api/meta-engineer/fieldkit/findings", json=sample_finding())

    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"
    assert called is False


def test_fieldkit_ingestion_rejects_invalid_scope_and_oversized_body(monkeypatch):
    monkeypatch.setattr(routes, "_authorized", lambda _headers: ("admin-1", None))
    bad = sample_finding(simulated=True)
    bad["scope"] = "local"
    response = client().post("/api/meta-engineer/fieldkit/findings", json=bad)
    assert response.status_code == 422

    huge = sample_finding()
    huge["summary"] = "x" * 70000
    response = client().post("/api/meta-engineer/fieldkit/findings", json=huge)
    assert response.status_code == 413
