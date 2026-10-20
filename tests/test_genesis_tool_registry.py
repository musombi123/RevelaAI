from __future__ import annotations

import json

from ai import tool_registry


def _manifest(*, risk_tier: int = 0, network: bool = False, hardware: bool = False) -> dict:
    return {
        "schema_version": "genesis.tool-manifest.v1",
        "name": "safe_tool",
        "version": "1.0.0",
        "language": "go",
        "entrypoint": "code.go",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "risk_tier": risk_tier,
        "permissions": {
            "network": network,
            "filesystem": False,
            "secrets": False,
            "hardware": hardware,
        },
        "timeout_ms": 10000,
        "memory_bytes": 134217728,
    }


def _active_item(manifest: dict) -> dict:
    return {
        "name": manifest["name"],
        "version": manifest["version"],
        "artifact_hash": "a" * 64,
        "active": True,
        "manifest": manifest,
    }


def test_gemini_declarations_include_only_valid_active_tool_contracts():
    valid = _active_item(_manifest())
    invalid = _active_item(_manifest(risk_tier=0, network=True))
    declarations = tool_registry.gemini_function_declarations([valid, invalid])
    assert len(declarations) == 1
    assert declarations[0]["name"] == "genesis_safe_tool"
    assert declarations[0]["parameters"]["type"] == "object"


def test_prompt_catalog_is_provider_neutral_and_not_executable():
    catalog = json.loads(tool_registry.prompt_based_tool_catalog([_active_item(_manifest())]))
    assert catalog[0]["function"] == "genesis_safe_tool"
    assert "never claim execution" in catalog[0]["description"]


def test_registry_unavailable_does_not_return_empty_success(monkeypatch):
    monkeypatch.delenv("GENESIS_BASE_URL", raising=False)
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    try:
        tool_registry.list_active_tools()
    except tool_registry.GenesisToolRegistryError as exc:
        assert exc.code == "genesis_unavailable"
        assert exc.status_code == 503
    else:
        raise AssertionError("missing Genesis URL must be an explicit unavailable state")


def test_execution_is_delegated_to_genesis_and_bounds_arguments(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.invalid")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    seen = {}

    def fake_request(path, *, method="GET", payload=None):
        seen.update(path=path, method=method, payload=payload)
        return {"status": "success", "result": {"status": "proposal_only"}}

    monkeypatch.setattr(tool_registry, "_request", fake_request)
    result = tool_registry.execute_active_tool(
        "safe_tool", "1.0.0", "a" * 64, {"action": "plan"}
    )
    assert result["status"] == "success"
    assert seen["method"] == "POST"
    assert seen["path"].endswith("/invoke")
    assert seen["payload"]["arguments"] == {"action": "plan"}


def test_execution_rejects_oversized_arguments_before_network(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.invalid")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(
        tool_registry,
        "_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )
    try:
        tool_registry.execute_active_tool(
            "safe_tool", "1.0.0", "a" * 64, {"action": "x", "data": "x" * 70000}
        )
    except tool_registry.GenesisToolRegistryError as exc:
        assert exc.code == "tool_arguments_too_large"
    else:
        raise AssertionError("oversized arguments must be rejected")


def test_provider_context_selects_native_gemini_or_prompt_based_fallback():
    active = _active_item(_manifest())
    gemini = tool_registry.provider_tool_context("gemini", [active])
    assert gemini["mode"] == "native_function_declarations"
    assert gemini["provider"] == "gemini"
    assert gemini["function_declarations"][0]["name"] == "genesis_safe_tool"

    for provider in ("hf", "mvi"):
        result = tool_registry.provider_tool_context(provider, [active])
        assert result["mode"] == "prompt_based"
        assert result["provider"] == provider
        assert "genesis_safe_tool" in result["tool_catalog"]


def test_tier2_confirmation_is_forwarded_as_a_one_use_token(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.invalid")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    seen = {}

    def fake_request(path, *, method="GET", payload=None, extra_headers=None, timeout=8.0):
        seen.update(path=path, method=method, payload=payload, headers=extra_headers, timeout=timeout)
        return {
            "status": "confirmed",
            "confirmation_token": "b" * 64,
            "artifact_hash": "a" * 64,
        }

    monkeypatch.setattr(tool_registry, "_request", fake_request)
    result = tool_registry.confirm_tier2_action(
        "safe_tool",
        "1.0.0",
        "a" * 64,
        {"action": "inspect", "consent": True},
        action_approval_token="test-action-approval",
    )
    assert result["status"] == "confirmed"
    assert seen["path"].endswith("/confirm")
    assert seen["method"] == "POST"
    assert seen["payload"] == {"arguments": {"action": "inspect", "consent": True}}
    assert seen["headers"] == {"X-Genesis-Action-Approval": "test-action-approval"}


def test_confirmation_rejects_invalid_or_oversized_arguments_before_network(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.invalid")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(
        tool_registry,
        "_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )
    try:
        tool_registry.confirm_tier2_action(
            "safe_tool", "1.0.0", "a" * 64,
            {"action": "x", "payload": "x" * 70000},
            action_approval_token="test-action-approval",
        )
    except tool_registry.GenesisToolRegistryError as exc:
        assert exc.code == "invalid_tool_arguments"
    else:
        raise AssertionError("oversized confirmation arguments must be rejected")


def test_render_private_genesis_hostport_is_normalized(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "genesis-core-one:10000")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    base, headers = tool_registry._configuration()
    assert base == "http://genesis-core-one:10000"
    assert headers["X-Genesis-Token"] == "test-token"


def test_public_plain_http_genesis_url_is_rejected(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "http://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    try:
        tool_registry._configuration()
    except tool_registry.GenesisToolRegistryError as exc:
        assert exc.code == "genesis_url_tls_required"
    else:
        raise AssertionError("public Genesis URLs must use HTTPS")


def test_genesis_url_rejects_credentials_and_paths(monkeypatch):
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    for value in (
        "https://user:pass@genesis.example.com",
        "https://genesis.example.com/api",
        "genesis-core-one/not-a-hostport",
        "genesis-core-one:badport",
    ):
        monkeypatch.setenv("GENESIS_BASE_URL", value)
        try:
            tool_registry._configuration()
        except tool_registry.GenesisToolRegistryError:
            continue
        raise AssertionError(f"unsafe Genesis URL must be rejected: {value}")


def test_public_ipv6_http_genesis_url_is_rejected(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "http://[2001:db8::1]:8781")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    try:
        tool_registry._configuration()
    except tool_registry.GenesisToolRegistryError as exc:
        assert exc.code == "genesis_url_tls_required"
    else:
        raise AssertionError("public IPv6 Genesis URLs must use HTTPS")


def test_genesis_registry_request_bypasses_environment_proxies(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    observed = {}

    class FakeResponse:
        content = b'{"tools": []}'
        status_code = 200
        ok = True

        def json(self):
            return {"tools": []}

    def fake_request(method, url, **kwargs):
        observed.update(method=method, url=url, kwargs=kwargs)
        return FakeResponse()

    monkeypatch.setattr(tool_registry.requests, "request", fake_request)
    result = tool_registry._request("/v1/genesis/registry/tools")
    assert result == {"tools": []}
    assert observed["kwargs"]["headers"]["X-Genesis-Token"] == "test-token"
    assert observed["kwargs"]["proxies"] == {"http": "", "https": ""}
