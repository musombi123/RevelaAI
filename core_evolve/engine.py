"""Bounded recursive evolution engine.

The engine produces auditable proposals and scores supplied benchmark evidence. It
never edits the running service, executes generated source, or promotes a candidate
without a separate human approval step.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .models import (
    CandidateProposal,
    EvolutionRequest,
    EvaluationReport,
    EvolutionEvaluationInput,
    MetricResult,
)


class EvolutionError(RuntimeError):
    """Invalid evolution state or persistence failure."""


class EvolutionEngine:
    MAX_GENERATION = 3

    def __init__(self, store_dir: str | Path | None = None) -> None:
        root = store_dir or os.getenv("REVELA_EVOLVE_STORE", ".revela/evolve")
        self.store_dir = Path(root).expanduser().resolve()
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _proposal_path(self, proposal_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", proposal_id):
            raise EvolutionError("Invalid proposal identifier.")
        return self.store_dir / f"{proposal_id}.json"

    def _save(self, proposal: CandidateProposal) -> None:
        target = self._proposal_path(proposal.proposal_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)

    def get(self, proposal_id: str) -> CandidateProposal:
        path = self._proposal_path(proposal_id)
        if not path.is_file():
            raise KeyError(proposal_id)
        return CandidateProposal.model_validate_json(path.read_text(encoding="utf-8"))

    def propose(self, request: EvolutionRequest, *, parent_proposal_id: str | None = None) -> CandidateProposal:
        generation = 1
        if parent_proposal_id:
            parent = self.get(parent_proposal_id)
            if parent.system_id != request.system_id:
                raise EvolutionError("A recursive proposal must remain within the same system scope.")
            generation = parent.generation + 1
        if generation > min(request.requested_depth, self.MAX_GENERATION):
            raise EvolutionError("Recursive evolution depth limit reached; create a new reviewed evolution cycle.")

        hypotheses: list[str] = []
        changes: list[str] = []
        for metric in request.metrics:
            hypotheses.append(
                f"Changing the system to {metric.direction} '{metric.name}' from "
                f"{metric.baseline:g} toward {metric.target:g} may improve the stated objective."
            )
            changes.append(
                f"Create an isolated experiment for metric '{metric.name}'; preserve the current "
                "version and compare against the supplied baseline."
            )
        if request.twin_baseline:
            changes.append(
                "Run a reproducible side-by-side benchmark against the declared twin baseline; "
                "report cost, latency, reliability and compliance evidence separately."
            )
        if generation > 1:
            hypotheses.append(
                "Evaluate the evolution workflow itself: measure proposal quality, test coverage, "
                "rollback correctness and time-to-verified-improvement."
            )
            changes.append(
                "Propose improvements to the evaluator only as a separately tested candidate; "
                "do not mutate the active evaluator in place."
            )

        proposal = CandidateProposal(
            system_id=request.system_id,
            parent_proposal_id=parent_proposal_id,
            generation=generation,
            objective=request.objective,
            hypotheses=hypotheses,
            proposed_changes=changes,
            success_metrics=request.metrics,
            guardrails=[
                "No generated code executes during proposal creation.",
                "No production self-modification; candidate changes remain isolated until review.",
                "Reject changes that weaken authentication, licensing, auditability, or safety checks.",
                "Require reproducible tests and a rollback artifact before deployment.",
                "Never claim a performance multiplier without benchmark evidence.",
            ],
            evidence_refs=request.evidence_refs,
        )
        self._save(proposal)
        return proposal

    def evaluate(self, proposal_id: str, result: EvolutionEvaluationInput) -> EvaluationReport:
        proposal = self.get(proposal_id)
        if result.proposal_id != proposal.proposal_id:
            raise EvolutionError("Evaluation proposal ID does not match the stored proposal.")

        metric_results: list[MetricResult] = []
        for target in proposal.success_metrics:
            observed = result.observations.get(target.name)
            passed = False
            note = "No measurement supplied; not verified."
            if observed is not None:
                passed = observed <= target.target if target.direction == "minimize" else observed >= target.target
                note = "Target met." if passed else "Target not met."
            metric_results.append(
                MetricResult(
                    name=target.name,
                    baseline=target.baseline,
                    observed=observed,
                    target=target.target,
                    direction=target.direction,
                    passed=passed,
                    note=note,
                )
            )

        evidence_complete = bool(result.evidence_refs or proposal.evidence_refs) and all(
            metric.observed is not None for metric in metric_results
        )
        safety_passed = bool(result.test_passed and result.security_review_passed)
        all_metrics_pass = bool(metric_results) and all(metric.passed for metric in metric_results)
        eligible = evidence_complete and safety_passed and all_metrics_pass
        baseline_latency = next((m.baseline for m in metric_results if m.name in {"latency_ms", "latency"}), None)
        observed_latency = next((m.observed for m in metric_results if m.name in {"latency_ms", "latency"}), None)
        speedup = None
        if baseline_latency and observed_latency and baseline_latency > 0 and observed_latency > 0:
            speedup = round(baseline_latency / observed_latency, 4)

        notes = []
        if not evidence_complete:
            notes.append("Supply measurements for every target and at least one evidence reference.")
        if not safety_passed:
            notes.append("Both the test suite and independent security review must pass.")
        if not all_metrics_pass:
            notes.append("One or more declared metric targets were not met.")
        if eligible:
            notes.append("Eligible for human review only; this report does not authorize deployment.")
        verdict = (
            "candidate_for_human_review" if eligible else
            "regression" if any(m.observed is not None and not m.passed for m in metric_results) else
            "insufficient_evidence"
        )
        return EvaluationReport(
            proposal_id=proposal.proposal_id,
            metrics=metric_results,
            evidence_complete=evidence_complete,
            safety_checks_passed=safety_passed,
            eligible_for_review=eligible,
            speedup_ratio=speedup,
            improvement_factor=speedup,
            verdict=verdict,
            notes=notes,
        )
