"""Compatibility import path for the native Meta-Engineer FastAPI router."""
from fastapi_routes.meta_engineer import router

meta_engineer_bp = router
__all__ = ["router", "meta_engineer_bp"]
