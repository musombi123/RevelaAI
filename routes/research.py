"""Compatibility import path for the native FastAPI research router."""
from fastapi_routes.research import router

research_bp = router
__all__ = ["router", "research_bp"]
