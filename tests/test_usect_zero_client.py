"""Configuration and fail-closed behavior tests for the USECT-ZERO HTTP client."""
from __future__ import annotations

import pytest

from services import usect_zero_client as client


@pytest.fixture(autouse=True)
def clear_zero_configuration(monkeypatch):
    for name in (
        "USECT_ZERO_URL",
        "USECT_ZERO_BASE_URL",
        "USECT_ZERO_ADMIN_TOKEN",
        "RENDER",
        "RENDER_SERVICE_ID",
        "RENDER_EXTERNAL_URL",
        "K_SERVICE",
        "DYNO",
    ):
        monkeypatch.delenv(name, raising=False)


def test_url_alias_is_supported(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "zero.internal:10000")
    assert client._base_url() == "http://zero.internal:10000"


def test_primary_url_takes_precedence_over_alias(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_URL", "https://zero.example.test")
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "http://legacy.internal:10000")
    assert client._base_url() == "https://zero.example.test"


def test_production_without_url_fails_closed(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-example")
    with pytest.raises(client.USECTZeroConfigurationError, match="Set USECT_ZERO_URL"):
        client._base_url()


def test_local_development_keeps_loopback_default():
    assert client._base_url() == "http://127.0.0.1:8780"


def test_admin_token_is_read_from_server_environment(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ADMIN_TOKEN", "test-only-token")
    assert client._admin_token() == "test-only-token"


def test_connection_failure_is_reported_as_zero_unavailable(monkeypatch):
    import requests

    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setenv("USECT_ZERO_URL", "http://zero.internal:8780")

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(client.requests, "request", fail_request)
    with pytest.raises(client.USECTZeroUnavailable, match="service is unavailable"):
        client.request_core("GET", "/v1/health")


def test_device_token_is_forwarded_only_in_its_dedicated_header(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_ENABLED", "true")
    monkeypatch.setenv("USECT_ZERO_URL", "http://zero.internal:8780")
    captured = {}

    class FakeResponse:
        status_code = 200

        def iter_content(self, chunk_size):
            yield b'{"status":"ok"}'

        def close(self):
            return None

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(client.requests, "request", fake_request)
    reply = client.request_core(
        "GET", "/v1/devices/0123456789abcdef01234567/read",
        device_token="uzd_test-token",
    )
    assert reply.status_code == 200
    assert captured["headers"]["X-Device-Token"] == "uzd_test-token"
    assert "Authorization" not in captured["headers"]
    assert "X-Admin-Token" not in captured["headers"]
