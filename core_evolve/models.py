"""Typed contracts shared by the Evolver service and its API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MetricTarget(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    direction: Literal["minimize", "maximize"]
    baseline: float
    target: float
    unit: str = Field(default="", max_length=24)


class EvolutionRequest(StrictModel):
    system_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
    objective: str = Field(min_length=8, max_length=2000)
    metrics: list[MetricTarget] = Field(min_length=1, max_length=12)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    requested_depth: int = Field(default=1, ge=1, le=3)
    twin_baseline: dict[str, float] = Field(default_factory=dict, max_length=20)

    @field_validator("constraints", "evidence_refs")
    @classmethod
    def reject_blank_entries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("entries must not be blank")
        return values


class CandidateProposal(StrictModel):
    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    system_id: str
    parent_proposal_id: str | None = None
    generation: int = Field(ge=1, le=3)
    objective: str
    hypotheses: list[str]
    proposed_changes: list[str]
    success_metrics: list[MetricTarget]
    guardrails: list[str]
    evidence_refs: list[str]
    status: Literal["proposed", "evaluated", "approved", "rejected", "rolled_back"] = "proposed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricResult(StrictModel):
    name: str
    baseline: float
    observed: float | None = None
    target: float
    direction: Literal["minimize", "maximize"]
    passed: bool = False
    note: str = "No measurement supplied; not verified."


class EvaluationReport(StrictModel):
    proposal_id: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: list[MetricResult]
    evidence_complete: bool
    safety_checks_passed: bool
    eligible_for_review: bool
    speedup_ratio: float | None = None
    improvement_factor: float | None = None
    verdict: Literal["insufficient_evidence", "regression", "candidate_for_human_review"]
    notes: list[str] = Field(default_factory=list)


class EvolutionEvaluationInput(StrictModel):
    proposal_id: str = Field(min_length=1, max_length=100)
    observations: dict[str, float] = Field(default_factory=dict, max_length=20)
    test_passed: bool
    security_review_passed: bool
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
