"""Native FastAPI Smart Memory endpoints backed by the separate `revelai` database."""
from __future__ import annotations

import logging
from typing import Any, Mapping

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pymongo import DESCENDING
from starlette.concurrency import run_in_threadpool

from fastapi_routes.auth import authenticate_identity
from services.revenue_entitlements import check_entitlement
from services.memory_store import (
    _json_safe,
    _now,
    _normalize,
    _record_messages,
    conversations,
    ideas,
    isBestThing,
    memories,
)

router = APIRouter(prefix="/api/memory", tags=["Smart Memory"])
logger = logging.getLogger("revelaai.fastapi.memory")


def _authenticate(headers: Mapping[str, str], payload: dict[str, Any] | None = None, path_user_id: str = ""):
    identity, user_id, auth_error = authenticate_identity(
        headers.get("authorization", ""),
        headers,
        payload or {},
        path_user_id=path_user_id,
    )
    if auth_error:
        return None, None, auth_error

    # Dedicated persistent memory/history/idea endpoints are the paid long-memory
    # capability. Core conversational replies remain usable on the free tier.
    _, entitlement_error = check_entitlement(
        headers.get("authorization", ""),
        hub="smart_ai",
        feature="long_memory",
    )
    if entitlement_error is not None:
        return None, None, entitlement_error
    return identity, user_id, None


def _memory_chat(headers: Mapping[str, str], payload: dict[str, Any]):
    identity, user_id, error = _authenticate(headers, payload)
    if error:
        return error
    user_text = str(payload.get("userMessage") or payload.get("message") or "").strip()
    assistant_text = str(payload.get("aiResponse") or payload.get("reply") or "").strip()
    hub = str(payload.get("hub") or "general").strip().lower()[:40]
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "default").strip()[:128] or "default"

    if not user_text and not assistant_text:
        return JSONResponse({"status": "error", "code": "message_required"}, status_code=400)
    if len(user_text) > 8000 or len(assistant_text) > 8000:
        return JSONResponse({"status": "error", "code": "message_too_large"}, status_code=413)
    try:
        result = _record_messages(identity, session_id, hub, user_text, assistant_text)
        logger.info(
            "Smart memory turn processed | stored=%s filtered=%s facts=%s ideas=%s",
            result["storedMessages"], result["filteredMessages"], result["learnedFacts"],
            len(result["ideas"] or []),
        )
        return {
            "status": "success",
            "userId": user_id,
            "stored": result["storedMessages"] > 0,
            "storedMessages": result["storedMessages"],
            "filteredMessages": result["filteredMessages"],
            "learnedFacts": result["learnedFacts"],
            "idea": result["idea"],
            "ideas": result["ideas"],
        }
    except Exception:
        logger.exception("Smart memory write failed")
        return JSONResponse({"status": "error", "code": "memory_unavailable"}, status_code=503)


def _get_memory(headers: Mapping[str, str], user_id: str):
    identity, authenticated_id, error = _authenticate(headers, path_user_id=user_id)
    if error:
        return error
    if authenticated_id != user_id:
        return JSONResponse({"status": "error", "code": "user_identity_mismatch"}, status_code=403)
    try:
        doc = memories().find_one({"userId": identity})
        return {
            "status": "success",
            "userId": authenticated_id,
            "data": _json_safe(doc) or {
                "userId": authenticated_id,
                "bestThings": {},
                "uselessFiltered": [],
                "learnScore": 0,
            },
        }
    except Exception:
        logger.exception("Memory read failed")
        return JSONResponse({"status": "error", "code": "memory_unavailable"}, status_code=503)


def _create_idea(headers: Mapping[str, str], payload: dict[str, Any]):
    identity, user_id, error = _authenticate(headers, payload)
    if error:
        return error
    idea_text = str(payload.get("ideaText") or "").strip()
    if not isBestThing(idea_text):
        return {"status": "success", "created": False, "reason": "filtered_as_noise"}
    normalized_key = _normalize(idea_text)[:240]
    if len(normalized_key) < 12:
        return {"status": "success", "created": False, "reason": "idea_too_short"}
    try:
        existing = ideas().find_one({"userId": identity, "normalizedKey": normalized_key})
        if existing:
            return {
                "status": "success", "created": False, "duplicate": True,
                "data": _json_safe(existing),
            }
        doc = {
            "userId": identity,
            "ideaText": idea_text[:1200],
            "normalizedKey": normalized_key,
            "isNew": True,
            "isUseful": True,
            "status": "new",
            "implementationCode": None,
            "sourceConversationId": str(payload.get("sourceConversationId") or "")[:128],
            "source": "explicit_api",
            "hub": str(payload.get("hub") or "general")[:40],
            "createdAt": _now(),
        }
        result = ideas().insert_one(doc)
        doc["_id"] = result.inserted_id
        return JSONResponse({"status": "success", "created": True, "data": _json_safe(doc)}, status_code=201)
    except Exception:
        logger.exception("Idea creation failed")
        return JSONResponse({"status": "error", "code": "ideas_unavailable"}, status_code=503)


def _record_implementation(headers: Mapping[str, str], idea_id: str, payload: dict[str, Any]):
    identity, user_id, error = _authenticate(headers, payload)
    if error:
        return error
    implementation_code = str(payload.get("implementationCode") or "").strip()
    implementation_ref = str(payload.get("implementationRef") or "").strip()
    if not implementation_code or len(implementation_code) > 20000:
        return JSONResponse({"status": "error", "code": "implementation_code_required_or_too_large"}, status_code=400)
    if not implementation_ref or len(implementation_ref) > 500:
        return JSONResponse({"status": "error", "code": "implementation_ref_required"}, status_code=400)
    try:
        idea_oid = ObjectId(idea_id)
    except (InvalidId, TypeError, ValueError):
        return JSONResponse({"status": "error", "code": "invalid_idea_id"}, status_code=400)
    try:
        result = ideas().update_one(
            {"_id": idea_oid, "userId": identity},
            {"$set": {
                "status": "implemented",
                "implementationCode": implementation_code,
                "implementationRef": implementation_ref,
                "implementedAt": _now(),
                "updatedAt": _now(),
            }},
        )
        if result.matched_count == 0:
            return JSONResponse({"status": "error", "code": "idea_not_found"}, status_code=404)
        return {"status": "success", "userId": user_id, "statusValue": "implemented"}
    except Exception:
        logger.exception("Idea implementation record update failed")
        return JSONResponse({"status": "error", "code": "ideas_unavailable"}, status_code=503)


def _get_ideas(headers: Mapping[str, str], user_id: str):
    identity, authenticated_id, error = _authenticate(headers, path_user_id=user_id)
    if error:
        return error
    if authenticated_id != user_id:
        return JSONResponse({"status": "error", "code": "user_identity_mismatch"}, status_code=403)
    try:
        docs = list(ideas().find({"userId": identity}).sort("createdAt", DESCENDING).limit(100))
        return {"status": "success", "userId": authenticated_id, "data": [_json_safe(doc) for doc in docs]}
    except Exception:
        logger.exception("Idea list failed")
        return JSONResponse({"status": "error", "code": "ideas_unavailable"}, status_code=503)


def _cleanup_useless(headers: Mapping[str, str], user_id: str):
    identity, authenticated_id, error = _authenticate(headers, path_user_id=user_id)
    if error:
        return error
    if authenticated_id != user_id:
        return JSONResponse({"status": "error", "code": "user_identity_mismatch"}, status_code=403)
    try:
        removed = 0
        docs = conversations().find({"userId": identity}, {"messages": 1})
        for doc in docs:
            retained = []
            recent: list[str] = []
            for message in doc.get("messages", []):
                text = str(message.get("content") or "") if isinstance(message, dict) else ""
                if isBestThing(text, recent):
                    retained.append(message)
                    recent.append(text)
                else:
                    removed += 1
            if len(retained) != len(doc.get("messages", [])):
                conversations().update_one(
                    {"_id": doc["_id"], "userId": identity},
                    {"$set": {"messages": retained}},
                )
        return {"status": "success", "removedMessages": removed}
    except Exception:
        logger.exception("Useless memory cleanup failed")
        return JSONResponse({"status": "error", "code": "memory_cleanup_failed"}, status_code=503)


def _get_history(headers: Mapping[str, str], user_id: str, hub: str):
    identity, authenticated_id, error = _authenticate(headers, path_user_id=user_id)
    if error:
        return error
    if authenticated_id != user_id:
        return JSONResponse({"status": "error", "code": "user_identity_mismatch"}, status_code=403)
    try:
        query: dict[str, Any] = {"userId": identity}
        requested_hub = str(hub or "auto").strip().lower()
        if requested_hub in {"mkulima", "biashara", "elimu", "mahubiri", "general"}:
            query["hub"] = requested_hub
        docs = list(conversations().find(query).sort("updatedAt", DESCENDING).limit(30))
        return {"status": "success", "data": [_json_safe(doc) for doc in docs]}
    except Exception:
        logger.exception("Conversation history read failed")
        return JSONResponse({"status": "error", "code": "memory_unavailable"}, status_code=503)


async def _payload(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


@router.post("/chat")
async def smart_memory_chat(request: Request):
    payload = await _payload(request)
    return await run_in_threadpool(_memory_chat, dict(request.headers), payload)


@router.post("/ideas")
async def create_idea(request: Request):
    payload = await _payload(request)
    return await run_in_threadpool(_create_idea, dict(request.headers), payload)


@router.post("/ideas/{idea_id}/implementation")
async def record_idea_implementation(idea_id: str, request: Request):
    payload = await _payload(request)
    return await run_in_threadpool(_record_implementation, dict(request.headers), idea_id, payload)


@router.get("/ideas/{user_id}")
async def get_ideas(user_id: str, request: Request):
    return await run_in_threadpool(_get_ideas, dict(request.headers), user_id)


@router.delete("/useless/{user_id}")
async def cleanup_useless(user_id: str, request: Request):
    return await run_in_threadpool(_cleanup_useless, dict(request.headers), user_id)


@router.get("/{user_id}/history")
async def get_history(user_id: str, request: Request, hub: str = "auto"):
    return await run_in_threadpool(_get_history, dict(request.headers), user_id, hub)


@router.get("/{user_id}")
async def get_memory(user_id: str, request: Request):
    return await run_in_threadpool(_get_memory, dict(request.headers), user_id)
