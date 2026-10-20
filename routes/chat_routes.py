"""Compatibility import path for the native authenticated FastAPI chat router."""
from fastapi_routes.chat import router

chat_bp = router
__all__ = ["router", "chat_bp"]
