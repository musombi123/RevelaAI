"""Import alias for the native FastAPI Living Brain router."""
from fastapi_routes.living_brain import router as living_brain_bp
from ai.living_brain import describe_vision, respond_local

__all__ = ["living_brain_bp", "describe_vision", "respond_local"]
