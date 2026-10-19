"""Native FastAPI adapter for the prototype users directory.

This mirrors the original in-memory demo store. It is intentionally not an
authoritative RevelaCode account store and is not used for authentication.
Replace this store with an approved persistence layer before relying on it in
production.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/users", tags=["Prototype Users"])
USERS: dict[str, dict[str, Any]] = {}


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


@router.post("")
async def create_user(request: Request):
    payload = await _read_json_object(request)
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()

    if not name:
        return JSONResponse(
            {"status": "error", "message": "User name is required"},
            status_code=400,
        )

    user_id = str(ObjectId())
    user = {
        "_id": user_id,
        "name": name,
        "email": email,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    USERS[user_id] = user
    return JSONResponse(
        {"status": "success", "data": user},
        status_code=201,
    )


@router.get("/{user_id}")
async def get_user(user_id: str):
    user = USERS.get(user_id)
    if user is None:
        return JSONResponse(
            {"status": "error", "message": "User not found"},
            status_code=404,
        )
    return {"status": "success", "data": user}
