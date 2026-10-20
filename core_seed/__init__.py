"""Bounded offline child-factory seeding."""
from .seed_runner import SeedRunner, SeedError

__all__ = ["SeedRunner", "SeedError"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
