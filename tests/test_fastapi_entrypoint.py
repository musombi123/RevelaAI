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
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "RevelaAI API"

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()


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


def test_existing_flask_route_is_forwarded_with_auth_contract() -> None:
    # This authenticated endpoint must continue to reject unauthenticated calls
    # through the WSGI bridge; the migration must not weaken auth to gain parity.
    response = client.get("/api/core-mesh/dashboard")
    assert response.status_code == 401
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
