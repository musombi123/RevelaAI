"""Compatibility import path for the native Smart Memory FastAPI router."""
from fastapi_routes.memory import router

memory_bp = router
__all__ = ["router", "memory_bp"]
