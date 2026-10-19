"""Framework-neutral import path for the native hub-persona router."""
from fastapi_routes.hub import router
from services.hub_personas import HUBS, respond

MAX_MESSAGE_CHARS = 8000
MAX_VISION_CHARS = 8000

__all__ = ["router", "HUBS", "respond", "MAX_MESSAGE_CHARS", "MAX_VISION_CHARS"]
