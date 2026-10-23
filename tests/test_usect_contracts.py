"""Regression checks for documented USECT HTTP contracts."""
from __future__ import annotations


def _paths(app):
    return {route.path for route in app.routes if getattr(route, "path", None)}


def test_native_ai_application_registers_documented_usect_routes():
    from asgi import app

    paths = _paths(app)
    required = {
        "/api/memory/{user_id}/history",
        "/api/core-mesh/dashboard",
        "/v1/learn/unknown",
        "/v1/verify/{tool_id}",
        "/v1/uncopyable/status",
        "/v1/migrate/scan",
        "/v1/migrate/migrate",
        "/v1/migrate/build-robot",
        "/api/elimu/hubs",
        "/api/elimu/progress",
        "/api/certificates/generate",
        "/api/certificates/{certificate_id}",
        "/api/accounts/profile/download",
        "/api/accounts/certificates",
        "/api/accounts/certificates/{certificate_id}/download",
        "/api/verify/certificate/{certificate_id}",
    }
    assert required <= paths


def test_platform_registers_seed_create_before_dynamic_seed_id():
    from revela_platform.fastapi_app import app

    paths = [route.path for route in app.routes if getattr(route, "path", None)]
    assert "/v1/seed/create" in paths
    assert "/v1/seed/{build_id}" in paths
    assert paths.index("/v1/seed/create") < paths.index("/v1/seed/{build_id}")


def test_orchestrator_accepts_documented_demand_only_request():
    from revela_platform.fastapi_app import OrchestratorRunInput

    request = OrchestratorRunInput(demand="Build a greenhouse temperature monitor")
    assert request.demand
    assert request.tool_id is None
    assert request.error == ""
    assert request.country == "KE"
    assert request.language == "en"


def test_improver_has_a_safe_default_objective():
    from revela_platform.fastapi_app import ImproveToolInput

    request = ImproveToolInput()
    assert len(request.objective) >= 8
    assert "improvement" in request.objective.lower()


def test_marketplace_accepts_the_documented_factory_id_alias():
    from revela_platform.fastapi_app import PublishToolInput

    request = PublishToolInput(
        tool_id="greenhouse-monitor",
        name="Greenhouse Monitor",
        description="Monitor greenhouse temperature and humidity with alerts.",
        endpoint="/v1/greenhouse-monitor",
        factory_id="fab_0123456789abcdef01234567",
        price_usd_cents=500,
    )
    assert request.factory_build_id == "fab_0123456789abcdef01234567"



def test_render_blueprint_enables_and_links_both_zero_origins():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    expected_gateway_wiring = """      # Keep the gateway adapter and dashboard/proxy origins identical.
      - key: USECT_ZERO_ENABLED
        value: "true"
      - key: USECT_ZERO_URL
        fromService:
          type: pserv
          name: usect-zero-core
          property: hostport
      - key: USECT_ZERO_BASE_URL
        fromService:
          type: pserv
          name: usect-zero-core
          property: hostport
"""
    assert expected_gateway_wiring in blueprint



def test_render_declares_runtime_dependencies_and_guarded_admin_secret():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    for key in (
        "REVELA_DATABASE_URL",
        "MONGO_URI",
        "REVELAAI_SERVICE_KEY",
        "GEMINI_API_KEY",
        "REVELA_LICENSE_PRIVATE_KEY",
        "REVELA_LICENSE_PUBLIC_KEY",
        "JWT_SECRET",
    ):
        assert f"- key: {key}\n" in blueprint
    assert """      - key: REVELA_ORGAN_ADMIN_TOKEN
        generateValue: true
""" in blueprint



def test_render_uses_documented_primary_and_fallback_gemini_models():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    assert """      - key: GEMINI_MODEL
        value: "gemini-3.8-flash"
""" in blueprint
    assert """      - key: GEMINI_FALLBACK_MODEL
        value: "gemini-3.5-flash-lite"
""" in blueprint


def test_elimu_bridge_forwards_data_without_creating_a_second_store():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "fastapi_routes" / "platform_hubs.py").read_text(encoding="utf-8")
    assert '"/api/study/elimu/hubs"' in source
    assert '"/api/study/elimu/progress"' in source
    assert '"/api/accounts/profile/download"' in source
    assert "MongoClient" not in source
    assert "pymongo" not in source.lower()


def test_personal_elimu_chat_context_uses_authoritative_backend_facts(monkeypatch):
    from fastapi_routes import platform_hubs

    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/accounts/profile/download"):
            return FakeResponse(200, {
                "success": True,
                "profile": {
                    "full_name": "Test Learner",
                    "verified": True,
                    "roles": ["student"],
                    "hubs": [{"name": "Elimu", "role": "Student", "status": "active"}],
                    "email": "must-not-be-injected@example.test",
                },
            })
        if url.endswith("/api/study/elimu/progress"):
            return FakeResponse(200, {
                "success": True,
                "hub": {
                    "name": "Elimu",
                    "progress": {"completed_lessons": 2, "total_lessons": 5},
                    "courses": [{
                        "title": "Foundations",
                        "completed": False,
                        "lessons": [{"title": "Lesson one", "completed": True}],
                    }],
                },
                "progress": {"completed_lessons": 2, "total_lessons": 5},
            })
        raise AssertionError(f"Unexpected platform URL: {url}")

    monkeypatch.setattr(platform_hubs.requests, "get", fake_get)
    context = platform_hubs.load_authoritative_user_context(
        "Bearer test-token",
        "What is my Elimu learning progress?",
    )
    assert context and context["role"] == "system"
    assert "Test Learner" in context["content"]
    assert "completed_lessons" in context["content"]
    assert "must-not-be-injected@example.test" not in context["content"]
    assert len(calls) == 2

    assert platform_hubs.load_authoritative_user_context(
        "Bearer test-token", "Explain photosynthesis"
    ) is None
    assert len(calls) == 2
