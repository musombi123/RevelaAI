"""Lazy, isolated MongoDB storage for RevelaAI's Elimu learning and credential data.

This module intentionally uses the RevelaAI database, not the upstream
RevelaCode users database. User existence is verified through the account
service; course progress and issued certificates are persisted here.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

_lock = threading.Lock()
_client: MongoClient | None = None


class ElimuStoreUnavailable(RuntimeError):
    pass


def get_database() -> Database:
    global _client
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        raise ElimuStoreUnavailable("MONGO_URI is required for Elimu progress persistence.")
    with _lock:
        if _client is None:
            try:
                _client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                )
                _client.admin.command("ping")
            except Exception as exc:
                _client = None
                raise ElimuStoreUnavailable("Elimu persistence is unavailable.") from exc
    return _client[os.getenv("REVELAAI_DATABASE_NAME", "revelai").strip() or "revelai"]


def collection(name: str):
    if name not in {"elimu_hubs", "elimu_progress", "revela_certificates"}:
        raise ValueError("Unsupported Elimu collection.")
    try:
        return get_database()[name]
    except ElimuStoreUnavailable:
        raise
    except Exception as exc:
        raise ElimuStoreUnavailable("Elimu persistence is unavailable.") from exc


def safe_document(value: Any) -> Any:
    """Convert BSON values and nested documents into JSON-safe primitives."""
    from bson import ObjectId
    from datetime import date, datetime

    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "_id":
                result["id"] = safe_document(item)
            else:
                result[str(key)] = safe_document(item)
        return result
    if isinstance(value, (list, tuple)):
        return [safe_document(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
