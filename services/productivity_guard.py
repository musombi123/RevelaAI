"""Shared safety preflight for all newly introduced productivity tools.

Meta Engineer supplies a read-only architecture check. Sci Defender supplies
the existing defensive pattern catalogue plus prompt-injection screening.
Both checks run before a new tool operation is accepted.
"""
from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache
from typing import Any

LOG = logging.getLogger("revelaai.productivity.guard")
_PROMPT_INJECTION = (
    re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I),
    re.compile(r"reveal (the )?(system prompt|secrets|api keys|credentials)", re.I),
    re.compile(r"you are now (the )?(system|developer|admin)", re.I),
    re.compile(r"send (all )?(files|data|secrets) to https?://", re.I),
)
_LAST_ARCH_SCAN = 0.0
_ARCH_SCAN: dict[str, Any] | None = None


class ProductivitySafetyError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _architecture_snapshot() -> dict[str, Any]:
    global _LAST_ARCH_SCAN, _ARCH_SCAN
    now = time.monotonic()
    if _ARCH_SCAN is not None and now - _LAST_ARCH_SCAN < 45:
        return _ARCH_SCAN
    # Meta Engineer is read-only. It verifies the running architecture and
    # confirms the productivity handler/service remain visible to introspection.
    from meta_engineer.introspector import scan_architecture
    snapshot = scan_architecture()
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("structure"), dict):
        raise ProductivitySafetyError("META_ENGINEER_UNAVAILABLE", "Meta Engineer architecture verification is unavailable.")
    service_files = snapshot["structure"].get("services", [])
    route_files = snapshot["structure"].get("fastapi_routes", [])
    required = {"services/productivity_service.py", "fastapi_routes/productivity.py"}
    discovered = set(service_files) | set(route_files)
    if not required.issubset(discovered):
        raise ProductivitySafetyError("META_ENGINEER_REGISTRATION_MISSING", "Meta Engineer could not verify the registered productivity modules.")
    _ARCH_SCAN = snapshot
    _LAST_ARCH_SCAN = now
    return snapshot


def guard_productivity_tool(tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if Meta Engineer or the Sci Defender checks cannot run."""
    if not isinstance(payload, dict):
        raise ProductivitySafetyError("INVALID_TOOL_INPUT", "The tool input must be a JSON object.")
    _architecture_snapshot()
    # Reuse Sci Defender's established defensive signatures. The scan is
    # limited to user-supplied code/text; source paths and secrets are not logged.
    try:
        from revelai.sci_core.defensive_shield import PATTERNS
    except Exception as exc:
        raise ProductivitySafetyError("SCI_DEFENDER_UNAVAILABLE", "Sci Defender is unavailable; the operation was not started.") from exc
    try:
        text_value = json.dumps(payload, ensure_ascii=False, default=str)[:100_000]
    except (TypeError, ValueError):
        raise ProductivitySafetyError("INVALID_TOOL_INPUT", "The input could not be safely normalized.")
    for pattern, severity, _recommendation in PATTERNS:
        if severity == "critical" and pattern.search(text_value):
            raise ProductivitySafetyError("SCI_DEFENDER_BLOCKED", "Sci Defender blocked a potentially unsafe operation.")
    for pattern in _PROMPT_INJECTION:
        if pattern.search(text_value):
            raise ProductivitySafetyError("SCI_DEFENDER_PROMPT_INJECTION", "Sci Defender detected instructions embedded in untrusted content.")
    LOG.info("Productivity safety preflight passed | tool=%s | meta_engineer=checked | sci_defender=checked",
             str(tool_id)[:64])
    return {"meta_engineer": "checked", "sci_defender": "checked", "passed": True}
