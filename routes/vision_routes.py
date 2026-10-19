"""Import alias for the native FastAPI Vision router."""
from fastapi_routes.vision import router as vision_bp
from fastapi_routes.vision import _decode_image, _analyze_sync

__all__ = ["vision_bp", "_decode_image", "_analyze_sync"]
