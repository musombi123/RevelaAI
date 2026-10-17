"""Safe proposal persistence and audit trail in the revelai database only."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "").strip()
try:
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000) if MONGO_URI else None
except Exception:
    _client = None
db = _client["revelai"] if _client is not None else None
ideas_col = db["ideas"] if db is not None else None
changelogs_col = db["changelogs"] if db is not None else None

class ForbiddenError(PermissionError):
    """Raised when a requested operation crosses the protected-code boundary."""

def _safe_path(path: str | Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    candidate = (root / Path(path)).resolve()
    protected = [(root / "revelai" / "routers" / "auth.py").resolve(),
                 (root / "revelai" / "middleware" / "security.py").resolve(),
                 (root / "revelai" / "core" / "config.py").resolve(),
                 (root / "revelai" / "core").resolve(),
                 (root / "revelai" / "middleware" / "security.py").resolve()]
    if any(candidate == item or item in candidate.parents for item in protected):
        raise ForbiddenError("Protected path cannot be modified")
    if root not in candidate.parents: raise ForbiddenError("Path escapes repository root")
    return candidate

def immutable_core_check(function):
    """Guard any future file-writing helper against immutable core paths."""
    def guarded(path, *args, **kwargs):
        _safe_path(path)
        return function(path, *args, **kwargs)
    guarded.__name__ = getattr(function, "__name__", "guarded")
    guarded.__doc__ = getattr(function, "__doc__", None)
    return guarded

def audit(action: str, spec: str, code_path: str | None, test_result: dict[str, Any] | None,
          actor: str, extra: dict[str, Any] | None = None) -> None:
    if changelogs_col is None: raise RuntimeError("MONGO_URI required; audit storage unavailable")
    changelogs_col.insert_one({"action": action, "spec": spec, "code_path": code_path,
        "test_result": test_result, "timestamp": datetime.now(timezone.utc),
        "actor": actor, "extra": extra or {}})

def save_idea(document: dict[str, Any]) -> str:
    if ideas_col is None: raise RuntimeError("MONGO_URI required; idea storage unavailable")
    return str(ideas_col.insert_one(document).inserted_id)

def get_idea(idea_id: str):
    if ideas_col is None: raise RuntimeError("MONGO_URI required; idea storage unavailable")
    from bson import ObjectId
    from bson.errors import InvalidId
    try: oid = ObjectId(idea_id)
    except (InvalidId, TypeError, ValueError): return None
    return ideas_col.find_one({"_id": oid})

def update_idea(idea_id: str, update: dict[str, Any]) -> bool:
    if ideas_col is None: raise RuntimeError("MONGO_URI required; idea storage unavailable")
    from bson import ObjectId
    from bson.errors import InvalidId
    try: oid = ObjectId(idea_id)
    except (InvalidId, TypeError, ValueError): return False
    return ideas_col.update_one({"_id": oid}, update).modified_count == 1
