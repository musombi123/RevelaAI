"""Import alias for the native FastAPI Meta-Engineer router."""
from fastapi_routes.meta_engineer import router as meta_engineer_bp
from fastapi_routes.admin_auth import require_platform_admin

__all__ = ["meta_engineer_bp", "require_platform_admin"]
