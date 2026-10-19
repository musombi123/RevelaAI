"""Regression tests for the FastAPI ASGI migration entry point and route parity."""
from fastapi.testclient import TestClient

from asgi import app


client = TestClient(app)


def test_fastapi_health_endpoint_and_security_headers() -> None:
    response = client.get("/_fastapi/health")
    assert response.status_code == 200
    assert response.json()["runtime"] == "fastapi"
    assert response.json()["service"] == "revelaai"
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_fastapi_openapi_and_docs_are_available() -> None:
    schema_response = client.get("/openapi.json")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["info"]["title"] == "RevelaAI API"
    assert "/api/chat" in schema["paths"]
    assert "/api/vision/analyze" in schema["paths"]
    assert "/api/revelaai/v2/brain/chat" in schema["paths"]
    assert "/api/revelaai/hubs/" in schema["paths"]

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()


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


def test_live_vision_still_requires_identity() -> None:
    response = client.post("/api/vision/analyze", json={})
    assert response.status_code in (401, 503)
    assert response.json().get("status") == "error"


def test_existing_flask_route_is_forwarded_with_auth_contract() -> None:
    # This authenticated endpoint remains on the WSGI bridge until its router
    # is migrated; unauthenticated access must not become less restrictive.
    response = client.get("/api/core-mesh/dashboard")
    assert response.status_code == 401
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
