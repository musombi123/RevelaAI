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
