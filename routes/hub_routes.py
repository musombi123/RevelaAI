"""Compatibility import path for the native hub persona FastAPI router."""
from fastapi_routes.hub import router

hub_bp = router
__all__ = ["router", "hub_bp"]
