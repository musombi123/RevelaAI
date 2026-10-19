from __future__ import annotations

import json

import pytest

from automation_fabric.engine import AutomationError, create_plan, execute_plan
from automation_fabric.policy import resolve_workspace_path
from automation_fabric import store


def test_math_tool_is_deterministic_and_bounded(tmp_path):
    plan = create_plan(
        "test-user",
        [{"tool": "math.evaluate", "args": {"expression": "(2 + 3) * 4"}}],
        tmp_path,
        db_path=str(tmp_path / "fabric.sqlite3"),
    )
    result = execute_plan(
        "test-user", plan["plan_id"], plan["plan_hash"], approved=True,
        workspace=tmp_path, db_path=str(tmp_path / "fabric.sqlite3"),
    )
    assert result["status"] == "completed"
    assert result["results"][0]["result"]["value"] == 20


def test_math_tool_rejects_code_execution(tmp_path):
    with pytest.raises(AutomationError) as raised:
        create_plan(
            "test-user",
            [{"tool": "math.evaluate", "args": {"expression": "__import__('os').system('whoami')"}}],
            tmp_path,
            db_path=str(tmp_path / "fabric.sqlite3"),
        )
    assert raised.value.code == "invalid_tool_args"


def test_workspace_traversal_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        resolve_workspace_path(tmp_path, "../outside.txt")


def test_write_requires_scope_and_plan_hash(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    plan = create_plan(
        "test-user",
        [{"tool": "workspace.write_text", "args": {"path": "notes/result.txt", "content": "safe hello"}}],
        tmp_path,
        db_path=db,
    )
    with pytest.raises(AutomationError) as no_grant:
        execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db)
    assert no_grant.value.code == "consent_required"

    store.grant_scopes("test-user", ["workspace:write"], reason="test", ttl_seconds=600, db_path=db)
    with pytest.raises(AutomationError) as bad_hash:
        execute_plan("test-user", plan["plan_id"], "0" * 64, approved=True, workspace=tmp_path, db_path=db)
    assert bad_hash.value.code == "plan_hash_mismatch"

    result = execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db)
    assert result["status"] == "completed"
    assert (tmp_path / "notes" / "result.txt").read_text(encoding="utf-8") == "safe hello"


def test_plan_is_one_shot(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    plan = create_plan(
        "test-user",
        [{"tool": "math.evaluate", "args": {"expression": "7 * 6"}}],
        tmp_path, db_path=db,
    )
    execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db)
    with pytest.raises(AutomationError) as raised:
        execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db)
    assert raised.value.code == "plan_not_executable"


def test_hosted_runtime_refuses_device_only_tool(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    plan = create_plan(
        "test-user",
        [{"tool": "hardware.discover", "args": {}}],
        tmp_path, db_path=db, local_mode=False,
    )
    assert plan["execution_target"] == "local_agent_required"
    store.grant_scopes("test-user", ["hardware:discover"], reason="test", ttl_seconds=600, db_path=db)
    with pytest.raises(AutomationError) as raised:
        execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db, local_mode=False)
    assert raised.value.code == "local_agent_required"


def test_scaffold_is_written_as_disabled_proposal_only(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    store.grant_scopes("test-user", ["tools:scaffold", "workspace:write"], reason="test", ttl_seconds=600, db_path=db)
    plan = create_plan(
        "test-user",
        [{"tool": "factory.scaffold_python_tool", "args": {"name": "sample_adapter", "description": "A sample tool adapter."}}],
        tmp_path, db_path=db,
    )
    output = execute_plan("test-user", plan["plan_id"], plan["plan_hash"], approved=True, workspace=tmp_path, db_path=db)
    proposal = tmp_path / "proposals" / "sample_adapter"
    manifest = json.loads((proposal / "manifest.json").read_text(encoding="utf-8"))
    assert output["status"] == "completed"
    assert manifest["enabled"] is False
    assert manifest["status"] == "proposal_only"
    assert "not_implemented" in (proposal / "tool.py").read_text(encoding="utf-8")



def test_research_planning_does_not_resolve_dns_before_consent(monkeypatch):
    from automation_fabric import registry

    def forbidden_dns(*args, **kwargs):
        raise AssertionError("DNS must not run while only planning a tool")

    monkeypatch.setattr(registry.socket, "getaddrinfo", forbidden_dns)
    validated = registry.validate_arguments(
        "research.fetch_public_page",
        {"url": "https://docs.python.org/3/"},
    )
    assert validated["url"] == "https://docs.python.org/3/"

def test_consent_can_be_revoked(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    store.grant_scopes("test-user", ["workspace:read"], reason="test", ttl_seconds=600, db_path=db)
    assert store.has_scope("test-user", "workspace:read", db_path=db)
    assert store.revoke_scopes("test-user", ["workspace:read"], db_path=db) == ["workspace:read"]
    assert not store.has_scope("test-user", "workspace:read", db_path=db)

def test_local_agent_is_fastapi_loopback_only_and_requires_its_bearer_token(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("REVELAAI_AUTOMATION_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("REVELAAI_AUTOMATION_DB", str(tmp_path / "fabric.sqlite3"))
    monkeypatch.setenv(
        "REVELAAI_AUTOMATION_ALLOWED_ORIGINS",
        "https://revelacode.co.ke",
    )

    from automation_fabric.local_agent import create_local_app

    app = create_local_app("local-agent-test-token")
    local_client = TestClient(app, client=("127.0.0.1", 50123))

    health = local_client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "local-device"

    unauthorized = local_client.get("/api/v1/tools")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "local_token_required"

    authorized = local_client.get(
        "/api/v1/tools",
        headers={"Authorization": "Bearer local-agent-test-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["runtime"] == "local-device"

    preflight = local_client.options(
        "/api/v1/tools",
        headers={
            "Origin": "https://revelacode.co.ke",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["Access-Control-Allow-Origin"] == "https://revelacode.co.ke"

    blocked_origin = local_client.get(
        "/api/v1/health",
        headers={"Origin": "https://untrusted.example"},
    )
    assert blocked_origin.status_code == 403
    assert blocked_origin.json()["code"] == "origin_not_allowed"

    remote_client = TestClient(app, client=("198.51.100.20", 50123))
    blocked_peer = remote_client.get("/api/v1/health")
    assert blocked_peer.status_code == 403
    assert blocked_peer.json()["code"] == "loopback_only"

