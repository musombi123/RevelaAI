"""Import alias for the native FastAPI prototype-users router."""
from fastapi_routes.users import router as users_bp
from fastapi_routes.users import USERS

__all__ = ["users_bp", "USERS"]
