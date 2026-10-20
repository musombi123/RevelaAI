"""Compatibility import path for the native Living Brain FastAPI router."""
from fastapi_routes.living_brain import router

living_brain_bp = router
__all__ = ["router", "living_brain_bp"]
