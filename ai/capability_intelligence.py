"""Runtime-grounded capability intelligence for RevelaAI.

The inventory describes exact source modules and registered tools, while
keeping source presence, request-level grants, configuration and live health
as separate facts. It never exposes credentials or invokes privileged tools.
"""
from __future__ import annotations

import importlib.util
import json
from typing import Any

from revelai.core.agi_manifest import AGI_MANIFEST

_MAX_TOOLS = 96


def _module_present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _registered_tools() -> list[dict[str, str]]:
    """Read tool names from the same catalogue used to declare Gemini functions."""
    try:
        from ai.gemini_tool_gateway import GENERAL_TOOL_DECLARATIONS, ZERO_TOOL_CATALOG
    except Exception:
        return []
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for source, records in (("general_gateway", GENERAL_TOOL_DECLARATIONS), ("usect_zero", ZERO_TOOL_CATALOG)):
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            items.append({
                "name": name,
                "source": source,
                "scope": str(record.get("scope") or ("authorization_checked_by_gateway" if source == "general_gateway" else "scope_checked_by_gateway")),
                "purpose": str(record.get("description") or "")[:220],
            })
    return items[:_MAX_TOOLS]


def capability_inventory_snapshot() -> dict[str, Any]:
    """Return an evidence-labelled inventory of RevelaAI's actual source catalogue."""
    try:
        from ai.gemini_tool_gateway import CORE_ENGAGEMENT
    except Exception:
        CORE_ENGAGEMENT = {}

    cores = []
    for name, spec in CORE_ENGAGEMENT.items():
        module = str(spec.get("module") or "")
        cores.append({
            "id": name,
            "module": module,
            "source_present": _module_present(module) if module else False,
            "role": str(spec.get("role") or ""),
            "tool_names": list(spec.get("tools") or []),
            "runtime_health": "not_probed_by_this_inventory",
        })

    manifest_caps = AGI_MANIFEST.get("capabilities", {})
    capabilities = []
    for key, value in manifest_caps.items():
        if isinstance(value, dict):
            capabilities.append({
                "id": str(key),
                "description": str(value.get("description") or "")[:260],
                "evidence": str(value.get("verification") or "manifest_recorded"),
            })
        else:
            capabilities.append({"id": str(key), "description": str(value)[:260], "evidence": "manifest_recorded"})

    hubs = {
        "auto": "automatic intent routing",
        "mkulima": "Shamba / agriculture",
        "biashara": "business operations",
        "elimu": "education and learning",
        "mahubiri": "faith, theology and Scripture",
        "general": "programming, technology, research and general assistance",
    }
    tool_catalogue = _registered_tools()
    return {
        "inventory_version": "1.0",
        "identity": AGI_MANIFEST.get("identity", {}).get("name", "RevelaAI"),
        "hubs": hubs,
        "manifest_capabilities": capabilities,
        "registered_gemini_tools": tool_catalogue,
        "registered_tool_count": len(tool_catalogue),
        "core_components": cores,
        "core_component_count": len(cores),
        "evidence_rules": {
            "source_present": "module can be resolved from this deployed source tree; not proof of live operation",
            "registered_tool": "tool appears in the server catalogue; user entitlement and owning service may still gate execution",
            "configured": "credentials/configuration presence must be checked without revealing values",
            "healthy": "requires a successful live provider or service probe",
            "available_this_turn": "only functions actually declared after this request's authorization checks",
        },
        "not_automatically_owned": [
            "third-party tools found during research",
            "uninstalled packages or unconnected plugins",
            "remote services not provisioned in deployment",
            "hardware or devices not enrolled and connected",
            "proposed tools awaiting human review and deployment",
        ],
    }


def build_capability_intelligence_context() -> str:
    """Compact deterministic context injected into every global-brain handoff."""
    snapshot = capability_inventory_snapshot()
    # Keep exact identifiers and tool names, while bounding prompt size.
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))[:18000]
