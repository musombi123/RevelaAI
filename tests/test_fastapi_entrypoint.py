"""Regression tests for the FastAPI ASGI migration entry point and route parity."""
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes.auth import _header_value


client = TestClient(app)



def test_app_module_exports_the_native_fastapi_instance() -> None:
    import app as app_module
    from fastapi import FastAPI

    assert isinstance(app_module.app, FastAPI)
    assert app_module.app is app


def test_runtime_has_no_flask_wsgi_compatibility_mount() -> None:
    from pathlib import Path
    import re
    import asgi

    app_source = Path("app.py").read_text(encoding="utf-8")
    asgi_source = Path(asgi.__file__).read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "WSGIMiddleware" not in asgi_source
    assert "legacy_flask_app" not in asgi_source
    assert "WSGIMiddleware" not in app_source
    assert not re.search(r"^\s*(?:from|import)\s+flask(?:\\.|\s)", asgi_source, re.M)
    assert not re.search(r"^\s*(?:from|import)\s+flask(?:\\.|\s)", app_source, re.M)
    for dependency in ("flask", "flask-cors", "a2wsgi"):
        assert not re.search(rf"^\s*{re.escape(dependency)}(?:[<=>~!;\\[]|\s|$)", requirements, re.M), dependency
    assert not Path("legacy_flask_app.py").exists()



def test_native_core_routers_do_not_import_the_flask_compatibility_module() -> None:
    from fastapi_routes import ai as ai_routes
    from fastapi_routes import stream as stream_routes
    from fastapi_routes import voice as voice_routes
    from fastapi_routes import system as system_routes

    for module in (ai_routes, stream_routes, voice_routes, system_routes):
        assert "legacy" not in module.__dict__
        assert "legacy_flask_app" not in module.__dict__


def test_fastapi_health_endpoint_and_security_headers() -> None:
    response = client.get("/_fastapi/health")
    assert response.status_code == 200
    assert response.json()["runtime"] == "fastapi"
    assert response.json()["service"] == "revelaai"
    assert response.json()["migration"] == "native-fastapi-only"
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_fastapi_openapi_and_docs_are_available() -> None:
    schema_response = client.get("/openapi.json")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["info"]["title"] == "RevelaAI API"
    assert "/api/chat" in schema["paths"]
    assert "/api/research" in schema["paths"]
    assert "/api/users" in schema["paths"]
    assert "/api/users/{user_id}" in schema["paths"]
    assert "/api/vision/analyze" in schema["paths"]
    assert "/voice" in schema["paths"]
    assert "/api/revelaai/v2/brain/chat" in schema["paths"]
    assert "/api/revelaai/hubs/" in schema["paths"]
    assert "/api/core-mesh/dashboard" in schema["paths"]
    assert "/api/memory/chat" in schema["paths"]
    assert "/api/memory/ideas" in schema["paths"]
    assert "/api/core-mesh/genesis/invent" in schema["paths"]
    assert "/v1/learn/known" in schema["paths"]
    assert "/health" in schema["paths"]
    assert "/ai" in schema["paths"]
    assert "/ai/stream" in schema["paths"]
    assert "/ready" in schema["paths"]
    assert "/capabilities" in schema["paths"]
    assert "/ai/images/{filename}" in schema["paths"]
    assert "/webhook/whatsapp" in schema["paths"]
    assert "/api/agi/manifest" in schema["paths"]
    assert "/api/agi/status" in schema["paths"]
    assert "/api/agi/brain-os/status" in schema["paths"]
    assert "/api/agi/brain-os/outcomes" in schema["paths"]
    assert "/api/agi/brain-os/heal/actions/simulate" in schema["paths"]
    assert "/api/agi/brain-os/engineering/guardrails" in schema["paths"]
    assert "/api/sci/shield/dashboard" in schema["paths"]
    assert "/api/sci/shield/status" in schema["paths"]
    assert "/api/sci/shield/scan" in schema["paths"]
    assert "/api/sci/research" in schema["paths"]
    assert "/api/sci/disaster/simulate" in schema["paths"]
    assert "/api/sci/lab/prototype" in schema["paths"]
    assert "/api/meta-engineer/health" in schema["paths"]
    assert "/api/meta-engineer/scan" in schema["paths"]
    assert "/api/meta-engineer/propose" in schema["paths"]
    assert "/api/meta-engineer/approve/{idea_id}" in schema["paths"]
    assert "/api/meta-engineer/pruner/audit" in schema["paths"]
    assert "/api/usect-zero/health" in schema["paths"]
    assert "/api/usect-zero/keys/requests" in schema["paths"]
    assert "/api/usect-zero/keys/issued" in schema["paths"]
    assert "/api/usect-zero/assemble" in schema["paths"]
    assert "/api/usect-zero/radar/compare" in schema["paths"]
    assert "/api/automation-fabric/health" in schema["paths"]
    assert "/api/automation-fabric/consent" in schema["paths"]
    assert "/api/automation-fabric/execute" in schema["paths"]

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()


def test_native_auth_header_lookup_is_case_insensitive() -> None:
    assert _header_value({"Authorization": "Bearer token"}, "authorization") == "Bearer token"
    assert _header_value({"userId": "507f1f77bcf86cd799439011"}, "USERID") == "507f1f77bcf86cd799439011"


def test_native_fastapi_routes_preserve_trusted_origin_cors() -> None:
    response = client.options(
        "/api/chat/",
        headers={
            "Origin": "https://revelacode.co.ke",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == "https://revelacode.co.ke"
    assert "Authorization" in response.headers.get("Access-Control-Allow-Headers", "")


def test_untrusted_origin_is_not_reflected_by_native_fastapi_routes() -> None:
    response = client.options(
        "/api/chat/",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("Access-Control-Allow-Origin") != "https://untrusted.example"


def test_explain_route_preserves_response_contract() -> None:
    response = client.post("/", json={"answer": "Evidence supports this claim."})
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": {
            "answer": "Evidence supports this claim.",
            "explanation": "Explainability module active ✅ (upgrade logic later).",
            "confidence": "medium",
        },
    }


def test_explain_route_rejects_empty_answer() -> None:
    response = client.post("/", json={"answer": "  "})
    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "message": "answer is required",
    }


def test_hub_catalog_is_served_by_fastapi() -> None:
    response = client.get("/api/revelaai/hubs/")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "regex-cache-local-json"
    assert isinstance(body["hubs"], list)


def test_hub_respond_preserves_session_validation_contract() -> None:
    response = client.post(
        "/api/revelaai/hubs/respond",
        json={"message": "Hello from the migration test"},
    )
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "sessionId is required."}
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_living_brain_health_is_native_fastapi() -> None:
    response = client.get("/api/revelaai/v2/health")
    assert response.status_code == 200
    assert response.json()["engine"] == "revelaai-local-global-brain-v2"


def test_primary_chat_still_requires_identity() -> None:
    response = client.post("/api/chat/", json={"message": "hello"})
    assert response.status_code in (401, 503)
    assert response.json().get("status") == "error"


def test_main_ai_route_rejects_empty_message_before_provider_calls() -> None:
    response = client.post("/ai", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_MESSAGE"
    assert response.headers.get("X-Request-ID")


def test_main_ai_route_rejects_invalid_image_options() -> None:
    response = client.post("/ai", json={"message": "Explain gravity", "width": "not-a-number"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE_OPTIONS"


def test_native_voice_requires_audio_upload() -> None:
    response = client.post("/voice")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUDIO_REQUIRED"


def test_live_vision_still_requires_identity() -> None:
    response = client.post("/api/vision/analyze", json={})
    assert response.status_code in (401, 503)
    assert response.json().get("status") == "error"


def test_smart_memory_routes_require_identity() -> None:
    response = client.post("/api/memory/chat", json={"userMessage": "remember this"})
    assert response.status_code in (401, 503)
    assert response.json().get("status") == "error"

    idea_list = client.get("/api/memory/ideas/507f1f77bcf86cd799439011")
    assert idea_list.status_code in (401, 503)
    assert idea_list.json().get("status") == "error"


def test_core_mesh_routes_keep_authentication_boundary() -> None:
    response = client.get("/api/core-mesh/dashboard")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"

    proposal = client.post("/api/core-mesh/genesis/invent", json={"demand": "test"})
    assert proposal.status_code == 401
    assert proposal.json()["error"]["code"] == "authentication_required"

    known = client.get("/v1/learn/known")
    assert known.status_code == 401
    assert known.json()["error"]["code"] == "authentication_required"



def test_native_research_validates_query_and_returns_source_results(monkeypatch) -> None:
    from fastapi_routes import research as research_module

    monkeypatch.setattr(
        research_module,
        "_search_feeds",
        lambda query: [{"source": "test", "title": f"Result for {query}", "url": "https://example.org", "snippet": "test"}],
    )
    invalid = client.post("/api/research", json={"query": "   "})
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "query is required"}

    response = client.post("/api/research", json={"query": "climate"})
    assert response.status_code == 200
    assert response.json()["query"] == "climate"
    assert response.json()["realtime"] is True
    assert response.json()["sources"][0]["title"] == "Result for climate"


def test_native_users_directory_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setenv("REVELAAI_ENABLE_PROTOTYPE_USERS_API", "false")
    response = client.post("/api/users", json={"name": "Blocked"})
    assert response.status_code == 503
    assert response.json()["status"] == "disabled"


def test_native_users_directory_create_get_and_validation(monkeypatch) -> None:
    monkeypatch.setenv("REVELAAI_ENABLE_PROTOTYPE_USERS_API", "true")
    from fastapi_routes.users import USERS

    USERS.clear()
    invalid = client.post("/api/users", json={"email": "test@example.org"})
    assert invalid.status_code == 400
    assert invalid.json() == {"status": "error", "message": "User name is required"}

    created = client.post(
        "/api/users",
        json={"name": "Migration Test", "email": "test@example.org"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "success"
    assert body["data"]["name"] == "Migration Test"
    assert body["data"]["email"] == "test@example.org"
    user_id = body["data"]["_id"]

    retrieved = client.get(f"/api/users/{user_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["data"]["_id"] == user_id

    missing = client.get("/api/users/000000000000000000000000")
    assert missing.status_code == 404
    assert missing.json() == {"status": "error", "message": "User not found"}


def test_native_system_routes_keep_response_contracts() -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "revelaai"
    assert root.json()["message"] == "RevelaAI is live."

    capabilities = client.get("/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["status"] == "success"
    assert {"text", "image_generation", "online_research", "pdf", "voice", "ecosystem"} <= set(body["capabilities"])

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers.get("X-Request-ID")
    assert health.headers.get("X-Content-Type-Options") == "nosniff"

    ready = client.get("/ready")
    assert ready.status_code in (200, 503)
    assert ready.json()["status"] in ("ready", "degraded")


def test_automation_fabric_health_and_privileged_routes() -> None:
    health = client.get("/api/automation-fabric/health")
    assert health.status_code == 200
    assert health.json()["module"] == "revelaai-automation-fabric"
    assert health.json()["generated_code_autorun"] is False
    assert health.json()["hardware_actuation"] is False

    tools = client.get("/api/automation-fabric/tools")
    assert tools.status_code in (401, 503)
    assert tools.json().get("status") == "error"

    consent = client.post(
        "/api/automation-fabric/consent",
        json={"accepted": True, "scopes": ["read"]},
    )
    assert consent.status_code in (401, 503)
    assert consent.json().get("status") == "error"


def test_usect_zero_admin_operations_remain_admin_only() -> None:
    activity = client.get("/api/usect-zero/activity")
    assert activity.status_code == 401
    assert activity.json()["code"] == "authentication_required"

    requests = client.get("/api/usect-zero/keys/requests")
    assert requests.status_code == 401
    assert requests.json()["code"] == "authentication_required"

    invalid_filter = client.get("/api/usect-zero/keys/requests?status=unknown")
    assert invalid_filter.status_code == 400
    assert invalid_filter.json()["code"] == "invalid_status_filter"


def test_usect_zero_health_is_explicitly_disabled_without_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("USECT_ZERO_ENABLED", "false")
    response = client.get("/api/usect-zero/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "disabled"
    assert body["module"] == "usect-zero"
    assert body["enabled"] is False
    assert body["model_free"] is True


def test_meta_engineer_privileged_routes_keep_authoritative_admin_gate() -> None:
    calls = [
        client.get("/api/meta-engineer/scan"),
        client.post("/api/meta-engineer/propose", json={"spec": "test"}),
        client.post("/api/meta-engineer/approve/example-id"),
        client.get("/api/meta-engineer/audit"),
        client.post("/api/meta-engineer/pruner/audit"),
    ]
    for response in calls:
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_required"


def test_meta_engineer_health_keeps_status_contract() -> None:
    response = client.get("/api/meta-engineer/health")
    assert response.status_code == 200
    body = response.json()
    assert body["module"] == "meta-engineer"
    assert body["candidate_execution"] is False
    assert body["auto_deploy"] is False
    assert set(body["checks"]) == {
        "proposal_generator", "sandbox_pytest", "sandbox_memory_monitor", "audit_storage"
    }


def test_agi_brain_os_routes_keep_authoritative_admin_gate() -> None:
    requests = [
        client.get("/api/agi/brain-os/status"),
        client.post("/api/agi/brain-os/outcomes", json={"category": "chat", "success": True}),
        client.post("/api/agi/brain-os/routing/shadow-evaluate", json={}),
        client.get("/api/agi/brain-os/heal/actions"),
        client.post("/api/agi/brain-os/heal/actions/simulate", json={}),
        client.post("/api/agi/brain-os/heal/diagnose"),
        client.get("/api/agi/brain-os/engineering/guardrails"),
    ]
    for response in requests:
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_required"


def test_sci_core_routes_keep_authoritative_admin_boundary() -> None:
    calls = [
        client.get("/api/sci/shield/dashboard"),
        client.get("/api/sci/shield/status"),
        client.post("/api/sci/shield/scan"),
        client.post("/api/sci/research", json={"query": "science"}),
        client.post("/api/sci/disaster/simulate", json={"type": "db_down"}),
        client.post("/api/sci/lab/prototype", json={"domain": "software", "spec": "safe calculator"}),
    ]
    for response in calls:
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_required"


def test_agi_manifest_and_status_routes_preserve_shape() -> None:
    manifest = client.get("/api/agi/manifest")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["identity"]["name"] == "RevelaAI"
    assert body["persistence"]["collection"] == "agi_manifest"

    status = client.get("/api/agi/status")
    assert status.status_code == 200
    body = status.json()
    assert body["name"] == "RevelaAI"
    assert "database" in body
    assert "all_modules_present" in body


def test_whatsapp_verification_route_preserves_token_boundary() -> None:
    from fastapi_routes.whatsapp import VERIFY_TOKEN

    verified = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "migration-challenge",
        },
    )
    assert verified.status_code == 200
    assert verified.text == "migration-challenge"

    rejected = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "not-the-token",
            "hub.challenge": "migration-challenge",
        },
    )
    assert rejected.status_code == 403
    assert rejected.text == "Verification failed"


def test_whatsapp_ignores_webhook_notifications_without_messages() -> None:
    response = client.post(
        "/webhook/whatsapp",
        json={"entry": [{"changes": [{"value": {}}]}]},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "no message"}


def test_native_stream_route_rejects_empty_message_before_provider_calls() -> None:
    response = client.post("/ai/stream", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_MESSAGE"
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
