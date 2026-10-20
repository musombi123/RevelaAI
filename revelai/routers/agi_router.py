"""Compatibility import alias for the native FastAPI AGI router.

The Flask blueprint was retired when the runtime moved to ASGI. Register the
router from :mod:`fastapi_routes.agi` on the application instead.
"""
from fastapi_routes.agi import router as agi_router

__all__ = ["agi_router"]
