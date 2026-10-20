"""Regression tests for the deterministic self-building core."""
import pytest

from meta_engineer.generator import generate_feature


def test_backend_target_builds_a_native_fastapi_route_proposal():
    result = generate_feature("Add endpoint GET /api/health/meta that returns module status", target="backend")
    assert result["target"] == "backend"
    assert result["kind"] == "python_fastapi_route_proposal"
    assert result["code_path"].endswith(".py")
    assert '@router.get("/api/health/meta")' in result["code"]
    assert "from fastapi import APIRouter, Request" in result["code"]
    assert "router = APIRouter()" in result["code"]
    assert "from flask import" not in result["code"]
    assert "proposal_only" in result["code"]
    assert result["files"][0]["role"] == "backend_route"
    assert result["runtime_integration"] == "disabled_until_human_approval"


def test_frontend_target_builds_a_react_component():
    result = generate_feature("Build a weather card with temperature and location", target="frontend")
    assert result["kind"] == "react_component_proposal"
    assert result["files"][0]["path"].endswith(".jsx")
    assert "export default function " in result["code"]
    assert "FEATURE_SPEC" in result["code"]
    assert "Proposal" in result["code"]


def test_database_target_builds_document_contract_without_connecting_to_mongo():
    result = generate_feature("Store a saved study with a title and status", target="database")
    assert result["kind"] == "python_document_schema_proposal"
    assert result["files"][0]["path"].endswith("_model.py")
    assert "class FeatureProposalRecord" in result["code"]
    assert "def to_document" in result["code"]
    assert "MongoClient" not in result["code"]


def test_fullstack_target_builds_all_three_artifact_types():
    result = generate_feature("Build a school notices feature", target="fullstack")
    assert result["kind"] == "fullstack_proposal_bundle"
    assert len(result["files"]) == 3
    assert {item["role"] for item in result["files"]} == {
        "backend_route", "document_schema", "frontend_component"
    }
    assert all(item["content"] and item["path"] for item in result["files"])


def test_previous_wrapped_generator_call_still_parses_target():
    result = generate_feature(
        "Target surface: frontend. Feature specification: Build a profile card"
    )
    assert result["target"] == "frontend"
    assert result["files"][0]["path"].endswith(".jsx")


@pytest.mark.parametrize("target", ["admin", "shell", "../backend", ""])
def test_unknown_targets_are_rejected(target):
    with pytest.raises(ValueError):
        generate_feature("Build a proposal", target=target)


def test_destructive_and_protected_specs_are_rejected():
    with pytest.raises(ValueError):
        generate_feature("Delete core and replace auth")
    with pytest.raises(ValueError):
        generate_feature("Add endpoint DELETE /api/users/{id}", target="backend")


def test_invalid_specification_is_rejected():
    with pytest.raises(ValueError):
        generate_feature("")
    with pytest.raises(ValueError):
        generate_feature("x" * 1001)
