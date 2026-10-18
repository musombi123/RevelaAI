"""First-class USECT-ZERO tools for the RevelaAI brain.

The dispatcher runs before language-model generation. It is not a fallback
provider: engineering requests that match a supported operation must produce
a USECT-ZERO tool outcome before the model is allowed to synthesize a reply.
The tool catalog is included in every ordinary text-model turn.
"""
from __future__ import annotations

import json
import os
import re
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from services.usect_zero_client import (
    USECTZeroAdminTokenMissing,
    USECTZeroConfigurationError,
    USECTZeroDisabled,
    USECTZeroError,
    USECTZeroPayloadTooLarge,
    USECTZeroResponseTooLarge,
    USECTZeroUnavailable,
    is_enabled,
    request_core,
)

MAX_TOOL_INPUT_CHARS = 12_000
MAX_TOOL_OUTPUT_CHARS = 20_000
TOOL_NAME = "usect_zero"
_RECENT_ACTIVITY: deque[dict[str, Any]] = deque(maxlen=50)
_ACTIVITY_LOCK = Lock()
_ACTIVITY_SUMMARY_FIELDS = (
    "file_count", "language_counts", "git_head", "manifest_sha256",
    "read_only", "target", "proposal_id", "id", "status",
    "compiled", "artifact_count", "source_count",
)

# Public, model-readable tool contract. The runtime dispatcher below retains
# strict allowlisted routes and never exposes the admin token to the model.
TOOL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "name": "usect_zero_scan_repository",
        "description": "Inspect the configured Host System Alpha repository and return SHA-256 inventory evidence, file counts, languages and Git HEAD. Use for repository/codebase scans and architecture inventory.",
        "operation": "scan",
        "scope": "scan:read",
        "method": "GET",
        "path": "/v1/scan",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "usect_zero_list_assembly_templates",
        "description": "List registered, versioned assembly templates and their validation status before generation. Read-only; no artifacts are generated and no hardware is accessed.",
        "operation": "assemble_templates",
        "scope": "scan:read",
        "method": "GET",
        "path": "/v1/assemble/templates",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "usect_zero_diagnostics",
        "description": "Check USECT-ZERO runtime details, data-directory write readiness, and added/modified/missing repository files versus the saved baseline. This is a read-only report; it never repairs drift.",
        "operation": "diagnostics",
        "scope": "scan:read",
        "method": "GET",
        "path": "/v1/diagnostics",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "usect_zero_propose_healing",
        "description": "Compare tracked baseline files with the working tree and stage verified recovery candidates for missing or modified files. Modified targets are hash-checked again and backed up before any human-approved replacement; this tool never approves or restores automatically.",
        "operation": "heal",
        "scope": "heal:propose",
        "method": "POST",
        "path": "/v1/heal/proposals",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "usect_zero_assemble_fixture",
        "description": "Generate artifacts from an exact registered version of the curated ESP32-S3 sensor template. BOM and wiring metadata are validated before files are generated; output remains a review draft and is not hardware-verified.",
        "operation": "assemble",
        "scope": "assemble:propose",
        "method": "POST",
        "path": "/v1/assemble",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["esp32-sensor"]},
                "template_version": {"type": "string", "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$"},
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usect_zero_compare_evidence",
        "description": "Compare a supplied current/candidate version and benchmark using offline evidence. Never invent a benchmark, source, version or evidence ID.",
        "operation": "radar",
        "scope": "radar:compare",
        "method": "POST",
        "path": "/v1/radar/compare",
        "parameters": {
            "type": "object",
            "properties": {
                "current": {"type": "object"},
                "candidate": {"type": "object"},
            },
            "required": ["current", "candidate"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usect_zero_bridge_plan",
        "description": "Create a non-executing integration plan for ROS2, FPGA, LabVIEW, or a USB/Bluetooth device. Does not access hardware or run drivers.",
        "operation": "bridge",
        "scope": "bridge:propose",
        "method": "POST",
        "path": "/v1/bridge/plan",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string", "enum": ["ros2", "fpga", "labview", "device"]}},
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usect_zero_compile_rv_lang",
        "description": "Compile explicit RV Lang source into a bounded declarative Go plan for review. The result is not executed and does not authorize changes.",
        "operation": "mind",
        "scope": "mind:compile",
        "method": "POST",
        "path": "/v1/mind/compile",
        "parameters": {
            "type": "object",
            "properties": {"source": {"type": "string", "maxLength": 12000}},
            "required": ["source"],
            "additionalProperties": False,
        },
    },
)

_CATALOG_BY_OPERATION = {item["operation"]: item for item in TOOL_CATALOG}
_BRIDGE_TARGETS = {
    "ros2": re.compile(r"\b(?:ros\s*2|ros2|robot operating system)\b", re.I),
    "fpga": re.compile(r"\b(?:fpga|verilog|systemverilog|hdl synthesis)\b", re.I),
    "labview": re.compile(r"\blabview\b", re.I),
    "device": re.compile(r"\b(?:usb|bluetooth)\s+(?:device|bridge|adapter|integration)\b", re.I),
}


def tool_catalog_prompt() -> str:
    """Return concise instructions embedded in every model turn."""
    lines = [
        "FIRST-CLASS ENGINEERING TOOL — USECT-ZERO",
        "USECT-ZERO is a named engineering tool in the primary brain pipeline, not a model/provider fallback.",
        "For repository scans and core diagnostics, engineering recovery proposals, registered assembly fixtures, version-evidence comparison, adapter planning, or RV Lang compilation, use the matching USECT-ZERO tool outcome supplied by the server.",
        "Never claim a USECT-ZERO operation occurred unless the current turn contains its tool_execution result.",
        "When a required USECT-ZERO tool is unavailable, report that blocker; do not silently answer as though the tool ran or downgrade the task to an ordinary answer.",
        "The server only dispatches a bounded allowlist. Admin approval, recovery application, code execution, deployment, and hardware actuation are not brain tools.",
        "Available tool contracts:",
    ]
    for item in TOOL_CATALOG:
        lines.append(
            f"- {item['name']} (scope {item['scope']}): {item['description']} "
            f"Arguments: {json.dumps(item['parameters'], separators=(',', ':'))}"
        )
    return "\n".join(lines)


def _extract_json_object(message: str) -> dict[str, Any] | None:
    """Accept one complete JSON object, optionally inside a fenced block."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", message, re.I | re.S)
    candidates.append(message.strip())
    # Also accept one complete evidence object embedded in a short natural-language instruction.
    first_brace = message.find("{")
    last_brace = message.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(message[first_brace:last_brace + 1])
    for candidate in candidates:
        if len(candidate) > MAX_TOOL_INPUT_CHARS:
            continue
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_rv_source(message: str) -> str | None:
    blocks = re.findall(r"```(?:rv|rvlang|rv-lang)?\s*\n(.*?)```", message, re.I | re.S)
    for block in blocks:
        value = block.strip()
        if value and re.match(r"^(?:heal|assemble|evolve|forge|bridge|scan|propose|approve|audit)\b", value, re.I):
            return value[:MAX_TOOL_INPUT_CHARS]
    match = re.search(r"(?:RV\s*Lang\s*(?:source)?\s*:\s*)(.+)$", message, re.I | re.S)
    if match:
        value = match.group(1).strip()
        return value[:MAX_TOOL_INPUT_CHARS] if value else None
    return None


def select_tool_for_message(message: str, intent: str = "general") -> tuple[str, dict[str, Any]] | None:
    """Select a named tool for clearly matching engineering tasks."""
    text = str(message or "").strip()
    lowered = text.lower()
    if not text:
        return None

    if re.search(
        r"\\b(?:diagnostic(?:s)?|health check|health status|baseline drift|repository drift|core readiness|storage readiness|what changed since baseline)\\b",
        lowered,
    ):
        return "diagnostics", {}

    # Structured offline evidence must be provided by the user; the brain
    # must not create benchmark numbers to satisfy this tool.
    evidence = _extract_json_object(text)
    if (
        evidence
        and isinstance(evidence.get("current"), dict)
        and isinstance(evidence.get("candidate"), dict)
        and re.search(r"\b(?:radar|compare|comparison|benchmark|candidate version)\b", lowered)
    ):
        return "radar", {
            "current": evidence["current"],
            "candidate": evidence["candidate"],
        }

    if re.search(r"\b(?:compile|run)\b.{0,50}\bRV\s*Lang\b|\bRV\s*Lang\b.{0,50}\b(?:compile|compiler)\b", text, re.I):
        source = _extract_rv_source(text)
        return ("mind", {"source": source}) if source else ("mind", {})

    if re.search(
        r"\b(?:bridge|integrate|adapter plan|integration plan)\b.{0,70}\b(?:ROS\s*2|ROS2|FPGA|Verilog|LabVIEW|USB|Bluetooth)\b|\b(?:ROS\s*2|ROS2|FPGA|Verilog|LabVIEW)\b.{0,70}\b(?:bridge|adapter|integration)\b",
        text,
        re.I,
    ):
        target = next((name for name, pattern in _BRIDGE_TARGETS.items() if pattern.search(text)), None)
        if target:
            return "bridge", {"target": target}

    if re.search(
        r"\b(?:assembly|assemble)\s+(?:template|templates|catalog|catalogue)|\b(?:list|show|available|registered|supported)\b.{0,50}\b(?:assembly templates?|assemble templates?|hardware templates?|design templates?)\b|\bwhat (?:assembly|hardware) templates? (?:are )?available\b",
        lowered,
    ):
        return "assemble_templates", {}

    if re.search(r"\b(?:heal proposal|propose healing|recover deleted file|recover modified file|restore missing file|restore a missing file|missing tracked files|modified tracked files|modified baseline file|repository recovery|code recovery)\b|/heal\b", lowered):
        return "heal", {}

    if re.search(
        r"\b(?:assemble|bill of materials|BOM|wiring diagram|generate STL|hardware fixture)\b|\bESP32(?:-S3)?\b.{0,50}\b(?:sensor|assemble|wiring|BOM)\b",
        text,
        re.I,
    ):
        target = "esp32-sensor" if re.search(r"\b(?:esp32|bme280|sensor fixture)\b", lowered, re.I) else "unregistered-target"
        version_match = re.search(r"\bv?(\d+\.\d+\.\d+)\b", text, re.I)
        arguments = {"target": target}
        if version_match:
            arguments["template_version"] = version_match.group(1)
        return "assemble", arguments

    if re.search(
        r"\b(?:scan|inspect|inventory|map)\b.{0,60}\b(?:repository|repo|codebase|project files|architecture|structure|tracked files)\b|\b(?:repository|repo|codebase)\b.{0,60}\b(?:scan|inspect|inventory|architecture map)\b|\bwhat files (?:are|exist) in (?:this|the) (?:repo|repository|codebase)\b",
        text,
        re.I,
    ) or re.search(r"\b(?:usect[- ]zero|usect0)\b.{0,45}\b(?:scan|inspect|inventory)\b", text, re.I):
        return "scan", {}

    # RV source compilation is only selected with an explicit RV Lang request.
    return None


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Bound untrusted core results before they enter model context."""
    if depth > 6:
        return "[nested result omitted]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            key_string = str(key)
            if key_string.lower() in {
                "repository_root", "api_key", "secret", "key_hash", "authorization",
                "admin_token", "password", "credentials",
            }:
                continue
            result[key_string] = _sanitize(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_sanitize(item, depth + 1) for item in value[:40]]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]


def _scan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep tool context useful without stuffing the whole inventory into the prompt."""
    files = payload.get("files")
    summary = {
        key: payload.get(key)
        for key in (
            "schema_version", "generated_at", "git_head", "file_count",
            "language_counts", "changelog_paths", "manifest_sha256", "read_only",
            "evidence_note",
        )
        if key in payload
    }
    if isinstance(files, list):
        summary["sample_files"] = [
            {k: row.get(k) for k in ("path", "sha256", "bytes", "language") if k in row}
            for row in files[:25]
            if isinstance(row, dict)
        ]
        summary["sample_files_truncated"] = len(files) > 25
    return _sanitize(summary)


def recent_activity(limit: int = 25) -> list[dict[str, Any]]:
    """Return a bounded, sanitized activity view; records are in-process only."""
    try:
        bounded_limit = min(max(int(limit), 1), 50)
    except (TypeError, ValueError):
        bounded_limit = 25
    with _ACTIVITY_LOCK:
        items = list(reversed(_RECENT_ACTIVITY))[:bounded_limit]
    return [dict(item) for item in items]


def _record_activity(outcome: dict[str, Any]) -> None:
    """Record operational status without user prompts, credentials or file paths."""
    raw_result = outcome.get("result")
    summary: dict[str, Any] = {}
    if isinstance(raw_result, dict):
        for field in _ACTIVITY_SUMMARY_FIELDS:
            if field not in raw_result:
                continue
            value = raw_result[field]
            if isinstance(value, str):
                summary[field] = value[:180]
            elif isinstance(value, (int, float, bool)) or value is None:
                summary[field] = value
            elif isinstance(value, dict):
                summary[field] = {
                    str(key)[:50]: item
                    for key, item in list(value.items())[:10]
                    if isinstance(item, (str, int, float, bool)) or item is None
                }
            elif isinstance(value, list):
                summary[field] = [
                    item[:120] if isinstance(item, str) else item
                    for item in value[:5]
                    if isinstance(item, (str, int, float, bool)) or item is None
                ]

    activity_item = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": str(outcome.get("name") or outcome.get("tool") or TOOL_NAME)[:80],
        "operation": str(outcome.get("operation") or "unknown")[:40],
        "status": str(outcome.get("status") or "unknown")[:40],
        "executed": bool(outcome.get("executed", False)),
        "http_status": outcome.get("http_status") if isinstance(outcome.get("http_status"), int) else None,
        "error_code": str(outcome.get("error_code") or "")[:100] or None,
        "result_summary": summary,
    }
    with _ACTIVITY_LOCK:
        _RECENT_ACTIVITY.append(activity_item)


def execute_tool(operation: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke one known tool using a dedicated scoped brain key, never admin credentials."""
    spec = _CATALOG_BY_OPERATION.get(str(operation or ""))
    if spec is None:
        return {
            "tool": TOOL_NAME,
            "operation": str(operation or "unknown"),
            "status": "blocked",
            "error_code": "unknown_tool_operation",
            "executed": False,
        }
    args = arguments if isinstance(arguments, dict) else {}
    result: dict[str, Any] = {
        "tool": TOOL_NAME,
        "name": spec["name"],
        "operation": operation,
        "status": "blocked",
        "executed": False,
        "scope": spec["scope"],
    }
    if not is_enabled():
        result.update({
            "status": "unavailable",
            "error_code": "usect_zero_disabled",
            "message": "USECT-ZERO is not enabled in this backend deployment.",
        })
        return result

    api_key = os.getenv("USECT_ZERO_BRAIN_API_KEY", "").strip()
    if not api_key:
        result.update({
            "status": "unavailable",
            "error_code": "usect_zero_brain_key_missing",
            "message": "The dedicated scoped brain API key is not configured on the server.",
        })
        return result

    try:
        method = spec["method"]
        if operation in {"scan", "diagnostics", "assemble_templates"}:
            body = None
        elif operation == "heal":
            body = b"{}"
        elif operation in {"assemble", "bridge", "mind", "radar"}:
            if operation == "assemble":
                target = args.get("target")
                if not isinstance(target, str) or len(target) > 80:
                    raise ValueError("target must be a short string")
                payload = {"target": target}
                version = args.get("template_version")
                if version is not None:
                    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
                        raise ValueError("template_version must use strict major.minor.patch format")
                    payload["template_version"] = version
            elif operation == "bridge":
                target = args.get("target")
                if target not in {"ros2", "fpga", "labview", "device"}:
                    raise ValueError("target must be ros2, fpga, labview, or device")
                payload = {"target": target}
            elif operation == "mind":
                source = args.get("source")
                if not isinstance(source, str) or not source.strip() or len(source) > MAX_TOOL_INPUT_CHARS:
                    raise ValueError("source is required and must be no more than 12,000 characters")
                payload = {"source": source}
            else:
                current = args.get("current")
                candidate = args.get("candidate")
                if not isinstance(current, dict) or not isinstance(candidate, dict):
                    raise ValueError("current and candidate evidence objects are required")
                payload = {"current": current, "candidate": candidate}
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        else:
            raise ValueError("operation has no dispatcher")

        reply = request_core(
            method,
            spec["path"],
            body=body,
            api_key=api_key,
            admin=False,
        )
        safe_payload = _scan_summary(reply.payload) if operation == "scan" and isinstance(reply.payload, dict) else _sanitize(reply.payload)
        status = "success" if 200 <= reply.status_code < 300 else "blocked"
        result.update({
            "status": status,
            "executed": True,
            "http_status": reply.status_code,
            "result": safe_payload,
        })
        if reply.status_code in {401, 403}:
            result["error_code"] = "usect_zero_scope_denied"
            result["message"] = "The configured brain key is missing the required scope or is invalid."
        elif reply.status_code in {409, 422}:
            result["error_code"] = "usect_zero_operation_blocked"
            result["message"] = "The core rejected this operation; inspect the returned result before deciding the next step."
        return result
    except (USECTZeroDisabled, USECTZeroAdminTokenMissing, USECTZeroConfigurationError, USECTZeroPayloadTooLarge, USECTZeroResponseTooLarge, USECTZeroUnavailable) as exc:
        result.update({
            "status": "unavailable",
            "error_code": "usect_zero_unavailable",
            "message": str(exc)[:300],
        })
    except (TypeError, ValueError) as exc:
        result.update({
            "status": "blocked",
            "error_code": "invalid_tool_arguments",
            "message": str(exc)[:300],
        })
    except USECTZeroError:
        result.update({
            "status": "unavailable",
            "error_code": "usect_zero_unavailable",
            "message": "The USECT-ZERO tool call was blocked or unavailable.",
        })
    return result


def execute_for_message(message: str, intent: str = "general") -> dict[str, Any] | None:
    """Select and run at most one supported tool before model generation."""
    selected = select_tool_for_message(message, intent=intent)
    if selected is None:
        return None
    operation, arguments = selected
    outcome = execute_tool(operation, arguments)
    outcome["selection"] = "server_tool_router"
    outcome["fallback"] = False
    outcome["input_summary"] = str(message or "").strip()[:500]
    _record_activity(outcome)
    serialized = json.dumps(outcome, ensure_ascii=False, default=str)
    if len(serialized) > MAX_TOOL_OUTPUT_CHARS:
        outcome["result"] = {"truncated": True, "summary": serialized[:MAX_TOOL_OUTPUT_CHARS]}
    return outcome


__all__ = [
    "TOOL_CATALOG",
    "execute_for_message",
    "execute_tool",
    "recent_activity",
    "select_tool_for_message",
    "tool_catalog_prompt",
]
