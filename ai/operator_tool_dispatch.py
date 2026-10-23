"""Explicit, fail-closed dispatch for privileged RevelaAI operator tools.

Only requests that name Sci Defend/Sci-Core or Meta Engineer and clearly ask
for a direct operation are intercepted. Explanatory questions stay in ordinary
chat. Privileged operations require the canonical RevelaCode admin verifier.
No code is deployed, executed, or merged by this dispatcher.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi.responses import JSONResponse


def classify_operator_tool_request(message: str) -> dict[str, str] | None:
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None
    lower = text.casefold()

    sci_named = bool(re.search(
        r"\b(?:sci[ -]?(?:defend|core)|defensive shield|shield dashboard)\b",
        lower,
    ))
    meta_named = bool(re.search(r"\bmeta[ -]?engineer\b", lower))
    action = bool(re.search(
        r"\b(?:run|perform|start|execute|launch|scan|audit|inspect|check|show|"
        r"get|open|view|report|propose|create|build|generate|develop|implement|"
        r"upgrade|improve)\b",
        lower,
    ))
    if not action:
        return None

    if sci_named and re.search(r"\b(?:scan|audit|inspect)\b", lower):
        return {"tool": "sci-defend", "operation": "shield_scan"}
    if sci_named and re.search(r"\b(?:status|dashboard|health|counters|report|check|show|get|view)\b", lower):
        return {"tool": "sci-defend", "operation": "shield_dashboard"}

    if meta_named and re.search(r"\b(?:propose|create|build|generate|develop|implement|upgrade|improve)\b", lower):
        return {"tool": "meta-engineer", "operation": "proposal"}
    if meta_named and re.search(r"\b(?:scan|audit|inspect)\b", lower):
        return {"tool": "meta-engineer", "operation": "architecture_scan"}
    if meta_named and re.search(r"\b(?:status|health|readiness)\b", lower):
        return {"tool": "meta-engineer", "operation": "health"}
    return None


def _unwrap(value: Any) -> tuple[dict[str, Any], int]:
    if isinstance(value, JSONResponse):
        try:
            payload = json.loads(value.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            payload = {"status": "error", "message": "Tool returned an unreadable response."}
        return (payload if isinstance(payload, dict) else {"data": payload}, int(value.status_code))
    if isinstance(value, dict):
        return value, 200
    return {"status": "error", "message": "Tool returned an unsupported response."}, 502


def _status_is_success(payload: dict[str, Any], code: int) -> bool:
    status = str(payload.get("status") or "").casefold()
    return code < 400 and status not in {"error", "degraded", "failed", "unavailable", "blocked"}


def dispatch_operator_tool(message: str, *, authorization: str = "") -> dict[str, Any] | None:
    """Invoke a narrowly allowlisted operator tool or return an explicit safe block."""
    request = classify_operator_tool_request(message)
    if request is None:
        return None

    tool = request["tool"]
    operation = request["operation"]
    privileged = operation != "health"
    actor = None
    if privileged:
        # Import lazily to keep ordinary chat independent of admin verification.
        from fastapi_routes.admin_auth import require_platform_admin

        actor, auth_error = require_platform_admin(authorization)
        if auth_error is not None:
            status_code = int(getattr(auth_error, "status_code", 403))
            error_body, _ = _unwrap(auth_error)
            code = str(error_body.get("code") or (
                "admin_verification_unavailable" if status_code >= 500 else "admin_required"
            ))[:80]
            result = {
                "status": "blocked",
                "code": code,
                "message": (
                    "Administrator verification is temporarily unavailable."
                    if status_code >= 500 else
                    "This direct operation requires a verified RevelaCode platform administrator."
                ),
                "invoked": False,
                "executed": False,
            }
            return _format_result(tool, operation, result, success=False, proposal=False)

        if not actor:
            result = {
                "status": "blocked", "code": "admin_required",
                "message": "No canonical administrator identity was supplied.",
                "invoked": False, "executed": False,
            }
            return _format_result(tool, operation, result, success=False, proposal=False)

    try:
        if tool == "sci-defend":
            from fastapi_routes import sci_core

            if operation == "shield_scan":
                raw = sci_core._shield_scan()
            else:
                # The route helper performs its own admin check as well. Keep
                # that second check so this call cannot drift from its API guard.
                raw = sci_core._dashboard(authorization)
        elif tool == "meta-engineer":
            from fastapi_routes import meta_engineer

            if operation == "health":
                raw = meta_engineer._health()
            elif operation == "architecture_scan":
                raw = meta_engineer._scan()
            else:
                spec = re.sub(
                    r"^.*?\bmeta[ -]?engineer\b\s*[:,—-]?\s*",
                    "", str(message or ""), flags=re.IGNORECASE,
                ).strip()
                spec = spec[:800]
                if len(spec) < 12:
                    return _format_result(
                        tool, operation,
                        {"status": "blocked", "code": "proposal_spec_required",
                         "message": "Give Meta Engineer a specific proposal objective (at least 12 characters).",
                         "invoked": False, "executed": False},
                        success=False, proposal=False,
                    )
                target = "security" if re.search(r"\b(?:security|defend|shield|hardening)\b", spec, re.I) else "fullstack"
                raw = meta_engineer._propose(actor, {"spec": spec, "target": target})
        else:
            return None
        payload, http_code = _unwrap(raw)
    except Exception as exc:
        # Do not leak credentials, stack traces, or arbitrary exception text.
        return _format_result(
            tool, operation,
            {"status": "error", "code": "operator_tool_failed",
             "message": "The selected operator tool could not complete its request.",
             "failure_type": type(exc).__name__, "invoked": True, "executed": False},
            success=False, proposal=False,
        )

    success = _status_is_success(payload, http_code)
    proposal = tool == "meta-engineer" and operation == "proposal" and success
    execution_status = "proposal_created" if proposal else "completed" if success else "failed"
    payload = dict(payload)
    payload["_http_status"] = http_code
    payload["_execution_status"] = execution_status
    payload["_invoked"] = True
    payload["_executed"] = bool(success and not proposal)
    return _format_result(tool, operation, payload, success=success, proposal=proposal)


def _format_result(
    tool: str, operation: str, result: dict[str, Any], *, success: bool, proposal: bool
) -> dict[str, Any]:
    status = str(result.get("_execution_status") or (
        "proposal_created" if proposal else "completed" if success else
        "blocked" if result.get("status") == "blocked" else "failed"
    ))
    invoked = result.get("_invoked") is True or result.get("invoked") is True
    executed = result.get("_executed") is True or result.get("executed") is True
    summary = str(result.get("message") or result.get("summary") or result.get("status") or status).strip()[:600]
    if proposal:
        proposal_id = result.get("idea_id") or result.get("proposal_id") or result.get("id")
        response = "Meta Engineer created a reviewable proposal. "
        if proposal_id:
            response += f"Proposal reference: {str(proposal_id)[:100]}. "
        response += "It remains subject to human review; no production code was changed, deployed, or merged."
    elif success and tool == "sci-defend" and operation == "shield_scan":
        response = "Sci Defend completed the defensive shield scan. " + summary + " Defensive-only operation; no offensive action was requested."
    elif success and tool == "sci-defend":
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        response = "Sci Defend returned the shield dashboard. "
        if counts:
            response += "Current counters: " + ", ".join(f"{str(k)[:40]}={str(v)[:40]}" for k, v in list(counts.items())[:8]) + ". "
        response += "The capability is restricted to defensive and civilian operations."
    elif success and tool == "meta-engineer" and operation == "architecture_scan":
        count = result.get("module_count")
        free = result.get("free_slots")
        response = f"Meta Engineer completed a read-only architecture scan ({count if count is not None else 'module count unavailable'} modules"
        if isinstance(free, list):
            response += f", {len(free)} identified extension slots"
        response += "). No files or deployment state were changed."
    elif success and tool == "meta-engineer" and operation == "health":
        response = "Meta Engineer health check returned status: " + str(result.get("status") or "unknown") + ". Candidate execution and auto-deployment remain disabled."
    elif success:
        response = f"{tool} completed the {operation.replace('_', ' ')} operation."
    else:
        code = str(result.get("code") or result.get("error") or result.get("status") or "tool_failed")[:100]
        message = str(result.get("message") or "").strip()
        response = (
            f"{tool} {operation.replace('_', ' ')} was not completed (status: {status}; code: {code}). "
            + (message + " " if message else "")
            + "No production code was changed or deployed."
        )

    safety = {
        "operation_executed": executed,
        "target_mutation_performed": False,
        "candidate_source_execution": False,
        "human_approval_required": bool(proposal or not success or tool == "meta-engineer"),
        "automatic_merge": False,
        "automatic_execution": False,
    }
    public_result = {
        key: value for key, value in result.items()
        if not str(key).startswith("_") and key not in {"stack", "traceback", "authorization", "token"}
    }
    tool_execution = {
        "source": "server_operator_dispatch",
        "tool": tool,
        "operation": operation,
        "status": status,
        "invoked": invoked,
        "executed": executed,
        "proposal_created": proposal,
        "http_status": result.get("_http_status"),
        "code": result.get("code"),
        "failure_type": result.get("failure_type"),
        "result": public_result,
        "safety": safety,
    }
    core = "sci-defend" if tool == "sci-defend" else "meta-engineer"
    mesh_mode = "proposal_created" if proposal else "executed" if success else "blocked" if status == "blocked" else "dispatch_failed"
    return {
        "response": response,
        "confidence": "high" if success else "low",
        "intent": "operator_tool",
        "domain": "security" if tool == "sci-defend" else "programming",
        "provider": "revelaai-operator-dispatch",
        "model": tool,
        "capability": "operator_tool",
        "tool_execution": tool_execution,
        "operator_tool": tool_execution,
        "orchestrator": {
            "core_mesh": {
                "mode": mesh_mode,
                "selected_core": core,
                "target_core": core,
                "operation_kind": operation,
                "execution_status": status,
                "failure_reason": tool_execution.get("code") if not success else None,
                "mesh_status": "direct_dispatch",
                "safety": safety,
            }
        },
    }


__all__ = ["classify_operator_tool_request", "dispatch_operator_tool"]
