"""USECT-EVOLVE: evidence-driven, bounded recursive improvement for RevelaAI."""

from .engine import EvolutionEngine
from .models import CandidateProposal, EvolutionRequest, EvaluationReport

__all__ = ["EvolutionEngine", "EvolutionRequest", "CandidateProposal", "EvaluationReport"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
