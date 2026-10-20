"""Compatibility import for older internal references; no Flask blueprint."""
from fastapi_routes.agi import router as agi_router

__all__ = ["agi_router"]
