"""Python-native, review-gated factory proposal builder."""
from .factory.foundry_builder import FoundryBuilder, FactoryBuildError

__all__ = ["FoundryBuilder", "FactoryBuildError"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
