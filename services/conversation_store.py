"""Framework-neutral bounded conversation session storage for RevelaAI.

The store deliberately remains process-local during the framework migration.
Its public functions do not depend on Flask globals and can be called from
FastAPI routes, CLI tools, and the legacy compatibility adapter.
"""
from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict
from threading import Lock
from typing import Any, Mapping


MAX_HISTORY = max(1, int(os.getenv("MAX_HISTORY", "12")))
MAX_SESSIONS = max(1, int(os.getenv("MAX_SESSIONS", "500")))
SESSION_TTL_SECONDS = max(60, int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60))))

SESSION_MEMORY: OrderedDict[str, dict[str, Any]] = OrderedDict()
SESSION_LOCK = Lock()


def _prune_session_memory() -> None:
    now = time.time()
    expired: list[str] = []
    for session_id, session in list(SESSION_MEMORY.items()):
        try:
            updated_at = float(session.get("updated_at", now))
        except (TypeError, ValueError):
            updated_at = now
        if now - updated_at > SESSION_TTL_SECONDS:
            expired.append(session_id)

    for session_id in expired:
        SESSION_MEMORY.pop(session_id, None)

    while len(SESSION_MEMORY) > MAX_SESSIONS:
        SESSION_MEMORY.popitem(last=False)


def get_session(session_id: str) -> dict[str, Any]:
    key = str(session_id or "").strip()[:128] or uuid.uuid4().hex
    with SESSION_LOCK:
        _prune_session_memory()
        existing = SESSION_MEMORY.get(key)
        if existing is None:
            existing = {
                "topic": None,
                "messages": [],
                "updated_at": time.time(),
            }
            SESSION_MEMORY[key] = existing
            return existing
        existing["updated_at"] = time.time()
        SESSION_MEMORY.move_to_end(key)
        return existing


def save_session(session_id: str, session: dict[str, Any]) -> None:
    key = str(session_id or "").strip()[:128]
    if not key:
        return
    if not isinstance(session, dict):
        raise TypeError("session must be a dictionary")
    messages = session.get("messages", [])
    session["messages"] = list(messages)[-MAX_HISTORY:] if isinstance(messages, list) else []
    session["updated_at"] = time.time()
    with SESSION_LOCK:
        SESSION_MEMORY[key] = session
        SESSION_MEMORY.move_to_end(key)
        _prune_session_memory()


def normalize_client_context(raw_context: Any) -> list[dict[str, str]]:
    if isinstance(raw_context, str):
        normalized: list[dict[str, str]] = []
        for line in raw_context.strip().splitlines():
            line = line.strip()
            if line.startswith("User:"):
                content = line[len("User:"):].strip()
                role = "user"
            elif line.startswith("Assistant:"):
                content = line[len("Assistant:"):].strip()
                role = "assistant"
            else:
                continue
            if content:
                normalized.append({"role": role, "content": content})
        return normalized[-MAX_HISTORY:]

    if not isinstance(raw_context, list):
        return []

    normalized = []
    for item in raw_context:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        content = str(item.get("content") or "").strip()
        if content:
            normalized.append({"role": role, "content": content})
    return normalized[-MAX_HISTORY:]


def build_server_context(session: Mapping[str, Any]) -> list[dict[str, str]]:
    messages = session.get("messages", [])
    if not isinstance(messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        content = str(item.get("content") or "").strip()
        if content:
            normalized.append({"role": role, "content": content})
    return normalized[-MAX_HISTORY:]


def resolve_conversation_context(
    session: dict[str, Any],
    client_context: Any = None,
) -> tuple[list[dict[str, str]], str]:
    normalized_client = normalize_client_context(client_context)
    if normalized_client:
        session["messages"] = normalized_client[-MAX_HISTORY:]
        return normalized_client[-MAX_HISTORY:], "client_context"
    return build_server_context(session), "server_session"


def build_session_id(
    headers: Mapping[str, Any],
    cookies: Mapping[str, Any],
    authenticated_user_id: str | None = None,
) -> str:
    """Build a bounded account-namespaced session ID without request globals."""
    header_id = next(
        (
            str(value).strip()
            for key, value in headers.items()
            if str(key).casefold() == "x-session-id"
        ),
        "",
    )
    cookie_id = str(cookies.get("revelaai_session") or "").strip()
    session_id = (header_id or cookie_id or uuid.uuid4().hex)[:128]
    if authenticated_user_id:
        session_id = f"{authenticated_user_id}:{session_id}"[:128]
    return session_id
