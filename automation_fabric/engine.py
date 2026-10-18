"""Plan validation and guarded, one-shot execution for Automation Fabric."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import store
from .policy import MAX_PLAN_TTL_SECONDS
from .registry import MAX_PLAN_ARGUMENTS_BYTES, TOOLS, run_tool, validate_arguments


class AutomationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _canonical_hash(value: dict[str, Any]) -> str:
    material = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_plan(
    principal: str,
    steps: Any,
    workspace: str | Path,
    *,
    db_path: str | None = None,
    local_mode: bool = False,
) -> dict[str, Any]:
    if not isinstance(steps, list) or not steps:
        raise AutomationError("invalid_steps", "steps must be a non-empty array")
    if len(steps) > 20:
        raise AutomationError("plan_too_large", "a plan can contain at most 20 steps")
    if len(json.dumps(steps, ensure_ascii=False, default=str).encode("utf-8")) > MAX_PLAN_ARGUMENTS_BYTES:
        raise AutomationError("plan_too_large", "plan arguments exceed the 350 KB limit")

    normalized_steps: list[dict[str, Any]] = []
    required_scopes: set[str] = set()
    requires_confirmation = False
    includes_local_tools = False
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            raise AutomationError("invalid_step", f"step {index + 1} must be an object")
        if set(raw_step) - {"tool", "args", "id"}:
            raise AutomationError("invalid_step", f"step {index + 1} has unsupported fields")
        name = raw_step.get("tool")
        if not isinstance(name, str) or name not in TOOLS:
            raise AutomationError("unknown_tool", f"step {index + 1} uses an unknown tool")
        try:
            args = validate_arguments(name, raw_step.get("args", {}))
        except (ValueError, TypeError) as exc:
            raise AutomationError("invalid_tool_args", f"step {index + 1}: {exc}") from exc
        spec = TOOLS[name]
        required_scopes.update(spec.scopes)
        requires_confirmation = requires_confirmation or spec.confirmation_required
        includes_local_tools = includes_local_tools or spec.local_only
        normalized_steps.append({
            "id": f"step-{index + 1}",
            "tool": name,
            "args": args,
            "required_scopes": list(spec.scopes),
            "risk": spec.risk,
            "confirmation_required": spec.confirmation_required,
            "local_agent_required": spec.local_only,
            "description": spec.description,
        })

    # A plan may be prepared in the hosted service for a device-only tool, but
    # it cannot execute there. No implicit handoff or remote device access exists.
    if includes_local_tools and not local_mode:
        execution_target = "local_agent_required"
    else:
        execution_target = "current_runtime"

    created = time.time()
    expires = created + min(MAX_PLAN_TTL_SECONDS, 15 * 60)
    plan_id = uuid.uuid4().hex
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "created_at": _utc_iso(created),
        "expires_at": _utc_iso(expires),
        "steps": normalized_steps,
        "required_scopes": sorted(required_scopes),
        "confirmation_required": requires_confirmation,
        "execution_target": execution_target,
        "model_dependency": False,
        "automatic_code_execution": False,
        "safety_notes": [
            "No shell commands or generated code are executed.",
            "Every required scope must have an unexpired user consent grant.",
            "Execution requires the exact plan hash and explicit approval.",
            "Device-only tools require an installed local agent on the target device.",
        ],
    }
    plan_hash = _canonical_hash(plan)
    plan["plan_hash"] = plan_hash
    store.save_plan(
        principal, plan_id, plan_hash, plan,
        created_at=created, expires_at=expires, db_path=db_path,
    )
    store.audit_event(principal, "plan_created", {
        "plan_id": plan_id, "plan_hash": plan_hash,
        "tools": [step["tool"] for step in normalized_steps],
        "required_scopes": sorted(required_scopes),
        "execution_target": execution_target,
    }, db_path=db_path)
    return plan


def _bounded_result(value: Any, *, depth: int = 0) -> Any:
    """Keep responses bounded, JSON-safe, and useful for client diagnostics."""
    if depth > 5:
        return "[depth limit]"
    if isinstance(value, str):
        return value if len(value) <= 20000 else value[:20000] + " [truncated]"
    if isinstance(value, dict):
        return {str(key)[:100]: _bounded_result(item, depth=depth + 1) for key, item in list(value.items())[:60]}
    if isinstance(value, (list, tuple)):
        return [_bounded_result(item, depth=depth + 1) for item in list(value)[:100]]
    if value is None or type(value) in (int, float, bool):
        return value
    return str(value)[:500]


def execute_plan(
    principal: str,
    plan_id: str,
    approved_plan_hash: str,
    *,
    approved: bool,
    workspace: str | Path,
    db_path: str | None = None,
    local_mode: bool = False,
) -> dict[str, Any]:
    if approved is not True:
        raise AutomationError("explicit_approval_required", "set approved=true only after reviewing this plan", 403)
    record = store.get_plan(principal, plan_id, db_path=db_path)
    if record is None:
        raise AutomationError("plan_not_found", "plan does not exist for this user", 404)
    if record["status"] != "planned":
        raise AutomationError("plan_not_executable", f"plan status is {record['status']}; plans can execute once", 409)
    if record["expires_at"] <= time.time():
        raise AutomationError("plan_expired", "plan expired; create and review a new plan", 409)
    if not isinstance(approved_plan_hash, str) or not hmac.compare_digest(record["plan_hash"], approved_plan_hash):
        raise AutomationError("plan_hash_mismatch", "plan changed; review the current plan before execution", 409)

    plan = record["plan"]
    if _canonical_hash({key: value for key, value in plan.items() if key != "plan_hash"}) != record["plan_hash"]:
        raise AutomationError("plan_integrity_failed", "stored plan integrity check failed", 503)
    if plan.get("execution_target") == "local_agent_required" and not local_mode:
        raise AutomationError("local_agent_required", "this plan includes device-only tools; run it using the installed local agent", 409)

    for scope in plan.get("required_scopes", []):
        if not store.has_scope(principal, scope, db_path=db_path):
            raise AutomationError("consent_required", f"permission scope not granted: {scope}", 403)

    if not store.claim_plan(principal, plan_id, approved_plan_hash, db_path=db_path):
        raise AutomationError("plan_not_executable", "plan was already claimed, expired, or changed", 409)

    store.audit_event(principal, "plan_execution_started", {
        "plan_id": plan_id, "plan_hash": record["plan_hash"],
        "step_count": len(plan.get("steps", [])),
    }, db_path=db_path)

    outputs: list[dict[str, Any]] = []
    outcome = "completed"
    for step in plan.get("steps", []):
        name = step["tool"]
        missing_scopes = [
            scope for scope in step.get("required_scopes", [])
            if not store.has_scope(principal, scope, db_path=db_path)
        ]
        if missing_scopes:
            outcome = "partial_failed" if outputs else "failed"
            outputs.append({
                "step_id": step["id"], "tool": name, "ok": False,
                "error": {"code": "consent_revoked_or_expired", "message": "Required consent is no longer active."},
            })
            store.audit_event(principal, "tool_blocked_by_policy", {
                "plan_id": plan_id, "step_id": step["id"], "tool": name,
                "missing_scopes": missing_scopes,
            }, db_path=db_path)
            break
        store.audit_event(principal, "tool_started", {
            "plan_id": plan_id, "step_id": step["id"], "tool": name,
            "arg_keys": sorted(step.get("args", {}).keys()),
        }, db_path=db_path)
        try:
            result = _bounded_result(run_tool(name, step.get("args", {}), workspace, local_mode=local_mode))
            outputs.append({"step_id": step["id"], "tool": name, "ok": True, "result": result})
            store.audit_event(principal, "tool_completed", {
                "plan_id": plan_id, "step_id": step["id"], "tool": name,
                "result_type": type(result).__name__,
            }, db_path=db_path)
        except Exception as exc:
            outcome = "partial_failed" if outputs else "failed"
            safe_message = str(exc)[:400]
            outputs.append({"step_id": step["id"], "tool": name, "ok": False,
                            "error": {"code": "tool_execution_failed", "message": safe_message}})
            store.audit_event(principal, "tool_failed", {
                "plan_id": plan_id, "step_id": step["id"], "tool": name,
                "error_type": type(exc).__name__,
            }, db_path=db_path)
            break

    # Persist only bounded summaries and hashes—not full file contents or write payloads.
    summaries = []
    for item in outputs:
        serialized = json.dumps(item.get("result"), sort_keys=True, default=str)
        summaries.append({
            "step_id": item["step_id"], "tool": item["tool"], "ok": item["ok"],
            "result_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest() if item["ok"] else None,
            "error_code": item.get("error", {}).get("code") if not item["ok"] else None,
        })
    store.finish_plan(principal, plan_id, outcome, {"steps": summaries}, db_path=db_path)
    store.audit_event(principal, "plan_execution_finished", {
        "plan_id": plan_id, "status": outcome, "completed_steps": sum(bool(item["ok"]) for item in outputs),
    }, db_path=db_path)
    return {
        "status": outcome,
        "plan_id": plan_id,
        "plan_hash": record["plan_hash"],
        "results": outputs,
        "automatic_code_execution": False,
    }
