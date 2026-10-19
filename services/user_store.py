"""Temporary in-process user store shared during the Flask-to-FastAPI transition.

Replace this with the project's authoritative persistence layer before scaling
beyond one process; this module intentionally preserves current behavior.
"""
from __future__ import annotations

USERS: dict[str, dict[str, str]] = {}
