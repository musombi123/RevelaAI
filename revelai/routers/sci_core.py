"""Compatibility import for older internal references; no Flask blueprint."""
from fastapi_routes.sci_core import router as sci_router

__all__ = ["sci_router"]
