from __future__ import annotations

import json

from fastapi_routes import ai as ai_routes
from fastapi_routes import system as system_routes


def test_image_capability_reports_pollinations_raster_and_local_svg_separately(monkeypatch):
    image_status = {
        "provider": "pollinations",
        "enabled": False,
        "configured": False,
        "api_key_configured": False,
        "base_url_configured": True,
        "model": "flux",
        "fallback_model": None,
    }
    monkeypatch.setattr(system_routes, "get_image_provider_status", lambda: image_status)
    monkeypatch.setattr(
        system_routes,
        "get_revelaai_text_status",
        lambda: {"providers": {"gemini": {"fallback_model": "gemini-fallback"}}},
    )
    monkeypatch.setattr(system_routes, "get_active_text_provider", lambda: "gemini")
    monkeypatch.setattr(system_routes, "get_active_text_model", lambda: "gemini-primary")
    monkeypatch.setattr(system_routes, "get_text_provider_status", lambda: {
        "provider_order": ["gemini", "huggingface", "mvi"],
        "gemini_model_validation": {"configured": True, "reachable": True, "model_valid": True},
        "providers": {
            "gemini": {"configured": True, "enabled": True, "primary_model": "gemini-primary"},
            "huggingface": {"configured": False, "enabled": False},
            "mvi": {"configured": False, "enabled": False},
        },
    })

    capabilities = system_routes.capabilities()["capabilities"]["image_generation"]
    health = system_routes.health()["providers"]["image"]
    ready = json.loads(system_routes.ready().body)

    assert capabilities["provider"] == "pollinations"
    assert capabilities["raster"]["enabled"] is False
    assert capabilities["structured_vector"] == {"enabled": True, "provider": "revelaai-svg"}
    assert health["provider"] == "pollinations"
    assert health["configured"] is False
    assert ready["checks"]["image_model"] is False
    assert ready["checks"]["structured_svg"] is True


def test_raster_image_response_metadata_names_the_real_provider(monkeypatch):
    asset = {
        "filename": "revelaai_test.png",
        "filepath": "/tmp/revelaai_test.png",
        "image_url": "https://revelaai.example.test/ai/images/revelaai_test.png",
        "asset_type": "png",
        "image_plan": {"engine": "raster", "has_text": False},
        "aspect_ratio": "1:1",
        "width": 1024,
        "height": 1024,
        "seed": 42,
    }
    monkeypatch.setattr(ai_routes, "generate_image_asset", lambda *args, **kwargs: asset)
    monkeypatch.setattr(ai_routes, "save_image_conversation", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_routes, "get_image_provider_status", lambda: {
        "provider": "pollinations",
        "enabled": True,
        "model": "flux",
    })

    response = ai_routes._image_response(
        "Create a test graphic",
        {},
        "session-1",
        {"messages": []},
        "request-1",
        "https://revelaai.example.test",
    )
    payload = json.loads(response.body)

    assert payload["success"] is True
    assert payload["meta"]["provider"] == "pollinations"
    assert payload["meta"]["model"] == "flux"



def test_runtime_reports_the_selected_mvi_model_when_gemini_is_unavailable(monkeypatch):
    from services import runtime_config

    monkeypatch.setattr(runtime_config, "get_revelaai_text_status", lambda: {
        "provider_order": ["mvi", "huggingface"],
        "providers": {
            "mvi": {"enabled": True, "primary_model": "mvi-ai-engine"},
            "huggingface": {"enabled": True, "primary_model": "hf-test-model"},
        },
    })

    assert runtime_config.get_active_text_provider() == "mvi"
    assert runtime_config.get_active_text_model() == "mvi-ai-engine"


def test_production_gateway_mounts_revelaai_and_imports_each_core_organ():
    from importlib import import_module
    from pathlib import Path

    from asgi import app as ai_app
    from revela_platform.fastapi_app import app as platform_app

    modules = (
        "core_auditor.ledger",
        "core_billing.service",
        "core_evolve.engine",
        "core_foundry.factory.foundry_builder",
        "core_inspector.inspector",
        "core_meter.meter",
        "core_migrate.service",
        "core_seed.seed_runner",
        "core_uncopyable.recipe_lock",
    )
    for module_name in modules:
        assert import_module(module_name) is not None

    mounted = next(
        route for route in platform_app.routes
        if getattr(route, "name", "") == "revelaai-native-gateway"
    )
    assert mounted.app is ai_app
    gateway_source = Path("revela_platform/fastapi_app.py").read_text(encoding="utf-8")
    assert 'app.mount("/", revelaai_app, name="revelaai-native-gateway")' in gateway_source
