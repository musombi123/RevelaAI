"""Explicit, fail-closed dispatch for privileged RevelaAI operator tools.

Only explicit tool-directed operations are intercepted. Explanatory questions
stay in ordinary chat. Sci Defend and Meta Engineer operations require canonical
RevelaCode administrator verification; Genesis and Infinite Mind proposals use
the Core Mesh operator gate. No candidate code is executed or automatically merged.
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

    ecosystem_named = bool(re.search(r"\b(?:ecosystem|revelacode)\b", lower)) and bool(
        re.search(r"\b(?:guardian|protection|perimeter|security)\b", lower)
    )
    ecosystem_action = bool(re.search(r"\b(?:run|perform|start|execute|launch|scan|audit|check)\b", lower))
    if ecosystem_named and ecosystem_action:
        return {"tool": "ecosystem-guardian", "operation": "guardian_sweep"}

    genesis_named = bool(re.search(r"\bgenesis\b", lower))
    mind_named = bool(re.search(r"\b(?:infinite mind|core[ -]?two)\b", lower))
    if genesis_named and re.search(r"\b(?:propose|create|build|generate|develop|implement|invent|design)\b", lower):
        return {"tool": "genesis", "operation": "invention_proposal"}
    if mind_named and re.search(r"\b(?:propose|evolve|improve|upgrade|enhance|harden|refine)\b", lower):
        return {"tool": "infinite-mind", "operation": "mind_proposal"}

    sci_named = bool(re.search(
        r"\b(?:sci[ -]?(?:defend|core)|defensive shield|shield dashboard)\b",
        lower,
    ))
    meta_named = bool(re.search(r"\bmeta[ -]?engineer\b", lower))
    action = bool(re.search(
        r"\b(?:run|perform|start|execute|launch|scan|audit|inspect|check|show|"
        r"get|open|view|report|propose|create|build|generate|develop|implement|"
        r"upgrade|improve|invent|evolve|enhance|harden|refine)\b",
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


def _run_guardian_sweep() -> dict[str, Any]:
    """Run a bounded cross-core status + defensive scan, never a repair or deploy."""
    from concurrent.futures import ThreadPoolExecutor
    from ai.core_mesh import get_core_mesh_dashboard
    from ai.usect_zero_tools import execute_tool
    from fastapi_routes.meta_engineer import _scan
    from fastapi_routes.sci_core import _shield_scan

    def safe_call(label: str, callback):
        try:
            raw = callback()
            value, http_code = _unwrap(raw)
            ok = _status_is_success(value, http_code)
            return {"ok": ok, "http_status": http_code, "data": value}
        except Exception as exc:
            return {
                "ok": False,
                "http_status": None,
                "data": {"status": "error", "failure_type": type(exc).__name__},
            }

    jobs = {
        "core_mesh": lambda: get_core_mesh_dashboard(force_refresh=True),
        "core_zero_diagnostics": lambda: execute_tool("diagnostics", {}),
        "sci_defend_scan": _shield_scan,
        "meta_engineer_scan": _scan,
    }
    raw_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="revela-guardian") as pool:
        futures = {name: pool.submit(safe_call, name, callback) for name, callback in jobs.items()}
        for name, future in futures.items():
            try:
                raw_results[name] = future.result(timeout=50)
            except Exception as exc:
                raw_results[name] = {
                    "ok": False,
                    "http_status": None,
                    "data": {"status": "error", "failure_type": type(exc).__name__},
                }

    mesh_raw = raw_results.get("core_mesh", {}).get("data", {})
    mesh = mesh_raw.get("data") if isinstance(mesh_raw, dict) and isinstance(mesh_raw.get("data"), dict) else mesh_raw
    mesh = mesh if isinstance(mesh, dict) else {}
    cores = mesh.get("cores") if isinstance(mesh.get("cores"), dict) else {}
    core_summary = {
        str(name)[:16]: {
            "status": str(info.get("status") or "unknown")[:40],
            "reachable": info.get("reachable") if info.get("reachable") in (True, False, None) else None,
            "version": str(info.get("version") or "")[:40] or None,
        }
        for name, info in list(cores.items())[:8] if isinstance(name, str) and isinstance(info, dict)
    }
    zero_raw = raw_results.get("core_zero_diagnostics", {}).get("data", {})
    zero_data = zero_raw if isinstance(zero_raw, dict) else {}
    sci_raw = raw_results.get("sci_defend_scan", {}).get("data", {})
    sci_data = sci_raw if isinstance(sci_raw, dict) else {}
    meta_raw = raw_results.get("meta_engineer_scan", {}).get("data", {})
    meta_data = meta_raw if isinstance(meta_raw, dict) else {}

    components = {
        "core_mesh": {
            "ok": raw_results.get("core_mesh", {}).get("ok") is True,
            "status": str(mesh.get("status") or raw_results.get("core_mesh", {}).get("data", {}).get("status") or "unknown")[:40],
            "cores": core_summary,
            "active_signed_tools": mesh.get("active_signed_tools_count"),
        },
        "core_zero_diagnostics": {
            "ok": raw_results.get("core_zero_diagnostics", {}).get("ok") is True
                  and zero_data.get("executed") is True,
            "status": str(zero_data.get("status") or "unknown")[:40],
            "error_code": str(zero_data.get("error_code") or "")[:80] or None,
            "message": str(zero_data.get("message") or "")[:240] or None,
            "executed": zero_data.get("executed") is True,
        },
        "sci_defend_scan": {
            "ok": raw_results.get("sci_defend_scan", {}).get("ok") is True,
            "status": str(sci_data.get("status") or "unknown")[:40],
            "defensive_only": sci_data.get("defensive_only") is True,
            "threats_last_24h": sci_data.get("threats_last_24h"),
            "shields_active": sci_data.get("shields_active"),
            "counts": sci_data.get("counts") if isinstance(sci_data.get("counts"), dict) else None,
        },
        "meta_engineer_scan": {
            "ok": raw_results.get("meta_engineer_scan", {}).get("ok") is True
                  and meta_data.get("read_only") is True,
            "status": str(meta_data.get("status") or "unknown")[:40],
            "module_count": meta_data.get("module_count"),
            "free_slots": meta_data.get("free_slots", [])[:10] if isinstance(meta_data.get("free_slots"), list) else [],
            "read_only": meta_data.get("read_only") is True,
        },
    }
    all_core_states = [item.get("reachable") for item in core_summary.values()]
    all_healthy = all(component["ok"] for component in components.values()) and bool(all_core_states) and all(state is True for state in all_core_states)
    complete_checks = sum(1 for component in components.values() if component["ok"])
    return {
        "status": "completed" if all_healthy else "partial",
        "completed_checks": complete_checks,
        "total_checks": len(components),
        "all_cores_reachable": bool(all_core_states) and all(state is True for state in all_core_states),
        "components": components,
        "safety": {
            "repair_performed": False,
            "production_mutation_performed": False,
            "candidate_source_execution": False,
            "human_approval_required": True,
            "automatic_merge": False,
            "automatic_execution": False,
        },
    }


def dispatch_operator_tool(message: str, *, authorization: str = "") -> dict[str, Any] | None:
    """Invoke a narrowly allowlisted operator tool or return an explicit safe block."""
    request = classify_operator_tool_request(message)
    if request is None:
        return None

    tool = request["tool"]
    operation = request["operation"]
    privileged = operation != "health" and tool not in {"genesis", "infinite-mind"}
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
        if tool == "ecosystem-guardian":
            payload = _run_guardian_sweep()
            success = int(payload.get("completed_checks") or 0) > 0
            payload["_execution_status"] = str(payload.get("status") or "partial")
            payload["_http_status"] = 200
            payload["_invoked"] = True
            payload["_executed"] = success
            return _format_result(
                tool, operation, payload, success=success, proposal=False
            )
        elif tool in {"genesis", "infinite-mind"}:
            from fastapi_routes.core_mesh import _proposal

            objective = " ".join(str(message or "").split())[:500]
            if tool == "genesis":
                raw = _proposal(authorization, {"demand": objective}, "genesis")
            else:
                raw = _proposal(
                    authorization,
                    {"objective": objective, "tool_name": "offline_vault_fixture"},
                    "mind",
                )
            payload, http_code = _unwrap(raw)
            success = _status_is_success(payload, http_code)
            proposal = bool(success and http_code in (200, 201, 202))
            payload["_http_status"] = http_code
            payload["_execution_status"] = "proposal_created" if proposal else "failed"
            payload["_invoked"] = http_code < 400
            payload["_executed"] = False
            return _format_result(
                tool, operation, payload, success=success, proposal=proposal
            )
        elif tool == "sci-defend":
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
    if proposal and tool == "meta-engineer":
        proposal_id = result.get("idea_id") or result.get("proposal_id") or result.get("id")
        response = "Meta Engineer created a reviewable proposal. "
        if proposal_id:
            response += f"Proposal reference: {str(proposal_id)[:100]}. "
        response += "It remains subject to human review; no production code was changed, deployed, or merged."
    elif proposal and tool == "genesis":
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        proposal_id = data.get("proposal_id") or data.get("id") or result.get("proposal_id")
        response = "Genesis created a guarded invention proposal. "
        if proposal_id:
            response += f"Proposal reference: {str(proposal_id)[:100]}. "
        response += "It awaits the existing review/approval path; no tool was activated and nothing was merged."
    elif proposal and tool == "infinite-mind":
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        proposal_id = data.get("proposal_id") or data.get("id") or result.get("proposal_id")
        response = "Infinite Mind created an evidence-gated improvement proposal. "
        if proposal_id:
            response += f"Proposal reference: {str(proposal_id)[:100]}. "
        response += "Human review remains required; no candidate code was executed or merged."
    elif success and tool == "ecosystem-guardian":
        components = result.get("components") if isinstance(result.get("components"), dict) else {}
        parts = []
        for key, label in (
            ("core_mesh", "Core Mesh"),
            ("core_zero_diagnostics", "Core Zero diagnostics"),
            ("sci_defend_scan", "Sci Defend"),
            ("meta_engineer_scan", "Meta Engineer"),
        ):
            item = components.get(key) if isinstance(components.get(key), dict) else {}
            parts.append(label + ": " + str(item.get("status") or ("checked" if item.get("ok") else "unavailable"))[:32])
        response = (
            f"Guardian sweep returned {int(result.get('completed_checks') or 0)}/"
            f"{int(result.get('total_checks') or 4)} completed checks. "
            + "; ".join(parts) + ". "
            + ("All reported cores are reachable. " if result.get("all_cores_reachable") is True else "At least one core or check needs attention. ")
            + "No repairs, production mutations, candidate execution, deployment, or automatic merge were performed."
        )
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
        nested_error = result.get("error") if isinstance(result.get("error"), dict) else {}
        code = str(result.get("code") or nested_error.get("code") or result.get("status") or "tool_failed")[:100]
        message = str(result.get("message") or nested_error.get("message") or "").strip()[:400]
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
    try:
        public_bytes = json.dumps(public_result, ensure_ascii=False, default=str).encode("utf-8")
        if len(public_bytes) > 16_000:
            public_result = {
                "truncated": True,
                "summary": public_bytes[:16_000].decode("utf-8", errors="ignore"),
            }
    except (TypeError, ValueError):
        public_result = {"summary": "Tool result could not be safely serialized."}
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
    core = {
        "ecosystem-guardian": "ecosystem-guardian",
        "sci-defend": "sci-defend",
        "meta-engineer": "meta-engineer",
        "genesis": "core-one",
        "infinite-mind": "core-two",
    }.get(tool, "orchestrator")
    mesh_mode = "proposal_created" if proposal else "executed" if success else "blocked" if status == "blocked" else "dispatch_failed"
    return {
        "response": response,
        "confidence": "high" if success else "low",
        "intent": "operator_tool",
        "domain": "security" if tool in {"sci-defend", "ecosystem-guardian"} else "programming",
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
