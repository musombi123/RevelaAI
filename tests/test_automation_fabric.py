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


def test_consent_can_be_revoked(tmp_path):
    db = str(tmp_path / "fabric.sqlite3")
    store.grant_scopes("test-user", ["workspace:read"], reason="test", ttl_seconds=600, db_path=db)
    assert store.has_scope("test-user", "workspace:read", db_path=db)
    assert store.revoke_scopes("test-user", ["workspace:read"], db_path=db) == ["workspace:read"]
    assert not store.has_scope("test-user", "workspace:read", db_path=db)
