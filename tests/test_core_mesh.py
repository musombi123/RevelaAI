import pytest

import ai.core_mesh as core_mesh


def _online_dashboard():
    return {
        "status": "online",
        "cores": {
            "zero": {"id": "USECT-ZERO", "status": "online", "reachable": True, "version": "test"},
            "one": {"id": "USECT-ONE", "status": "online", "reachable": True, "version": "test"},
            "two": {"id": "USECT-TWO", "status": "online", "reachable": True, "version": "test"},
        },
    }


def test_normal_chat_does_not_trigger_core_health_fanout(monkeypatch):
    monkeypatch.setattr(core_mesh, "_cache_value", None)

    def fail_if_probed(*args, **kwargs):
        raise AssertionError("ordinary chat must not run live core probes")

    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", fail_if_probed)
    result = core_mesh.orchestrator_core_context("Explain photosynthesis in simple terms.")

    assert result["selected_core"] == "orchestrator"
    assert result["mesh_status"] == "not_probed"
    assert result["cores"]["two"]["reachable"] is None
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["automatic_merge"] is False


def test_invention_request_routes_advisorially_to_genesis(monkeypatch):
    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", lambda: _online_dashboard())

    result = core_mesh.orchestrator_core_context(
        "Create a tool that summarizes school documents.",
        domain="general",
        intent="engineering",
    )

    assert result["selected_core"] == "core-one"
    assert result["cores"]["one"]["reachable"] is True
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["human_approval_required"] is True


def test_improvement_request_routes_advisorially_to_infinite_mind(monkeypatch):
    monkeypatch.setattr(core_mesh, "get_core_mesh_dashboard", lambda: _online_dashboard())

    result = core_mesh.orchestrator_core_context(
        "Improve core performance by reducing repeated scans.",
        domain="general",
        intent="engineering",
    )

    assert result["selected_core"] == "core-two"
    assert result["cores"]["two"]["reachable"] is True
    assert result["safety"]["operation_executed"] is False
    assert result["safety"]["automatic_merge"] is False


def test_render_private_hostport_is_normalized_and_allowed(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "usect-zero-core:10000")
    base = core_mesh._base_url("USECT_ZERO_BASE_URL", "")
    assert base == "http://usect-zero-core:10000"
    core_mesh._validate_base(base)


def test_invalid_hostport_is_not_normalized(monkeypatch):
    monkeypatch.setenv("USECT_ZERO_BASE_URL", "usect-zero-core/path")
    base = core_mesh._base_url("USECT_ZERO_BASE_URL", "")
    assert base == "usect-zero-core/path"
    with pytest.raises(core_mesh.CoreMeshError):
        core_mesh._validate_base(base)


def test_off_host_http_core_url_is_rejected():
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh._validate_base("http://core-service.example.com")
    assert error.value.code == "core_service_tls_required"


def test_only_allowlisted_proposal_fields_are_returned():
    proposal = core_mesh._public_proposal({
        "id": "proposal-123",
        "tool_name": "school_doc_summary",
        "status": "await_merge",
        "source_code": "DO NOT FORWARD THIS",
        "admin_token": "never-return-this",
    })

    assert proposal["id"] == "proposal-123"
    assert proposal["human_approval_required"] is True
    assert proposal["automatic_execution"] is False
    assert proposal["automatic_merge"] is False
    assert "source_code" not in proposal
    assert "admin_token" not in proposal



def test_genesis_invention_calls_genesis_service_directly(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-genesis-token")
    monkeypatch.delenv("MIND_ADMIN_TOKEN", raising=False)
    observed = {}

    def fake_request(base, path, **kwargs):
        observed.update(base=base, path=path, kwargs=kwargs)
        return {"id": "proposal-1", "name": "safe_tool", "status": "await_merge"}

    monkeypatch.setattr(core_mesh, "_request_json", fake_request)
    result = core_mesh.propose_genesis_invention("Create a safe document summarizer")

    assert observed["base"] == "https://genesis.example.com"
    assert observed["path"] == "/v1/genesis/invent"
    assert observed["kwargs"]["headers"]["X-Genesis-Token"] == "test-genesis-token"
    assert "X-Mind-Token" not in observed["kwargs"]["headers"]
    assert result["human_approval_required"] is True


def test_genesis_unreachable_is_explicit_and_does_not_fallback_to_mind(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-genesis-token")

    def unavailable(*args, **kwargs):
        raise core_mesh.CoreMeshError(
            "Core service is unreachable.",
            status_code=502,
            code="core_service_unreachable",
        )

    monkeypatch.setattr(core_mesh, "_request_json", unavailable)
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh.propose_genesis_invention("Create a safe document summarizer")
    assert error.value.code == "genesis_unavailable"
    assert error.value.status_code == 503


def test_genesis_documented_read_routes_use_direct_core_one_url(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    calls = []

    def fake_request(base, path, **kwargs):
        calls.append((base, path, kwargs))
        return {"status": "ok", "path": path}

    monkeypatch.setattr(core_mesh, "_request_json", fake_request)
    assert core_mesh.get_genesis_status()["status"] == "ok"
    assert core_mesh.list_genesis_proposals()["path"] == "/v1/genesis/tools"
    proposal = core_mesh.get_genesis_proposal("safe_tool")
    assert proposal["status"] == "ok"
    assert calls[2][1] == "/v1/genesis/tools/safe_tool"
    guide = core_mesh.get_genesis_hardware_guide("safe_tool", country="KE", language="sw")
    assert guide["path"].startswith("/v1/genesis/tools/safe_tool/hardware_guide?")
    assert "country=KE" in guide["path"] and "lang=sw" in guide["path"]
    plan = core_mesh.get_genesis_capability_plan("safe_tool")
    assert plan["path"] == "/v1/genesis/tools/safe_tool/capability_plan"
    assert len(calls) == 5
    assert all(call[0] == "https://genesis.example.com" for call in calls)
    assert all(call[2]["headers"]["X-Genesis-Token"] == "test-token" for call in calls)


def test_genesis_queue_key_and_rvx_use_expected_http_contracts(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    calls = []

    def fake_request(base, path, **kwargs):
        calls.append((path, kwargs))
        return {"status": "queued"}

    monkeypatch.setattr(core_mesh, "_request_json", fake_request)
    queued = core_mesh.queue_genesis_demand(
        "Create a safe school document index",
        country="KE",
        language="sw",
    )
    assert queued["status"] == "queued"
    assert calls[0][0] == "/v1/genesis/queue"
    assert calls[0][1]["method"] == "POST"
    assert calls[0][1]["payload"]["demand"] == "Create a safe school document index"
    assert core_mesh.get_genesis_key_request_info()["status"] == "queued"
    key_request = core_mesh.request_genesis_provider_key("gateway-test", "Request a provider key for approved testing")
    assert key_request["status"] == "queued"
    assert calls[2][0] == "/v1/genesis/key"
    assert calls[2][1]["payload"]["client_id"] == "gateway-test"
    assert core_mesh.compile_genesis_rvx("module safe_tool").get("status") == "queued"
    assert calls[3][0] == "/v1/rvx/compile"
    assert calls[3][1]["method"] == "POST"
    assert calls[3][1]["payload"]["source"] == "module safe_tool"


def test_genesis_detail_rejects_uppercase_resource_names_before_network(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(
        core_mesh,
        "_genesis_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not be called")),
    )
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh.get_genesis_proposal("Safe_Tool")
    assert error.value.code == "invalid_tool_name"
    assert error.value.status_code == 400


def test_genesis_clients_fail_explicitly_when_gateway_credential_missing(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.delenv("GENESIS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GENESIS_TOKEN", raising=False)
    with pytest.raises(core_mesh.CoreMeshError) as error:
        core_mesh.get_genesis_status()
    assert error.value.code == "genesis_unavailable"
    assert error.value.status_code == 503


def test_genesis_stream_fails_with_explicit_unavailable_status_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GENESIS_BASE_URL", raising=False)
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")
    with pytest.raises(core_mesh.CoreMeshError) as error:
        next(core_mesh.iter_genesis_events(max_events=1))
    assert error.value.code in {"core_service_not_configured", "genesis_unavailable"}


def test_genesis_gateway_routes_are_registered():
    from fastapi_routes.core_mesh import router

    methods_by_path = {
        route.path: set(route.methods or set())
        for route in router.routes
        if getattr(route, "methods", None)
    }
    expected = {
        "/api/core-mesh/genesis/status": {"GET"},
        "/api/core-mesh/genesis/proposals": {"GET"},
        "/api/core-mesh/genesis/proposals/{name}": {"GET"},
        "/api/core-mesh/genesis/tools/{name}/hardware-guide": {"GET"},
        "/api/core-mesh/genesis/tools/{name}/capability-plan": {"GET"},
        "/api/core-mesh/genesis/queue": {"POST"},
        "/api/core-mesh/genesis/key": {"GET"},
        "/api/core-mesh/genesis/key/request": {"POST"},
        "/api/core-mesh/genesis/rvx/compile": {"POST"},
        "/api/core-mesh/genesis/events": {"GET"},
        "/api/core-mesh/tools": {"GET"},
        "/api/core-mesh/tools/registry": {"GET"},
        "/api/core-mesh/tools/execute": {"POST"},
        "/api/core-mesh/tools/{name}/publish": {"POST"},
        "/api/core-mesh/tools/{name}/{version}/{artifact_hash}/activate": {"POST"},
        "/api/core-mesh/tools/{name}/{version}/{artifact_hash}/confirm": {"POST"},
        "/api/core-mesh/tools/{name}/deactivate": {"POST"},
        "/api/core-mesh/tools/{name}/rollback": {"POST"},
    }
    for path, methods in expected.items():
        actual = methods_by_path.get(path)
        if actual is not None:
            actual = actual - {"HEAD"}  # Starlette may add HEAD automatically for GET routes.
        assert actual == methods, f"route contract mismatch for {path}: got {actual}"


def test_genesis_proposal_details_redact_raw_research_and_source(monkeypatch):
    payload = {
        "name": "safe_tool",
        "status": "await_merge",
        "hardware_guide_url": "/v1/genesis/tools/safe_tool/hardware_guide",
        "proposal": {
            "invention_id": "inv-1",
            "created_at": "2026-10-20T00:00:00Z",
            "status": "await_merge",
            "specification": {
                "name": "safe_tool",
                "title": "Safe tool",
                "purpose": "Summarize approved documents",
                "demand": "PRIVATE USER DEMAND",
                "capabilities": ["summarize"],
            },
            "research": {
                "mode": "offline",
                "collected_at": "2026-10-20T00:00:00Z",
                "sources": [{"url": "https://example.invalid", "snippet": "PRIVATE RAW SOURCE"}],
                "findings": ["PRIVATE RAW FINDING"],
            },
            "source_code": "PRIVATE SOURCE CODE",
        },
        "admin_token": "PRIVATE TOKEN",
    }
    monkeypatch.setattr(core_mesh, "_genesis_request", lambda path: payload)
    result = core_mesh.get_genesis_proposal("safe_tool")
    serialized = str(result)
    assert result["proposal"]["specification"]["title"] == "Safe tool"
    assert result["proposal"]["research_summary"]["source_count"] == 1
    assert result["proposal"]["research_summary"]["finding_count"] == 1
    assert "PRIVATE USER DEMAND" not in serialized
    assert "PRIVATE RAW SOURCE" not in serialized
    assert "PRIVATE RAW FINDING" not in serialized
    assert "PRIVATE SOURCE CODE" not in serialized
    assert "PRIVATE TOKEN" not in serialized
    assert result["automatic_execution"] is False
    assert result["automatic_merge"] is False


def test_genesis_event_stream_decodes_byte_lines(monkeypatch):
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis.example.com")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-token")

    class FakeResponse:
        status_code = 200
        ok = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def iter_lines(self, decode_unicode=False):
            assert decode_unicode is False
            yield b"event: status"
            yield b'data: {"status":"ok"}'
            yield b""

    monkeypatch.setattr(core_mesh.requests, "get", lambda *args, **kwargs: FakeResponse())
    events = list(core_mesh.iter_genesis_events(max_events=1))
    assert events == [{"status": "ok", "type": "status"}]


def test_core_mesh_authenticated_requests_bypass_environment_proxies(monkeypatch):
    observed = {}

    class FakeResponse:
        content = b'{"status":"ok"}'
        status_code = 200
        ok = True

        def json(self):
            return {"status": "ok"}

    def fake_request(method, url, **kwargs):
        observed.update(method=method, url=url, kwargs=kwargs)
        return FakeResponse()

    monkeypatch.setattr(core_mesh.requests, "request", fake_request)
    result = core_mesh._request_json(
        "https://genesis.example.com",
        "/v1/genesis/status",
        headers={"X-Genesis-Token": "test-token"},
    )
    assert result == {"status": "ok"}
    assert observed["kwargs"]["headers"]["X-Genesis-Token"] == "test-token"
    assert observed["kwargs"]["proxies"] == {"http": "", "https": ""}
