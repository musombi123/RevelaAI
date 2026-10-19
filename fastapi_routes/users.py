"""Native FastAPI endpoints for the repository's temporary user store."""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from services.user_store import USERS

router = APIRouter(tags=["Users"])


async def _payload(request: Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, Exception):
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/", status_code=201)
async def create_user(request: Request):
    payload = await _payload(request)
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
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }
    USERS[user_id] = user
    return JSONResponse({"status": "success", "data": user}, status_code=201)


@router.get("/{user_id}")
async def get_user(user_id: str = Path(..., min_length=1, max_length=128)):
    user = USERS.get(user_id)
    if not user:
        return JSONResponse(
            {"status": "error", "message": "User not found"},
            status_code=404,
        )
    return {"status": "success", "data": user}
