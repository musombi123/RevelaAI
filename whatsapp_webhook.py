"""Compatibility imports for the native FastAPI WhatsApp webhook."""
from fastapi_routes.whatsapp import (
    router as whatsapp_bp,
    VERIFY_TOKEN,
    ACCESS_TOKEN,
    PHONE_NUMBER_ID,
    GRAPH_API_URL,
    verify_webhook,
    receive_message,
    send_whatsapp_message,
    decode_scripture,
)

__all__ = [
    "whatsapp_bp", "VERIFY_TOKEN", "ACCESS_TOKEN", "PHONE_NUMBER_ID",
    "GRAPH_API_URL", "verify_webhook", "receive_message",
    "send_whatsapp_message", "decode_scripture",
]
