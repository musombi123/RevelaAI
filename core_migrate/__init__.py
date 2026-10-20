"""USECT-MIGRATE: authorized device enrollment and deployment planning."""
from .service import MigrationService

__all__ = ["MigrationService"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
