"""Versioned capability contract for RevelaAI's expandable invention factory.

This is an inventory/activation contract, not a second signed tool registry.
Genesis remains authoritative for executable tool artifacts and versions.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import StrictModel

SCHEMA_VERSION = "revela.factory-capability.v1"


class FactoryCapability(StrictModel):
    schema_version: Literal["revela.factory-capability.v1"] = SCHEMA_VERSION
    capability_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_.-]+$")
    owner: str = Field(min_length=2, max_length=80)
    domain: Literal[
        "intelligence", "learning", "invention", "engineering",
        "security", "orchestration", "hardware",
    ]
    purpose: str = Field(min_length=8, max_length=500)
    module: str | None = Field(default=None, max_length=160)
    source_path: str | None = Field(default=None, max_length=240)
    dependencies: list[str] = Field(default_factory=list, max_length=20)
    lifecycle: Literal["implemented", "experimental", "planned", "disabled"]
    runtime_probe: Literal["module_presence", "mongodb", "external_service", "source_file"]
    approval_policy: Literal[
        "none", "human_review", "owner_approval", "owner_and_operator",
    ]
    execution_boundary: Literal[
        "proposal_only", "sandbox_only", "signed_registry", "read_only", "physical_actuation_disabled",
    ]


_CATALOG: tuple[FactoryCapability, ...] = (
    FactoryCapability(
        capability_id="evolver.metric_proposals",
        owner="USECT-EVOLVE",
        domain="learning",
        purpose="Create bounded metric-driven improvement proposals and child generations.",
        module="core_evolve.engine",
        dependencies=["mongodb:revelai.evolution_runs"],
        lifecycle="implemented",
        runtime_probe="mongodb",
        approval_policy="human_review",
        execution_boundary="proposal_only",
    ),
    FactoryCapability(
        capability_id="evolver.evidence_ledger",
        owner="USECT-EVOLVE",
        domain="learning",
        purpose="Persist privacy-minimized proposals, evaluations and verified metric history.",
        module="core_evolve.learning",
        dependencies=["mongodb:revelai.evolution_runs", "sci_core:shared_mongo_client"],
        lifecycle="implemented",
        runtime_probe="mongodb",
        approval_policy="none",
        execution_boundary="read_only",
    ),
    FactoryCapability(
        capability_id="genesis.invention_factory",
        owner="Genesis / Core-One",
        domain="invention",
        purpose="Research and create reviewable software and hardware invention packages.",
        source_path="core-one/genesis/engine.go",
        dependencies=["GENESIS_BASE_URL", "GENESIS_ADMIN_TOKEN"],
        lifecycle="implemented",
        runtime_probe="external_service",
        approval_policy="human_review",
        execution_boundary="proposal_only",
    ),
    FactoryCapability(
        capability_id="genesis.signed_tool_registry",
        owner="Genesis / Core-One",
        domain="engineering",
        purpose="Guardian-screen, sandbox-test, sign, version and activate immutable tool artifacts.",
        module="ai.tool_registry",
        source_path="core-one/genesis/tool_registry.go",
        dependencies=["Genesis signing key", "Genesis sandbox", "owner approval for risk tiers 1 and 2"],
        lifecycle="implemented",
        runtime_probe="external_service",
        approval_policy="owner_approval",
        execution_boundary="signed_registry",
    ),
    FactoryCapability(
        capability_id="brain_os.outcome_learning",
        owner="Brain OS",
        domain="intelligence",
        purpose="Record privacy-minimized delivery, task-quality, latency and feedback outcomes.",
        module="revelai.core.brain_os",
        dependencies=["mongodb:revelai.brain_outcomes"],
        lifecycle="implemented",
        runtime_probe="module_presence",
        approval_policy="none",
        execution_boundary="read_only",
    ),
    FactoryCapability(
        capability_id="meta_engineer.architecture_review",
        owner="Meta Engineer",
        domain="engineering",
        purpose="Inspect source structure and dependency relationships before factory work.",
        module="meta_engineer.introspector",
        dependencies=["read_only_source_access"],
        lifecycle="implemented",
        runtime_probe="module_presence",
        approval_policy="none",
        execution_boundary="read_only",
    ),
    FactoryCapability(
        capability_id="sci_defender.preflight",
        owner="Sci-Core Defensive Shield",
        domain="security",
        purpose="Scan the RevelaAI Python codebase for high-risk defensive findings before factory operations.",
        module="revelai.sci_core.defensive_shield",
        dependencies=["local_source_access", "mongodb:revelai.shields"],
        lifecycle="implemented",
        runtime_probe="module_presence",
        approval_policy="none",
        execution_boundary="read_only",
    ),
    FactoryCapability(
        capability_id="automation_fabric.plan_execution",
        owner="Automation Fabric",
        domain="orchestration",
        purpose="Plan bounded tool workflows with scopes, consent, expiry and one-shot execution.",
        module="automation_fabric.engine",
        dependencies=["workspace_policy", "explicit_user_consent"],
        lifecycle="implemented",
        runtime_probe="module_presence",
        approval_policy="human_review",
        execution_boundary="sandbox_only",
    ),
    FactoryCapability(
        capability_id="hardware.robot_blueprints",
        owner="USECT-MIGRATE",
        domain="hardware",
        purpose="Produce hardware and robot blueprints with inventory and authorization checks.",
        module="core_migrate.service",
        dependencies=["verified_device_inventory", "device_owner_authorization"],
        lifecycle="implemented",
        runtime_probe="module_presence",
        approval_policy="owner_and_operator",
        execution_boundary="physical_actuation_disabled",
    ),
)


def _present(module: str | None, source_path: str | None, root: Path) -> bool:
    if source_path:
        candidate = (root / source_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return False
        return candidate.is_file()
    if module:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False
    return False


def capability_registry() -> dict[str, Any]:
    """Return source presence separately from runtime readiness and activation."""
    root = Path(__file__).resolve().parents[1]
    result: list[dict[str, Any]] = []
    for capability in _CATALOG:
        item = capability.model_dump(mode="json")
        present = _present(capability.module, capability.source_path, root)
        item["source_present"] = present
        if not present:
            item["runtime_state"] = "missing"
        elif capability.runtime_probe == "mongodb":
            try:
                from .learning import ensure_available
                ensure_available()
            except Exception:
                item["runtime_state"] = "blocked"
            else:
                item["runtime_state"] = "available"
        elif capability.runtime_probe == "external_service":
            item["runtime_state"] = "not_probed"
        else:
            item["runtime_state"] = "not_probed"
        result.append(item)

    return {
        "schema_version": SCHEMA_VERSION,
        "registry_kind": "capability_inventory_not_executable_tool_registry",
        "capability_count": len(result),
        "capabilities": result,
        "activation_policy": (
            "Source presence does not prove readiness. External services require live probes; "
            "signed tools require Genesis verification and risk-tier approval. "
            "No capability may grant itself permissions or activate physical actuation."
        ),
    }
