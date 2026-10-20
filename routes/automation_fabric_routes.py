"""Compatibility import path for the native Automation Fabric FastAPI router."""
from fastapi_routes.automation_fabric import router

automation_fabric_bp = router
__all__ = ["router", "automation_fabric_bp"]
