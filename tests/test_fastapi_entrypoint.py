"""Regression tests for the FastAPI ASGI migration entry point."""
from fastapi.testclient import TestClient

from asgi import app


client = TestClient(app)


def test_fastapi_health_endpoint() -> None:
    response = client.get("/_fastapi/health")
    assert response.status_code == 200
    assert response.json()["runtime"] == "fastapi"
    assert response.json()["service"] == "revelaai"


def test_fastapi_openapi_and_docs_are_available() -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "RevelaAI API"

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()


def test_existing_flask_route_is_forwarded_with_auth_contract() -> None:
    # This authenticated endpoint must continue to reject unauthenticated calls
    # through the WSGI bridge; the migration must not weaken auth to gain parity.
    response = client.get("/api/core-mesh/dashboard")
    assert response.status_code == 401
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
