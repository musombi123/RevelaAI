"""Compatibility import path for the native prototype-users FastAPI router."""
from fastapi_routes.users import router

users_bp = router
__all__ = ["router", "users_bp"]
