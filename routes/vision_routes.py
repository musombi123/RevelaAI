"""Compatibility import path for the native Live Vision FastAPI router."""
from fastapi_routes.vision import router

vision_bp = router
__all__ = ["router", "vision_bp"]
