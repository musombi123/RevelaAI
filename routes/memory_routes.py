"""Framework-neutral Smart Memory imports for older Python callers.

Use :mod:`fastapi_routes.memory` for HTTP handlers and :mod:`services.memory_store`
for persistence. No framework-specific request context is exposed here.
"""
from fastapi_routes.memory import router
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
    "router", "_collection", "_detect_and_store_ideas", "_iso", "_json_safe",
    "_normalize", "_now", "_record_messages", "_recent_messages",
    "_remember_best_things", "conversations", "ideas", "isBestThing",
    "isUsefulMemory", "learnings", "memories",
]
