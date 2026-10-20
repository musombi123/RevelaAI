"""Centralized server-side URL and credential resolution for the USECT cores."""
from __future__ import annotations
import os

_CORE_ENV = {
    "zero": (("USECT_ZERO_URL", "USECT_ZERO_BASE_URL"), ("USECT_ZERO_ADMIN_TOKEN",), "8780"),
    "genesis": (("GENESIS_BASE_URL",), ("GENESIS_ADMIN_TOKEN", "GENESIS_TOKEN"), "8781"),
    "mind": (("MIND_BASE_URL",), ("MIND_ADMIN_TOKEN",), "8782"),
}


def _production() -> bool:
    return os.getenv("RENDER", "").strip().lower() == "true" or os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}


def core_base_url(core: str, *, default: str = "") -> str:
    """Resolve the configured core URL; never invent a loopback URL in production."""
    key = str(core or "").strip().lower()
    if key not in _CORE_ENV:
        raise ValueError("Unknown USECT core name.")
    url_names, _, port = _CORE_ENV[key]
    for name in url_names:
        value = os.getenv(name, "").strip()
        if value:
            return value.rstrip("/")
    if _production():
        return ""
    return (default or f"http://127.0.0.1:{port}").rstrip("/")


def core_admin_token(core: str) -> str:
    """Resolve the server-side administrative token without exposing it to callers."""
    key = str(core or "").strip().lower()
    if key not in _CORE_ENV:
        raise ValueError("Unknown USECT core name.")
    _, names, _ = _CORE_ENV[key]
    return next((os.getenv(name, "").strip() for name in names if os.getenv(name, "").strip()), "")


def core_is_configured(core: str) -> bool:
    return bool(core_base_url(core) and core_admin_token(core))
