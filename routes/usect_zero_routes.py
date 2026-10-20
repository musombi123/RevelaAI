"""Compatibility import path for the native USECT-ZERO FastAPI router."""
from fastapi_routes.usect_zero import router

usect_zero_bp = router
__all__ = ["router", "usect_zero_bp"]
