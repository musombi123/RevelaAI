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
