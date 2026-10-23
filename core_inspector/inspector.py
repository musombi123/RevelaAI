"""Evidence-based USECT capability inspection.

This module deliberately distinguishes structural evidence from live readiness.
Presence of code/routes/tests is not proof that private upstream services, secrets,
payment providers, electrical designs, or regulatory certifications are operational.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from starlette.routing import Mount


SOURCE_SUFFIXES = {".py", ".go", ".yaml", ".yml", ".json", ".sql", ".md"}
EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages", ".pytest_cache"}

# These are contract checks for this repository's deployed API. External Elimu
# endpoints remain owned by RevelaCode-Backend and are not misrepresented as
# routes served by RevelaAI.
CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "usect_zero", "name": "USECT-ZERO / Core Zero healer",
        "source_files": ["core-zero/cmd/usect-zero/main.go", "core-zero/internal/api/server.go", "fastapi_routes/usect_zero.py", "services/usect_zero_client.py", "ai/usect_zero_tools.py"],
        "test_files": ["core-zero/internal/api/server_test.go", "tests/test_usect_zero_backend.py", "tests/test_usect_zero_brain_tool.py"],
        "routes": [("GET", "/api/usect-zero/health"), ("POST", "/api/usect-zero/heal/proposals"), ("POST", "/v1/zero/heal")],
        "safety": "Recovery is proposed and explicitly approved; the internal brain identity cannot call admin endpoints.",
    },
    {
        "id": "usect_one", "name": "USECT-ONE / Genesis",
        "source_files": ["core-one/cmd/genesis/main.go", "core-one/genesis/server.go", "core-one/genesis/guardian.go", "ai/core_mesh.py", "fastapi_routes/core_mesh.py"],
        "test_files": ["core-one/genesis/genesis_test.go", "core-one/genesis/tool_guardian_test.go", "tests/test_genesis_tool_dispatch.py"],
        "routes": [("GET", "/api/core-mesh/genesis/status"), ("POST", "/api/core-mesh/genesis/queue"), ("POST", "/v1/one/genesis")],
        "safety": "Genesis actions remain proposals; Guardian, owner approvals, signed artifacts and human review gate activation.",
    },
    {
        "id": "usect_two", "name": "USECT-TWO / Infinite Mind",
        "source_files": ["core-two/cmd/revela-mind/main.go", "core-two/mind/api.go", "core-two/mind/evolve.go", "ai/core_mesh.py", "fastapi_routes/core_mesh.py"],
        "test_files": ["core-two/mind/mind_test.go", "core-two/mind/learning_test.go", "tests/test_genesis_tool_registry.py"],
        "routes": [("POST", "/api/core-mesh/mind/evolve"), ("POST", "/api/core-mesh/mind/candidates"), ("POST", "/v1/two/improve/{tool_id}")],
        "safety": "Candidate assessment and improvement proposals do not auto-run source code, merge, or deploy.",
    },
    {
        "id": "usect_orchestrator", "name": "USECT-ORCHESTRATOR",
        "source_files": ["ai/orchestrator.py", "ai/core_mesh.py", "fastapi_routes/chat.py", "fastapi_routes/core_mesh.py"],
        "test_files": ["tests/test_fastapi_entrypoint.py", "tests/test_core_mesh.py"],
        "routes": [("POST", "/api/chat"), ("POST", "/v1/orchestrator/run")],
        "safety": "Pipeline status identifies queued/proposed steps and never reports an automatic production merge.",
    },
    {
        "id": "living_brain", "name": "USECT-LIVING-BRAIN",
        "source_files": ["ai/living_brain.py", "fastapi_routes/living_brain.py", "fastapi_routes/memory.py", "routes/living_brain_routes.py"],
        "test_files": ["tests/test_fastapi_entrypoint.py", "tests/test_brain_os.py", "tests/test_core_mesh.py"],
        "routes": [("POST", "/api/revelaai/v2/brain/chat"), ("GET", "/api/memory/{user_id}/history")],
        "safety": "Memory is user-scoped; the brain reports fallback/degraded state rather than claiming unavailable evidence.",
    },
    {
        "id": "billing", "name": "USECT-BILLING / Core license enforcement",
        "source_files": ["core_billing/licensing.py", "core_billing/service.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_fastapi_revenue.py", "tests/test_revela_security.py"],
        "routes": [("GET", "/v1/billing/plans"), ("POST", "/v1/billing/buy"), ("POST", "/v1/billing/webhooks/stripe"), ("POST", "/v1/billing/verify")],
        "safety": "Licenses are signed server-side; checkout redirects do not mint licenses before a verified settlement webhook.",
    },
    {
        "id": "meter", "name": "USECT-METER",
        "source_files": ["core_meter/meter.py", "revela_platform/database.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_usect_capability_surface.py"],
        "routes": [("GET", "/v1/meter/usage"), ("GET", "/v1/meter/health")],
        "safety": "Usage events contain operation identifiers and measured outcomes, not prompts or secrets; unverified savings stay zero.",
    },
    {
        "id": "marketplace", "name": "USECT-MARKETPLACE",
        "source_files": ["marketplace/service.py", "revela_platform/fastapi_app.py", "core_uncopyable/dna_vault_guard.py"],
        "test_files": ["tests/test_fastapi_revenue.py", "tests/test_revela_security.py"],
        "routes": [("POST", "/v1/marketplace/publish"), ("GET", "/v1/marketplace/search"), ("POST", "/v1/marketplace/buy"), ("GET", "/v1/marketplace/earnings/me")],
        "safety": "Listings require a signed watermark and human review; recorded revenue uses the 70/30 creator/platform split.",
    },
    {
        "id": "foundry", "name": "USECT-FOUNDRY",
        "source_files": ["core_foundry/factory/foundry_builder.py", "core_foundry/attestation.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_fastapi_revenue.py", "tests/test_revela_security.py"],
        "routes": [("POST", "/v1/foundry/build"), ("GET", "/v1/foundry/builds/{build_id}"), ("POST", "/v1/foundry/builds/{build_id}/review"), ("POST", "/v1/inspector/produce")],
        "safety": "Factory plans are declarative; no untrusted code execution, hardware actuation or production deployment is performed.",
    },
    {
        "id": "seed", "name": "USECT-SEED",
        "source_files": ["core_seed/seed_runner.py", "core_seed/cli.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_fastapi_revenue.py", "tests/test_revela_security.py"],
        "routes": [("POST", "/v1/seed/{build_id}"), ("GET", "/v1/seed/{seed_id}/verify")],
        "safety": "Offline authorization is bounded by the signed lease (at most 30 days); no destructive self-wipe or automatic activation is performed.",
    },
    {
        "id": "auditor", "name": "USECT-AUDIT",
        "source_files": ["core_auditor/ledger.py", "revela_platform/database.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_fastapi_revenue.py", "tests/test_usect_capability_surface.py"],
        "routes": [("GET", "/v1/auditor/verify"), ("GET", "/v1/auditor/events"), ("POST", "/v1/auditor/reports/generate"), ("GET", "/v1/auditor/reports/{report_id}/verify")],
        "safety": "Compliance PDFs are draft evidence reports with QR verification, never counterfeit regulatory certifications.",
    },
    {
        "id": "evolve", "name": "USECT-EVOLVE",
        "source_files": ["core_evolve/engine.py", "core_evolve/models.py", "fastapi_routes/evolve_migrate.py"],
        "test_files": ["tests/test_usect_evolve_migrate.py"],
        "routes": [("GET", "/api/usect/evolve/health"), ("POST", "/api/usect/evolve/proposals"), ("POST", "/api/usect/evolve/proposals/{proposal_id}/evaluate"), ("POST", "/v1/evolve/scan"), ("GET", "/v1/evolve/scans/latest")],
        "safety": "Performance claims require measurements and evidence; evolution remains an isolated human-reviewed proposal.",
    },
    {
        "id": "migrate", "name": "USECT-MIGRATE / robot blueprint",
        "source_files": ["core_migrate/service.py", "core_migrate/models.py", "fastapi_routes/evolve_migrate.py"],
        "test_files": ["tests/test_usect_evolve_migrate.py"],
        "routes": [("POST", "/api/usect/migrate/plans"), ("POST", "/api/usect/migrate/robot-blueprints")],
        "safety": "Devices require explicit enrollment/owner authorization; there is no stealth discovery, remote execution or unattended hardware actuation.",
    },
    {
        "id": "uncopyable", "name": "USECT-UNCOPYABLE / five trust controls",
        "source_files": ["core_uncopyable/recipe_lock.py", "core_uncopyable/license_lock.py", "core_uncopyable/hardware_bind.py", "core_uncopyable/rvx_evolver.py", "core_uncopyable/dna_vault_guard.py", "mesh/rvx_mesh.py", "rvx/crypto.py"],
        "test_files": ["tests/test_usect_uncopyable.py"],
        "routes": [("GET", "/v1/uncopyable/status"), ("POST", "/v1/uncopyable/rotate-dialect"), ("GET", "/v1/verify/{tool_id}")],
        "safety": "Trust controls fail closed where configured; the hardware fingerprint is a software signal, not TPM attestation, and data is not wiped automatically.",
    },
    {
        "id": "inspector", "name": "USECT-INSPECTOR / human-production simulator",
        "source_files": ["core_inspector/inspector.py", "revela_platform/fastapi_app.py"],
        "test_files": ["tests/test_usect_capability_surface.py"],
        "routes": [("GET", "/v1/inspector/inspect"), ("POST", "/v1/inspector/produce")],
        "safety": "The simulator creates a reviewable plan and evidence gaps; it does not fabricate procurement, test, compliance or deployment results.",
    },
    {
        "id": "worldwide", "name": "Worldwide BOM, localization and electrical references",
        "source_files": ["lib/worldwide/bom/bom.go", "lib/worldwide/country/profile.go", "lib/worldwide/i18n/guide.go", "core-one/hardware/worldwide_guide.go"],
        "test_files": ["lib/worldwide/bom/bom_test.go", "lib/worldwide/country/profile_test.go", "lib/worldwide/i18n/guide_test.go"],
        "routes": [("GET", "/api/core-mesh/genesis/tools/{name}/hardware-guide")],
        "safety": "Supplier names are leads, not quotes; 120/230/240V values are references; DIN-rail suitability and datasheets require human/qualified review.",
    },
    {
        "id": "guardian", "name": "Guardian harm-screening and policy",
        "source_files": ["core-one/genesis/guardian.go", "core-one/guardian/rules.yaml", "core-zero/guardian/worldwide_rules.yaml", "core_foundry/factory/foundry_builder.py"],
        "test_files": ["core-one/genesis/tool_guardian_test.go", "core-one/genesis/tool_publication_guardian_test.go"],
        "routes": [("POST", "/v1/one/genesis"), ("POST", "/api/core-mesh/genesis/invent"), ("POST", "/v1/foundry/build")],
        "safety": "The Guardian is a deterministic safety layer, not a complete guarantee; hazardous demands remain subject to specialized review.",
    },
    {
        "id": "elimu_external", "name": "ELIMU learning, profile and certificate routes (external backend)",
        "external": True,
        "source_files": [],
        "test_files": [],
        "routes": [],
        "note": "Owned by RevelaCode-Backend, not the RevelaAI gateway. Inspect that repository and its runtime separately.",
        "safety": "Account certificates must be described as platform participation records, not academic or government accreditation.",
    },
)


def _join(prefix: str, path: str) -> str:
    left = (prefix or "").rstrip("/")
    right = (path or "").strip("/")
    if not right:
        return left or "/"
    return left + "/" + right if left else "/" + right


def _routes_on_app(app: Any) -> list[Any]:
    """Unwrap Starlette middleware stacks until the underlying router is reached."""
    current = app
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        routes = getattr(current, "routes", None)
        if routes is not None:
            return list(routes)
        router = getattr(current, "router", None)
        routes = getattr(router, "routes", None)
        if routes is not None:
            return list(routes)
        current = getattr(current, "app", None)
    return []


def registered_routes(application: Any) -> set[tuple[str, str]]:
    """Read real FastAPI/Starlette route registrations, recursively including mounted apps."""
    discovered: set[tuple[str, str]] = set()
    visited: set[tuple[int, str]] = set()

    def walk(app: Any, prefix: str = "") -> None:
        marker = (id(app), prefix)
        if marker in visited:
            return
        visited.add(marker)
        for route in _routes_on_app(app):
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", None)
            child = getattr(route, "app", None)
            # FastAPI / Starlette can expose a Mount wrapped as an ASGI middleware
            # object, so identify nested applications by their route collection as
            # well as by the concrete Mount class.
            child_routes = _routes_on_app(child) if child is not None and not methods else []
            if child_routes and (isinstance(route, Mount) or not methods):
                child_prefix = _join(prefix, path) if path.strip("/") else prefix
                walk(child, child_prefix)
                continue
            if not path or not methods:
                continue
            full_path = _join(prefix, path)
            for method in methods:
                if method not in {"HEAD", "OPTIONS"}:
                    discovered.add((str(method).upper(), full_path))

    walk(application)
    return discovered


def _count_source_files(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        total += 1
    return total


def inspect_capabilities(root_app: Any, repository_root: str | Path | None = None) -> dict[str, Any]:
    """Compare expected capability modules/tests/routes against the running app."""
    root = Path(repository_root or Path(__file__).resolve().parent.parent).resolve()
    routes = registered_routes(root_app)
    results: list[dict[str, Any]] = []

    for spec in CAPABILITIES:
        if spec.get("external"):
            results.append({
                "id": spec["id"], "name": spec["name"], "status": "external_not_checked",
                "source_files_present": None, "test_files_present": None,
                "routes_present": None, "missing_source_files": [], "missing_test_files": [],
                "missing_routes": [], "note": spec.get("note"), "safety": spec.get("safety"),
            })
            continue

        sources = list(spec.get("source_files", []))
        tests = list(spec.get("test_files", []))
        required_routes = list(spec.get("routes", []))
        missing_sources = [relative for relative in sources if not (root / relative).is_file()]
        missing_tests = [relative for relative in tests if not (root / relative).is_file()]
        missing_routes = [
            {"method": method, "path": path}
            for method, path in required_routes
            if (method.upper(), path) not in routes
        ]
        if missing_sources or missing_routes:
            status = "missing"
        elif missing_tests:
            status = "test_gap"
        else:
            status = "structurally_covered"
        results.append({
            "id": spec["id"], "name": spec["name"], "status": status,
            "source_files_present": len(sources) - len(missing_sources),
            "source_files_required": len(sources),
            "test_files_present": len(tests) - len(missing_tests),
            "test_files_required": len(tests),
            "routes_present": len(required_routes) - len(missing_routes),
            "routes_required": len(required_routes),
            "missing_source_files": missing_sources,
            "missing_test_files": missing_tests,
            "missing_routes": missing_routes,
            "safety": spec.get("safety"),
        })

    internal = [item for item in results if item["status"] != "external_not_checked"]
    passed = sum(item["status"] == "structurally_covered" for item in internal)
    failed = sum(item["status"] != "structurally_covered" for item in internal)
    blockers = []
    if any(item["status"] != "structurally_covered" for item in internal):
        blockers.append("One or more local capabilities have missing source, route, or regression-test evidence.")
    blockers.extend([
        "Structural checks do not prove live private-service reachability, secret validity, payment settlement, or production credentials.",
        "No generated document from this system is itself a CE, UL, ISO, RoHS or FCC certification.",
        "Electrical design, vendor stock/prices, legal conformity, production deployment and physical actuation require independent evidence and qualified/human review.",
        "ELIMU is external to this repository and must be inspected in RevelaCode-Backend.",
    ])
    return {
        "schema_version": "usect-inspector.v1",
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "repository": "RevelaAI",
        "total_files": _count_source_files(root),
        "total_capabilities": len(CAPABILITIES),
        "local_capabilities": len(internal),
        "external_capabilities": len(results) - len(internal),
        "passed": passed,
        "failed": failed,
        "structurally_covered": failed == 0,
        "ready_for_production": False,
        "production_blockers": blockers,
        "checks": results,
        "interpretation": "This is an evidence inventory. A source file, route declaration, or test file is not proof that the live service is healthy or certified.",
    }


__all__ = ["CAPABILITIES", "inspect_capabilities", "registered_routes"]
