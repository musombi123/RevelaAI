"""Framework-neutral import path for native Meta-Engineer and admin verification."""
from fastapi_routes.meta_engineer import router
from fastapi_routes.admin_auth import require_platform_admin

__all__ = ["router", "require_platform_admin"]
