from __future__ import annotations

from unittest.mock import patch

from ai import ai_client, tool_registry
from services import ai_service


def _manifest(*, risk_tier: int = 0) -> dict:
    network = risk_tier == 1
    return {
        "schema_version": "genesis.tool-manifest.v1",
        "name": "safe_tool",
        "version": "1.0.0",
        "language": "go",
        "entrypoint": "code.go",
        "input_schema": tool_registry._RUNTIME_INPUT_SCHEMA,
        "output_schema": tool_registry._RUNTIME_OUTPUT_SCHEMA,
        "risk_tier": risk_tier,
        "permissions": {
            "network": network,
            "filesystem": False,
            "secrets": False,
            "hardware": False,
        },
        "timeout_ms": 10000,
        "memory_bytes": 134217728,
    }


def _active_item(*, risk_tier: int = 0, signature_valid: bool = True, evidence_passed: bool = True) -> dict:
    manifest = _manifest(risk_tier=risk_tier)
    return {
        "name": manifest["name"],
        "version": manifest["version"],
        "artifact_hash": "a" * 64,
        "signature": "ed25519:" + ("b" * 128 if signature_valid else "invalid"),
        "risk_tier": manifest["risk_tier"],
        "active": True,
        "manifest": manifest,
        "sandbox_evidence": {"passed": evidence_passed, "isolation_level": "test-only"},
    }


def _call(**arguments) -> list[dict]:
    return [{
        "name": "genesis_safe_tool",
        "arguments": {"action": "inspect the requested result", **arguments},
    }]


def _set_operator(monkeypatch, allowed: str = "operator-1") -> None:
    monkeypatch.setenv("CORE_MESH_ADMIN_USER_IDS", allowed)
    monkeypatch.delenv("META_ENGINEER_ADMIN_USER_IDS", raising=False)


def test_operator_can_dispatch_only_active_signed_tier_zero_tool(monkeypatch):
    _set_operator(monkeypatch)
    seen = {}

    def execute(name, version, artifact_hash, arguments):
        seen.update(name=name, version=version, artifact_hash=artifact_hash, arguments=arguments)
        return {"status": "success", "result": {"status": "completed", "summary": "read-only check"}}

    monkeypatch.setattr(ai_service, "execute_active_tool", execute)
    result = ai_service._execute_genesis_function_calls(
        _call(inputs={"scope": "workspace"}),
        [_active_item()],
        "operator-1",
    )

    assert result["status"] == "executed"
    assert result["executed"] is True
    assert result["tool"] == "safe_tool"
    assert result["risk_tier"] == 0
    assert result["automatic_merge"] is False
    assert result["candidate_source_execution"] is False
    assert seen["name"] == "safe_tool"
    assert seen["version"] == "1.0.0"
    assert seen["artifact_hash"] == "a" * 64
    assert seen["arguments"] == {
        "action": "inspect the requested result",
        "inputs": {"scope": "workspace"},
        "consent": False,
    }


def test_gemini_key_value_pairs_are_normalized_to_existing_runtime_input_map(monkeypatch):
    _set_operator(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        ai_service,
        "execute_active_tool",
        lambda name, version, artifact_hash, arguments: (
            seen.update(arguments=arguments) or {"status": "success", "result": {"summary": "ok"}}
        ),
    )

    result = ai_service._execute_genesis_function_calls(
        _call(inputs=[
            {"key": "county", "value": "Mombasa"},
            {"key": "crop", "value": "maize"},
        ]),
        [_active_item()],
        "operator-1",
    )

    assert result["status"] == "executed"
    assert seen["arguments"]["inputs"] == {"county": "Mombasa", "crop": "maize"}


def test_duplicate_gemini_input_keys_are_rejected(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    result = ai_service._execute_genesis_function_calls(
        _call(inputs=[
            {"key": "county", "value": "Mombasa"},
            {"key": "county", "value": "Nairobi"},
        ]),
        [_active_item()],
        "operator-1",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "tool_arguments_failed_safety_validation"
    assert called == []


def test_non_operator_cannot_dispatch_and_never_calls_genesis(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    result = ai_service._execute_genesis_function_calls(
        _call(),
        [_active_item()],
        "ordinary-user",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "operator_not_authorized"
    assert result["executed"] is False
    assert called == []


def test_higher_risk_tool_requires_dashboard_approval(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    result = ai_service._execute_genesis_function_calls(
        _call(),
        [_active_item(risk_tier=1)],
        "operator-1",
    )

    assert result["status"] == "approval_required"
    assert result["risk_tier"] == 1
    assert result["executed"] is False
    assert called == []


def test_model_arguments_cannot_claim_consent_or_add_unapproved_fields(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    for extra in ({"consent": True}, {"shell": "run arbitrary command"}, {"inputs": {"bad": ["not", "a", "string"]}}):
        result = ai_service._execute_genesis_function_calls(
            _call(**extra),
            [_active_item()],
            "operator-1",
        )
        assert result["status"] == "blocked"
        assert result["reason"] == "tool_arguments_failed_safety_validation"

    assert called == []


def test_tool_must_match_a_verified_signed_registry_item(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    for item in (_active_item(signature_valid=False), _active_item(evidence_passed=False)):
        result = ai_service._execute_genesis_function_calls(
            _call(),
            [item],
            "operator-1",
        )
        assert result["status"] == "blocked"
        assert result["reason"] == "tool_not_in_verified_active_registry"

    assert called == []


def test_invalid_manifest_is_rejected_before_genesis_invocation(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    item = _active_item()
    item["manifest"]["input_schema"] = {
        "type": "object",
        "properties": {"arbitrary": {"type": "string"}},
        "additionalProperties": False,
    }
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    result = ai_service._execute_genesis_function_calls(
        _call(),
        [item],
        "operator-1",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "tool_not_in_verified_active_registry"
    assert called == []


def test_gemini_function_call_with_non_stop_finish_reason_is_rejected():
    from ai.ai_client import AIClientError

    response = {
        "candidates": [{
            "content": {"parts": [{
                "functionCall": {"name": "genesis_safe_tool", "args": {"action": "inspect"}}
            }]},
            "finishReason": "MAX_TOKENS",
        }]
    }
    try:
        ai_client._extract_gemini_function_calls(response)
    except AIClientError as exc:
        assert exc.error_code == "gemini_function_call_not_completed"
    else:
        raise AssertionError("incomplete function call must not be returned for execution")


def test_multiple_model_tool_calls_are_rejected_without_execution(monkeypatch):
    _set_operator(monkeypatch)
    called = []
    monkeypatch.setattr(ai_service, "execute_active_tool", lambda *args, **kwargs: called.append(args))

    result = ai_service._execute_genesis_function_calls(
        _call() * 2,
        [_active_item()],
        "operator-1",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "exactly_one_tool_call_required"
    assert called == []


def test_proposal_only_remote_result_is_not_reported_as_direct_execution(monkeypatch):
    _set_operator(monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "execute_active_tool",
        lambda *args, **kwargs: {"status": "proposal_only", "proposal_id": "p-1"},
    )

    result = ai_service._execute_genesis_function_calls(
        _call(),
        [_active_item()],
        "operator-1",
    )

    assert result["status"] == "proposal_only"
    assert result["remote_status"] == "proposal_only"
    assert result["invocation_confirmed"] is True
    assert result["executed"] is False


def test_genesis_declarations_strip_unsupported_gemini_schema_keywords():
    declarations = tool_registry.gemini_function_declarations([_active_item()])
    assert len(declarations) == 1

    supported = {
        "type", "nullable", "required", "format", "description",
        "properties", "items", "enum", "anyOf", "$ref", "$defs",
    }

    def walk(schema):
        if not isinstance(schema, dict):
            return
        assert set(schema).issubset(supported)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for property_schema in properties.values():
                walk(property_schema)
        items = schema.get("items")
        if isinstance(items, dict):
            walk(items)
        definitions = schema.get("$defs")
        if isinstance(definitions, dict):
            for definition in definitions.values():
                walk(definition)
        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            for variant in any_of:
                walk(variant)

    walk(declarations[0]["parameters"])
    properties = declarations[0]["parameters"]["properties"]
    assert properties["action"]["type"] == "string"
    assert properties["inputs"]["type"] == "array"
    assert properties["inputs"]["items"]["required"] == ["key", "value"]
    assert "consent" not in properties
    assert "additionalProperties" not in declarations[0]["parameters"]


def test_gemini_function_call_response_is_extracted_without_fabricated_text():
    response = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "genesis_safe_tool",
                        "args": {"action": "inspect", "inputs": {}, "consent": False},
                    }
                }]
            },
            "finishReason": "STOP",
        }],
        "usageMetadata": {"totalTokenCount": 20},
    }
    calls = ai_client._extract_gemini_function_calls(response)
    assert calls == [{
        "name": "genesis_safe_tool",
        "arguments": {"action": "inspect", "inputs": {}, "consent": False},
    }]


def test_gemini_request_payload_contains_bounded_function_declarations(monkeypatch):
    monkeypatch.setattr(ai_client, "GEMINI_ENABLED", True)
    monkeypatch.setattr(ai_client, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(ai_client, "GEMINI_FALLBACK_MODEL", "")
    observed = {}

    class FakeResponse:
        ok = True
        status_code = 200

        def json(self):
            return {
                "candidates": [{
                    "content": {
                        "parts": [{
                            "functionCall": {
                                "name": "genesis_safe_tool",
                                "args": {"action": "inspect", "inputs": {}, "consent": False},
                            }
                        }]
                    },
                    "finishReason": "STOP",
                }]
            }

    def fake_post(url, **kwargs):
        observed.update(url=url, kwargs=kwargs)
        return FakeResponse()

    declarations = [{
        "name": "genesis_safe_tool",
        "description": "Use the verified read-only signed tool.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string"}}},
    }]
    monkeypatch.setattr(ai_client.requests, "post", fake_post)

    result = ai_client._request_gemini(
        model="test-model",
        messages=[{"role": "user", "content": "inspect"}],
        function_declarations=declarations,
    )

    payload = observed["kwargs"]["json"]
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "genesis_safe_tool"
    assert payload["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert result["candidates"][0]["content"]["parts"][0]["functionCall"]["name"] == "genesis_safe_tool"


def test_ask_hf_returns_gemini_tool_call_metadata_to_dispatcher(monkeypatch):
    monkeypatch.setattr(ai_client, "GEMINI_ENABLED", True)
    monkeypatch.setattr(ai_client, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(ai_client, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(ai_client, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(ai_client, "TEXT_PROVIDER_ORDER", ["gemini"])
    monkeypatch.setattr(ai_client, "_provider_enabled", lambda provider: provider == "gemini")
    monkeypatch.setattr(
        ai_client,
        "_request_gemini",
        lambda **kwargs: {
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {
                        "name": "genesis_safe_tool",
                        "args": {"action": "inspect", "inputs": {}, "consent": False},
                    }
                }]},
                "finishReason": "STOP",
            }],
        },
    )
    declarations = [{
        "name": "genesis_safe_tool",
        "description": "Read-only signed tool.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string"}}},
    }]

    result = ai_client.ask_hf(
        "Please run the safe tool",
        gemini_function_declarations=declarations,
    )

    assert result["success"] is True
    assert result["response"] == ""
    assert result["tool_calls"][0]["name"] == "genesis_safe_tool"
