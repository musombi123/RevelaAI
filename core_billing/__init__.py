"""Revenue enforcement and signed license issuance for RevelaCode."""
from .licensing import LicenseError, verify_license_token

__all__ = ["LicenseError", "verify_license_token"]

# Enforce owner recipe integrity in hardened deployments.
from core_uncopyable.recipe_lock import guard_core_startup

guard_core_startup()
