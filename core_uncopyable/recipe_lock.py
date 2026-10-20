"""Fail-closed owner recipe verification for RevelaAI runtime deployments."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

from rvx.crypto import RecipeError, default_master_key_path, load_master_key


FOUNDER_MESSAGE = "Need RevelaCode Brain - Contact founder"


class RecipeLockError(RuntimeError):
    """The local recipe is missing, invalid, or does not match the expected lock."""


def verify_recipe(*, strict_path: bool | None = None) -> dict[str, Any]:
    """Verify the 4096-bit owner recipe without returning key material.

    REVELA_RECIPE_EXPECTED_SHA256 is optional and should be provisioned out of
    band when deployments need an independently pinned recipe digest. The
    recipe file itself must never be committed to source control.
    """
    path = default_master_key_path().resolve()
    strict = (
        os.getenv("REVELA_UNCOPYABLE_STRICT_PATH", "").strip().lower() in {"1", "true", "yes"}
        if strict_path is None else strict_path
    )
    if strict:
        repository = Path(__file__).resolve().parent.parent
        try:
            path.relative_to(repository)
        except ValueError:
            pass
        else:
            raise RecipeLockError(f"{FOUNDER_MESSAGE}: owner recipe must live outside the repository.")
    try:
        key = load_master_key(path)
    except RecipeError as exc:
        raise RecipeLockError(f"{FOUNDER_MESSAGE}: owner recipe is unavailable or invalid.") from exc
    digest = hashlib.sha256(key).hexdigest()
    expected = os.getenv("REVELA_RECIPE_EXPECTED_SHA256", "").strip().lower()
    if expected and not hmac.compare_digest(digest, expected):
        raise RecipeLockError(f"{FOUNDER_MESSAGE}: owner recipe fingerprint mismatch.")
    if os.name != "nt":
        try:
            mode = path.stat().st_mode & 0o777
        except OSError as exc:
            raise RecipeLockError(f"{FOUNDER_MESSAGE}: recipe file cannot be inspected.") from exc
        if mode & 0o077:
            raise RecipeLockError("Owner recipe permissions are too broad; set master.key to mode 0600.")
    return {
        "valid": True,
        "algorithm": "SHA-256 fingerprint (digest not exposed)",
        "key_bits": len(key) * 8,
        "path_configured": True,
        "digest_pinned": bool(expected),
    }


def recipe_lock_status() -> dict[str, Any]:
    try:
        return {"locked": True, **verify_recipe()}
    except RecipeLockError as exc:
        return {"locked": False, "reason": str(exc)}


def guard_core_startup() -> None:
    """Apply the recipe gate from Python core packages in strict deployments."""
    enabled = os.getenv("REVELA_UNCOPYABLE_ENFORCE", "").strip().lower() in {"1", "true", "yes", "on"}
    if enabled:
        verify_recipe(strict_path=True)
