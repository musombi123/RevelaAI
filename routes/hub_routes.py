"""Import alias for the native FastAPI hub-persona router."""
from fastapi_routes.hub import router as hub_bp
from services.hub_personas import HUBS, respond

MAX_MESSAGE_CHARS = 8000
MAX_VISION_CHARS = 8000

__all__ = ["hub_bp", "HUBS", "respond", "MAX_MESSAGE_CHARS", "MAX_VISION_CHARS"]
