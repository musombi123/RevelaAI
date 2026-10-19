"""FastAPI implementation of the five-hub persona routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from services.hub_personas import HUBS, respond

router = APIRouter(prefix="/api/revelaai/hubs", tags=["Hubs"])

MAX_MESSAGE_CHARS = 8000
MAX_VISION_CHARS = 8000
MAX_BODY_BYTES = 16 * 1024 * 1024


@router.get("/")
async def hub_catalog() -> dict[str, Any]:
    return {
        "ok": True,
        "engine": "regex-cache-local-json",
        "paidModel": False,
        "hubs": [
            {"id": key, "label": value["label"]}
            for key, value in HUBS.items()
        ],
    }


@router.post("/respond")
async def hub_respond(request: Request):
    """Match the legacy hub route's status codes and response envelope."""
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        return JSONResponse(
            {"ok": False, "error": "Request body exceeds the size limit."},
            status_code=413,
        )

    try:
        payload = json.loads(raw_body) if raw_body else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None

    if not isinstance(payload, dict):
        return JSONResponse(
            {"ok": False, "error": "A JSON request body is required."},
            status_code=400,
        )

    message = str(payload.get("message") or "").strip()
    vision_description = str(
        payload.get("visionDescription")
        or payload.get("vision_description")
        or ""
    ).strip()
    vision = payload.get("vision")
    hub = str(payload.get("hub") or "general").strip().lower()
    session_id = str(
        payload.get("sessionId") or payload.get("session_id") or ""
    ).strip()

    if not session_id:
        return JSONResponse(
            {"ok": False, "error": "sessionId is required."},
            status_code=400,
        )
    if not message and not vision_description and not vision:
        return JSONResponse(
            {
                "ok": False,
                "error": "Provide a message or a camera vision description.",
            },
            status_code=400,
        )
    if len(message) > MAX_MESSAGE_CHARS or len(vision_description) > MAX_VISION_CHARS:
        return JSONResponse(
            {
                "ok": False,
                "error": "Message or vision description exceeds the size limit.",
            },
            status_code=413,
        )
    if len(session_id) > 256:
        return JSONResponse(
            {"ok": False, "error": "userId must be 256 characters or fewer."},
            status_code=400,
        )
    if vision is not None and not isinstance(vision, dict):
        return JSONResponse(
            {"ok": False, "error": "vision must be an object when supplied."},
            status_code=400,
        )

    try:
        result = await run_in_threadpool(
            respond,
            message=message or "What do you see?",
            hub=hub,
            user_id=session_id,
            vision=vision,
            vision_description=vision_description,
        )
        return result
    except Exception:
        # Never disclose internal filesystem, persistence, or request details.
        return JSONResponse(
            {
                "ok": False,
                "error": "The local hub engine could not complete this request.",
            },
            status_code=500,
        )
