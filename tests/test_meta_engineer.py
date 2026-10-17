"""Regression tests for review-gated Meta-Engineer proposal generation."""
from meta_engineer.generator import generate_feature
from meta_engineer.introspector import scan_architecture
from meta_engineer.integrator import _safe_path, ForbiddenError

def test_requested_health_route_is_generated_as_proposal():
    result = generate_feature("Add endpoint GET /api/health/meta that returns meta-engineer status")
    assert result["kind"] == "python_flask_route_proposal"
    assert '@router.get("/api/health/meta")' in result["code"]
    assert "proposal_only" in result["code"]
    assert result["runtime_integration"] == "disabled_until_human_approval"

def test_generator_rejects_empty_spec():
    try:
        generate_feature("")
    except ValueError:
        return
    raise AssertionError("empty spec must be rejected")

def test_architecture_scan_is_read_only_and_reports_database_boundary():
    result = scan_architecture()
    assert result["read_only"] is True
    assert result["framework"] == "Flask; no FastAPI assumption"
    assert "revelacode.users" not in str(result).lower()

def test_protected_paths_are_rejected():
    try:
        _safe_path("revelai/core/config.py")
    except ForbiddenError:
        return
    raise AssertionError("protected path must be rejected")
