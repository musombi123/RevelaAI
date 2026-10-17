"""Secure, smart-filtered per-user memory for RevelaAI.

RevelaCode remains the identity authority. This module stores only in the
separate MongoDB database named `revelai`; it never queries `revelacode.users`.
A signed RevelaCode JWT and a service-to-service existence check are required.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import jwt
import requests
from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, jsonify, request
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

memory_bp = Blueprint("memory_bp", __name__)
logger = logging.getLogger("revelaai.memory")

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"
MONGO_URI = os.getenv("MONGO_URI", "").strip()
REVELACODE_BACKEND_URL = os.getenv(
    "REVELACODE_BACKEND_URL",
    "https://revelacode-backend.onrender.com",
).strip().rstrip("/")
# Dedicated service-to-service key used by the protected user-verification
# endpoint in the existing RevelaCode backend branch.
REVELAAI_SERVICE_KEY = (
    os.getenv("REVELAAI_SERVICE_KEY", "").strip()
    or os.getenv("REVELACODE_VERIFY_KEY", "").strip()
)
VERIFY_TIMEOUT_SECONDS = float(os.getenv("REVELACODE_VERIFY_TIMEOUT_SECONDS", "4"))

_mongo_client = None
_revelai_db = None
if MONGO_URI:
    try:
        _mongo_client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            appname="RevelaAI-SmartMemory-v2",
        )
        _revelai_db = _mongo_client["revelai"]
        # Unique per-user memory and session; ideas are de-duplicated per user.
        _revelai_db["memories"].create_index([("userId", ASCENDING)], unique=True)
        _revelai_db["conversations"].create_index(
            [("userId", ASCENDING), ("sessionId", ASCENDING)], unique=True
        )
        _revelai_db["conversations"].create_index(
            [("userId", ASCENDING), ("updatedAt", DESCENDING)]
        )
        _revelai_db["ideas"].create_index(
            [("userId", ASCENDING), ("normalizedKey", ASCENDING)], unique=True
        )
        _revelai_db["ideas"].create_index(
            [("userId", ASCENDING), ("createdAt", DESCENDING)]
        )
        _revelai_db["learnings"].create_index(
            [("userId", ASCENDING), ("createdAt", DESCENDING)]
        )
    except Exception:
        logger.exception("Memory MongoDB initialization failed")
        _mongo_client = None
        _revelai_db = None

conversations = lambda: _collection("conversations")
memories = lambda: _collection("memories")
ideas = lambda: _collection("ideas")
learnings = lambda: _collection("learnings")


def _collection(name: str):
    if _revelai_db is None:
        raise RuntimeError("RevelaAI MongoDB is not configured or unavailable")
    return _revelai_db[name]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", str(text or "").lower())).strip()


NOISE_ONLY = re.compile(
    r"^(?:hi|hello|hey|how are you|how are u|good morning|good afternoon|good evening|"
    r"ok|okay|k|thanks|thank you|thx|lol|lmao|asante|sawa|poa|mambo|habari|"
    r"cool|nice|great|sure|yes|no|yep|nope|hmm|hm|bye|goodbye|test)[.!?\s]*$",
    re.IGNORECASE,
)
IDEA_CUES = re.compile(
    r"\b(i want to build|i want to create|i plan to build|my idea is|i have an idea|"
    r"let us build|let's build|we should build|i should create|i should build|"
    r"i could create|i could build|a tool that|a tool for|calculator for|"
    r"new feature|new tool|i propose|i suggest building)\b",
    re.IGNORECASE,
)
IDEA_SENTENCE = re.compile(r"[^.!?\n]*(?:" + IDEA_CUES.pattern + r")[^.!?\n]*", re.IGNORECASE)


def isBestThing(text: str, recent_messages: list[str] | None = None) -> bool:
    """Return True for meaningful, non-duplicate content worth retaining.

    Noise is discarded without writing it to MongoDB. This is a filter, not
    a claim that all valuable context can be inferred from wording alone.
    """
    value = str(text or "").strip()
    normalized = _normalize(value)
    if len(value) < 3 or NOISE_ONLY.fullmatch(value):
        return False
    if not re.search(r"[A-Za-z0-9]", value):
        return False

    # Most fragments are not useful memories, but short explicit facts and
    # preferences must not be discarded just because they contain few words.
    short_fact = re.search(
        r"\b(?:my name is|call me|i live in|i am based in|i'm based in|"
        r"i prefer|my goal is|my business is|my farm is|i grow|i raise|"
        r"my preferred language is|my preferred hub is)\b",
        value,
        re.IGNORECASE,
    )
    word_count = len(normalized.split())
    if word_count < 2:
        return False
    if word_count == 2 and not short_fact:
        # Keep concise but meaningful preference/identity fragments and
        # two-word proper names/locations; discard generic two-word chatter.
        explicit_preference = re.search(
            r"\b(?:no|avoid|prefer|use|remember|farm|business|goal)\b",
            value,
            re.IGNORECASE,
        )
        words = [word.strip(".,!?;:()[]{}") for word in value.split()]
        proper_name_or_place = bool(words) and all(
            word and word[0].isupper() for word in words
        )
        if not explicit_preference and not proper_name_or_place:
            return False
    for prior in (recent_messages or [])[-5:]:
        prior_normalized = _normalize(prior)
        if prior_normalized and normalized == prior_normalized:
            return False
    # Explicit long-term facts, preferences, plans, and specific questions are useful.
    return True


# Backward-compatible descriptive alias used by route/tests.
isUsefulMemory = isBestThing


def _authenticate() -> tuple[ObjectId | None, str | None, tuple | None]:
    """Authenticate via RevelaCode JWT; never accept identity from body alone."""
    if not JWT_SECRET:
        return None, None, (jsonify(status="error", code="auth_not_configured"), 503)

    header = request.headers.get("Authorization", "").strip()
    if not header.startswith("Bearer "):
        return None, None, (jsonify(status="error", code="authentication_required"), 401)

    token = header[7:].strip()
    try:
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            # The existing RevelaCode signer uses "user_id" (not "sub").
            options={"require": ["iat", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        return None, None, (jsonify(status="error", code="token_expired"), 401)
    except jwt.InvalidTokenError:
        return None, None, (jsonify(status="error", code="invalid_token"), 401)

    raw_user_id = str(claims.get("sub") or claims.get("user_id") or "").strip()
    try:
        user_oid = ObjectId(raw_user_id)
    except (InvalidId, TypeError, ValueError):
        return None, None, (jsonify(status="error", code="invalid_user_identity"), 401)

    # Identity hints are accepted only when they match the signed JWT.
    # The header never establishes identity on its own.
    requested_id = str(
        request.headers.get("userId")
        or request.headers.get("X-User-ID")
        or (
            request.view_args.get("user_id")
            if request.view_args and request.view_args.get("user_id")
            else (request.get_json(silent=True) or {}).get("userId", "")
        )
        or ""
    ).strip()
    if requested_id and requested_id != str(user_oid):
        return None, None, (jsonify(status="error", code="user_identity_mismatch"), 403)

    return user_oid, str(user_oid), None


def _verify_authoritative_user(user_id: str) -> tuple[bool, str | None]:
    """Ask RevelaCode's protected verify endpoint; fail closed if misconfigured."""
    if not REVELAAI_SERVICE_KEY:
        return False, "user_verification_not_configured"
    try:
        response = requests.get(
            f"{REVELACODE_BACKEND_URL}/api/auth/verify/{user_id}",
            headers={"X-REVELAAI-SERVICE-KEY": REVELAAI_SERVICE_KEY},
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            data = response.json()
            return bool(data.get("exists") and str(data.get("userId")) == user_id), None
        if response.status_code == 404:
            return False, "user_not_found"
        if response.status_code in (401, 403):
            return False, "user_verification_forbidden"
        return False, "user_verification_unavailable"
    except (requests.RequestException, ValueError):
        logger.warning("RevelaCode user verification service unavailable")
        return False, "user_verification_unavailable"


def _require_identity() -> tuple[ObjectId | None, str | None, tuple | None]:
    user_oid, user_id, error = _authenticate()
    if error:
        return None, None, error
    valid, code = _verify_authoritative_user(user_id)
    if not valid:
        status = 404 if code == "user_not_found" else 503 if code in {
            "user_verification_not_configured", "user_verification_unavailable"
        } else 403
        return None, None, (jsonify(status="error", code=code or "user_verification_failed"), status)
    return user_oid, user_id, None


def _recent_messages(user_oid: ObjectId, limit: int = 5) -> list[str]:
    try:
        docs = list(
            conversations().find(
                {"userId": user_oid},
                {"messages": {"$slice": -limit}},
            ).sort("updatedAt", DESCENDING).limit(5)
        )
        values: list[str] = []
        # The query is newest-session-first; reverse sessions to evaluate
        # duplicate detection against the true chronological tail.
        for doc in reversed(docs):
            for message in doc.get("messages", []):
                if isinstance(message, dict):
                    values.append(str(message.get("content") or ""))
        return values[-limit:]
    except Exception:
        return []


def _remember_best_things(user_oid: ObjectId, text: str) -> int:
    """Extract only explicit, high-confidence long-term facts/preferences."""
    value = str(text or "").strip()
    updates: dict[str, str] = {}
    patterns = {
        "name": [
            r"\bmy name is\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})",
            r"\byou can call me\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,2})",
        ],
        "business": [
            r"\bmy business(?: name)? is\s+([^.!?\n]{2,100})",
            r"\bmy company is\s+([^.!?\n]{2,100})",
            r"\bi run\s+([^.!?\n]{2,100})",
        ],
        "farm": [
            r"\bmy farm (?:is|grows|raises)\s+([^.!?\n]{2,120})",
            r"\bi grow\s+([^.!?\n]{2,100})",
            r"\bi raise\s+([^.!?\n]{2,100})",
        ],
        "location": [
            r"\bi (?:live|am based) in\s+([^.!?\n]{2,100})",
            r"\bmy farm is in\s+([^.!?\n]{2,100})",
            r"\bmy business is based in\s+([^.!?\n]{2,100})",
        ],
        "goals": [
            r"\bmy goal is to\s+([^.!?\n]{3,180})",
            r"\bi want to build\s+([^.!?\n]{3,180})",
            r"\bi plan to\s+([^.!?\n]{3,180})",
        ],
        "faith": [
            r"\bmy faith journey(?: is| involves)?\s*([^.!?\n]{3,180})",
            r"\bmy prayer request is\s*([^.!?\n]{3,180})",
            r"\bplease remember (?:me in prayer|my prayer request)\s*([^.!?\n]{0,180})",
        ],
        "preferences": [
            r"\bi prefer\s+([^.!?\n]{3,160})",
            r"\bplease (?:always )?(?:use|speak|reply in|respond in)\s+([^.!?\n]{3,120})",
            r"\bmy preferred language is\s+([^.!?\n]{2,60})",
            r"\bmy preferred hub is\s+([^.!?\n]{2,60})",
        ],
        "personality": [
            r"\bi like (?:answers|responses|explanations) that\s+([^.!?\n]{3,160})",
            r"\bmy communication style is\s+([^.!?\n]{3,100})",
        ],
    }
    for field, expressions in patterns.items():
        for expression in expressions:
            match = re.search(expression, value, re.IGNORECASE)
            if match:
                candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,;.")
                if candidate and len(candidate) <= 200:
                    updates[field] = candidate
                    break

    if updates:
        payload = {
            "userId": user_oid,
            "bestThings": {key: val for key, val in updates.items()},
            "updatedAt": _now(),
        }
        memories().update_one(
            {"userId": user_oid},
            {
                "$set": {f"bestThings.{key}": val for key, val in updates.items()},
                "$setOnInsert": {
                    "userId": user_oid,
                    "createdAt": _now(),
                    "uselessFiltered": [],
                    "learnScore": 0,
                },
                "$currentDate": {"lastLearnedAt": True},
            },
            upsert=True,
        )
    return len(updates)


def _record_messages(
    user_oid: ObjectId,
    session_id: str,
    hub: str,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any]:
    recent = _recent_messages(user_oid)
    candidates = [("user", user_text), ("assistant", assistant_text)]
    useful_messages = []
    for role, content in candidates:
        if isBestThing(content, recent + [item["content"] for item in useful_messages]):
            useful_messages.append({
                "role": role,
                "content": content[:8000],
                "timestamp": _now(),
                "isUseful": True,
            })

    if useful_messages:
        conversations().update_one(
            {"userId": user_oid, "sessionId": session_id},
            {
                "$setOnInsert": {
                    "userId": user_oid,
                    "sessionId": session_id,
                    "createdAt": _now(),
                },
                "$set": {"hub": hub[:40], "updatedAt": _now()},
                "$push": {"messages": {"$each": useful_messages}},
            },
            upsert=True,
        )
        memories().update_one(
            {"userId": user_oid},
            {
                "$setOnInsert": {
                    "userId": user_oid,
                    "bestThings": {},
                    "uselessFiltered": [],
                    "createdAt": _now(),
                },
                "$inc": {"learnScore": 1},
                "$currentDate": {"lastLearnedAt": True},
            },
            upsert=True,
        )

    extracted = _remember_best_things(user_oid, user_text) if isBestThing(user_text, recent) else 0
    created_ideas = _detect_and_store_ideas(user_oid, user_text, assistant_text, session_id, hub) if (
        isBestThing(user_text, recent) or isBestThing(assistant_text, recent)
    ) else []

    if useful_messages:
        try:
            learnings().insert_one({
                "userId": user_oid,
                "sessionId": session_id,
                "hub": hub[:40],
                "usefulMessageCount": len(useful_messages),
                "learnedFactCount": extracted,
                "ideaCreated": bool(created_ideas),
                "createdAt": _now(),
            })
        except PyMongoError:
            logger.warning("Learning telemetry could not be persisted")

    return {
        "storedMessages": len(useful_messages),
        "filteredMessages": len(candidates) - len(useful_messages),
        "learnedFacts": extracted,
        "idea": created_ideas[0] if created_ideas else None,
        "ideas": created_ideas,
    }


def _detect_and_store_ideas(
    user_oid: ObjectId,
    user_text: str,
    assistant_text: str,
    session_id: str,
    hub: str,
) -> list[dict[str, Any]]:
    """Persist distinct useful ideas from the user and assistant without duplicates."""
    created: list[dict[str, Any]] = []
    seen_this_turn: set[str] = set()
    for source, text in (("user", user_text), ("assistant", assistant_text)):
        for match in IDEA_SENTENCE.finditer(str(text or "")):
            idea_text = re.sub(r"\s+", " ", match.group(0)).strip(" -,:;")
            if len(idea_text) < 20 or not isBestThing(idea_text):
                continue
            normalized_key = _normalize(idea_text)[:240]
            if not normalized_key or normalized_key in seen_this_turn:
                continue
            seen_this_turn.add(normalized_key)
            try:
                result = ideas().update_one(
                    {"userId": user_oid, "normalizedKey": normalized_key},
                    {"$setOnInsert": {
                        "userId": user_oid,
                        "ideaText": idea_text[:1200],
                        "normalizedKey": normalized_key,
                        "isNew": True,
                        "isUseful": True,
                        "status": "new",
                        "implementationCode": None,
                        "sourceConversationId": session_id,
                        "source": source,
                        "hub": hub[:40],
                        "createdAt": _now(),
                    }},
                    upsert=True,
                )
                if result.upserted_id:
                    created.append({
                        "id": str(result.upserted_id),
                        "status": "new",
                        "source": source,
                        "ideaText": idea_text[:240],
                    })
            except PyMongoError:
                logger.exception("Idea persistence failed")
    return created

def _json_safe(doc: dict | None) -> dict | None:
    if not doc:
        return doc
    output = dict(doc)
    if "_id" in output:
        output["_id"] = str(output["_id"])
    if isinstance(output.get("userId"), ObjectId):
        output["userId"] = str(output["userId"])
    for key in ("createdAt", "updatedAt", "lastLearnedAt"):
        if isinstance(output.get(key), datetime):
            output[key] = output[key].isoformat()
    for item in output.get("messages", []) if isinstance(output.get("messages"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("timestamp"), datetime):
            item["timestamp"] = item["timestamp"].isoformat()
    return output


@memory_bp.route("/chat", methods=["POST"])
def smart_memory_chat():
    identity, user_id, error = _require_identity()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    user_text = str(payload.get("userMessage") or payload.get("message") or "").strip()
    assistant_text = str(payload.get("aiResponse") or payload.get("reply") or "").strip()
    hub = str(payload.get("hub") or "general").strip().lower()[:40]
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "default").strip()[:128] or "default"

    if not user_text and not assistant_text:
        return jsonify(status="error", code="message_required"), 400
    if len(user_text) > 8000 or len(assistant_text) > 8000:
        return jsonify(status="error", code="message_too_large"), 413

    try:
        result = _record_messages(identity, session_id, hub, user_text, assistant_text)
        logger.info(
            "Memory v2 - Smart Filter - Best things only, useless dumped - "
            "Cluster0 revelacode users + revelai memory/ideas wired separately - per userId"
        )
        return jsonify(
            status="success",
            userId=user_id,
            stored=result["storedMessages"] > 0,
            storedMessages=result["storedMessages"],
            filteredMessages=result["filteredMessages"],
            learnedFacts=result["learnedFacts"],
            idea=result["idea"],
            ideas=result["ideas"],
        ), 200
    except Exception:
        logger.exception("Smart memory write failed")
        # Memory must never take down the conversation itself.
        return jsonify(status="error", code="memory_unavailable"), 503


@memory_bp.route("/<user_id>", methods=["GET"])
def get_memory(user_id: str):
    identity, authenticated_id, error = _require_identity()
    if error:
        return error
    if authenticated_id != user_id:
        return jsonify(status="error", code="user_identity_mismatch"), 403
    try:
        doc = memories().find_one({"userId": identity})
        return jsonify(status="success", userId=authenticated_id, data=_json_safe(doc) or {
            "userId": authenticated_id,
            "bestThings": {},
            "uselessFiltered": [],
            "learnScore": 0,
        }), 200
    except Exception:
        logger.exception("Memory read failed")
        return jsonify(status="error", code="memory_unavailable"), 503


@memory_bp.route("/ideas", methods=["POST"])
def create_idea():
    identity, user_id, error = _require_identity()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    idea_text = str(payload.get("ideaText") or "").strip()
    if not isBestThing(idea_text):
        return jsonify(status="success", created=False, reason="filtered_as_noise"), 200
    normalized_key = _normalize(idea_text)[:240]
    if len(normalized_key) < 12:
        return jsonify(status="success", created=False, reason="idea_too_short"), 200
    try:
        existing = ideas().find_one({"userId": identity, "normalizedKey": normalized_key})
        if existing:
            return jsonify(status="success", created=False, duplicate=True, data=_json_safe(existing)), 200
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
        return jsonify(status="success", created=True, data=_json_safe(doc)), 201
    except Exception:
        logger.exception("Idea creation failed")
        return jsonify(status="error", code="ideas_unavailable"), 503


@memory_bp.route("/ideas/<idea_id>/implementation", methods=["POST"])
def record_idea_implementation(idea_id: str):
    """Record a reviewed implementation artifact; never execute submitted code."""
    identity, user_id, error = _require_identity()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    implementation_code = str(payload.get("implementationCode") or "").strip()
    implementation_ref = str(payload.get("implementationRef") or "").strip()

    if not implementation_code or len(implementation_code) > 20000:
        return jsonify(status="error", code="implementation_code_required_or_too_large"), 400
    if not implementation_ref or len(implementation_ref) > 500:
        return jsonify(status="error", code="implementation_ref_required"), 400

    try:
        idea_oid = ObjectId(idea_id)
    except (InvalidId, TypeError, ValueError):
        return jsonify(status="error", code="invalid_idea_id"), 400

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
            return jsonify(status="error", code="idea_not_found"), 404
        return jsonify(status="success", userId=user_id, statusValue="implemented"), 200
    except Exception:
        logger.exception("Idea implementation record update failed")
        return jsonify(status="error", code="ideas_unavailable"), 503


@memory_bp.route("/ideas/<user_id>", methods=["GET"])
def get_ideas(user_id: str):
    identity, authenticated_id, error = _require_identity()
    if error:
        return error
    if authenticated_id != user_id:
        return jsonify(status="error", code="user_identity_mismatch"), 403
    try:
        docs = list(ideas().find({"userId": identity}).sort("createdAt", DESCENDING).limit(100))
        return jsonify(status="success", userId=authenticated_id, data=[_json_safe(doc) for doc in docs]), 200
    except Exception:
        logger.exception("Idea list failed")
        return jsonify(status="error", code="ideas_unavailable"), 503


@memory_bp.route("/useless/<user_id>", methods=["DELETE"])
def cleanup_useless(user_id: str):
    """Prune legacy noise already persisted by earlier memory implementations."""
    identity, authenticated_id, error = _require_identity()
    if error:
        return error
    if authenticated_id != user_id:
        return jsonify(status="error", code="user_identity_mismatch"), 403
    try:
        removed = 0
        docs = conversations().find({"userId": identity}, {"messages": 1})
        for doc in docs:
            retained = []
            recent: list[str] = []
            for message in doc.get("messages", []):
                content = str(message.get("content") or "") if isinstance(message, dict) else ""
                if isBestThing(content, recent):
                    retained.append(message)
                    recent.append(content)
                else:
                    removed += 1
            if len(retained) != len(doc.get("messages", [])):
                conversations().update_one({"_id": doc["_id"], "userId": identity}, {"$set": {"messages": retained}})
        return jsonify(status="success", removedMessages=removed), 200
    except Exception:
        logger.exception("Useless memory cleanup failed")
        return jsonify(status="error", code="memory_cleanup_failed"), 503


# Compatibility history endpoints: they now read/write the durable filtered store.
@memory_bp.route("/<user_id>/history", methods=["GET"])
def get_history(user_id: str):
    identity, authenticated_id, error = _require_identity()
    if error:
        return error
    if authenticated_id != user_id:
        return jsonify(status="error", code="user_identity_mismatch"), 403
    try:
        docs = list(conversations().find({"userId": identity}).sort("updatedAt", DESCENDING).limit(30))
        return jsonify(status="success", data=[_json_safe(doc) for doc in docs]), 200
    except Exception:
        logger.exception("Conversation history read failed")
        return jsonify(status="error", code="memory_unavailable"), 503
