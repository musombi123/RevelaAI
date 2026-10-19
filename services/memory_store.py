"""Flask-independent persistence and filtering services for RevelaAI Smart Memory."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger("revelaai.memory.store")
MONGO_URI = os.getenv("MONGO_URI", "").strip()

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


def _collection(name: str):
    if _revelai_db is None:
        raise RuntimeError("RevelaAI MongoDB is not configured or unavailable")
    return _revelai_db[name]


conversations = lambda: _collection("conversations")
memories = lambda: _collection("memories")
ideas = lambda: _collection("ideas")
learnings = lambda: _collection("learnings")


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


