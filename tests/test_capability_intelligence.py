from __future__ import annotations

from ai.capability_intelligence import build_capability_intelligence_context, capability_inventory_snapshot
from ai.global_brain_adapter import build_global_context


def test_capability_inventory_contains_exact_hubs_cores_and_registered_tools():
    inventory = capability_inventory_snapshot()

    assert {"auto", "mkulima", "biashara", "elimu", "mahubiri", "general"} <= set(inventory["hubs"])
    assert inventory["core_component_count"] >= 15
    assert inventory["registered_tool_count"] > 0
    assert any(item["id"] == "core_foundry" for item in inventory["core_components"])
    assert any(item["id"] == "vision" for item in inventory["manifest_capabilities"])
    assert any(item["name"] == "revelaai_research" for item in inventory["registered_gemini_tools"])
    assert "not_automatically_owned" in inventory


def test_every_global_brain_context_receives_capability_intelligence():
    system, _metadata = build_global_context("What can you build for me?", "auto")

    assert "LIVE CAPABILITY INTELLIGENCE" in system["content"]
    assert "registered_gemini_tools" in system["content"]
    assert "core_component_count" in system["content"]
    assert "authorization" in system["content"]
    assert "not proof of live service health" in system["content"] or "not a promise of live service health" in system["content"]


def test_inventory_context_is_bounded_and_secret_free():
    context = build_capability_intelligence_context()

    assert len(context) <= 18_000
    assert "api_key" not in context.lower()
    assert "private_key" not in context.lower()
