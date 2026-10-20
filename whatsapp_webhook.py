"""Backward-compatible import names for the native FastAPI WhatsApp router.

The historical module name is retained for import compatibility only. The
exported `whatsapp_bp` is now a FastAPI APIRouter, not a Flask Blueprint.
Register `router` once through `asgi.py`; do not mount this alias separately.
"""
from fastapi_routes.whatsapp import (
    ACCESS_TOKEN,
    GRAPH_API_URL,
    PHONE_NUMBER_ID,
    VERIFY_TOKEN,
    decode_scripture,
    receive_message,
    router,
    send_whatsapp_message,
    verify_webhook,
)

# Preserve the old variable name as a native FastAPI router alias.
whatsapp_bp = router

__all__ = [
    "ACCESS_TOKEN",
    "GRAPH_API_URL",
    "PHONE_NUMBER_ID",
    "VERIFY_TOKEN",
    "decode_scripture",
    "receive_message",
    "router",
    "send_whatsapp_message",
    "verify_webhook",
    "whatsapp_bp",
]
