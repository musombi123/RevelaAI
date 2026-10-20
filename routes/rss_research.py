"""Compatibility import path for the native FastAPI research router."""
from fastapi_routes.research import router

rss_bp = router
__all__ = ["router", "rss_bp"]
