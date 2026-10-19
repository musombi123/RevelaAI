"""Compatibility imports for native FastAPI Smart Memory and framework-neutral storage.

No Flask request context or Blueprint is provided. Use the registered router from
:mod:`fastapi_routes.memory` for HTTP handling.
"""
from fastapi_routes.memory import router as memory_bp
from services.memory_store import (
    _collection,
    _detect_and_store_ideas,
    _iso,
    _json_safe,
    _normalize,
    _now,
    _record_messages,
    _recent_messages,
    _remember_best_things,
    conversations,
    ideas,
    isBestThing,
    isUsefulMemory,
    learnings,
    memories,
)

__all__ = [
    "memory_bp", "_collection", "_detect_and_store_ideas", "_iso", "_json_safe",
    "_normalize", "_now", "_record_messages", "_recent_messages",
    "_remember_best_things", "conversations", "ideas", "isBestThing",
    "isUsefulMemory", "learnings", "memories",
]
