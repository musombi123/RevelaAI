"""Import aliases for the native FastAPI chat router and orchestration helpers."""
from fastapi_routes.chat import (
    router as chat_bp,
    _load_personalization_context,
    _persist_turn,
    _record_brain_outcome,
    _chat_sync,
    chat_no_slash,
    chat_with_slash,
)
from ai.intent_router import classify_intent
from ai.global_brain_adapter import build_global_context
from ai.hub_prompts import HUB_LABELS, get_identity_answer
from revelai.core.agi_manifest import get_self_description_answer
from services.ai_service import process_message

chat = chat_no_slash

__all__ = [
    "chat_bp", "chat", "chat_no_slash", "chat_with_slash",
    "_load_personalization_context", "_persist_turn", "_record_brain_outcome",
    "_chat_sync", "classify_intent", "build_global_context", "HUB_LABELS",
    "get_identity_answer", "get_self_description_answer", "process_message",
]
