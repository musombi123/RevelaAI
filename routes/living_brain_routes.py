"""Framework-neutral import path for the native Living Brain router."""
from fastapi_routes.living_brain import router
from ai.living_brain import describe_vision, respond_local

__all__ = ["router", "describe_vision", "respond_local"]
