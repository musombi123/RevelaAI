"""Compatibility facade for the legacy RevelaAI Flask application.

The FastAPI application is defined in :mod:`asgi`. Legacy routes are retained
in :mod:`legacy_flask_app` only to protect endpoints reserved for migration.

This module deliberately delegates unknown attributes so older imports such as
`import app as legacy` and `from app import process_message` continue working.
Do not add HTTP routes here; register new endpoints with FastAPI routers.
"""
from __future__ import annotations

from typing import Any

import legacy_flask_app as _legacy_app_module

# Preserve the historical WSGI application import for compatibility.
app = _legacy_app_module.app

# Preserve the public module surface for legacy star-import callers.
__all__ = sorted(
    name for name in dir(_legacy_app_module)
    if not name.startswith("__")
)


def __getattr__(name: str) -> Any:
    """Delegate backwards-compatible access to the isolated legacy module."""
    try:
        return getattr(_legacy_app_module, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None


def __dir__() -> list[str]:
    """Expose legacy names to IDEs, debuggers and introspection tools."""
    return sorted(set(globals()) | set(dir(_legacy_app_module)))


if __name__ == "__main__":
    # Keep the prior local development command operational.
    app.run(
        host="0.0.0.0",
        port=_legacy_app_module.PORT,
        debug=_legacy_app_module.ENVIRONMENT == "development",
    )
