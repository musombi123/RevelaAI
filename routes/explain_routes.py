"""Compatibility import path for the native explainability FastAPI router."""
from fastapi_routes.explain import router

explain_bp = router
__all__ = ["router", "explain_bp"]
