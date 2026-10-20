"""Worldwide usage metering and user-scoped reporting."""

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
