"""Native FastAPI routes for local Living Brain chat, vision fallback, and health."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ai.living_brain import describe_vision, respond_local

router = APIRouter(prefix="/api/revelaai/v2", tags=["Living Brain"])
logger = logging.getLogger("revelaai.living_brain")
_DIAGNOSTIC_LOCK = Lock()
_DIAGNOSTIC_PATH = Path(
    os.getenv("REVELAAI_V2_DIAGNOSTICS", "instance/revelaai_v2_diagnostics.json")
)


def _record_diagnostic(operation: str, status: str, error: Exception | None = None) -> None:
    """Record a bounded diagnostic event without prompts, identity, or image data."""
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "operation": operation[:60],
        "status": status[:30],
        "errorType": type(error).__name__ if error else None,
    }
    try:
        with _DIAGNOSTIC_LOCK:
            _DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                existing = json.loads(_DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except (OSError, json.JSONDecodeError):
                existing = []
            existing.append(event)
            _DIAGNOSTIC_PATH.write_text(
                json.dumps(existing[-100:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception as exc:
        logger.debug("Living Brain diagnostic persistence unavailable: %s", type(exc).__name__)


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


@router.post("/brain/chat")
async def living_brain_chat(request: Request):
    payload = await _json_object(request)
    message = str(payload.get("message") or "").strip()
    preferred_hub = str(payload.get("hub") or "auto").strip()
    context = payload.get("context") if isinstance(payload.get("context"), list) else []

    if not message:
        return JSONResponse({"status": "error", "message": "message is required"}, status_code=400)
    if len(message) > 8000:
        return JSONResponse(
            {"status": "error", "message": "message must be 8,000 characters or fewer"},
            status_code=413,
        )

    try:
        result = respond_local(message, preferred_hub=preferred_hub, context=context[-8:])
        _record_diagnostic("brain-chat", "ok")
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.exception("RevelaAI local brain failed")
        _record_diagnostic("brain-chat", "fallback", exc)
        return {
            "status": "success",
            "data": {
                "reply": "My specialist routing had a problem, but the conversation is still available. Please restate the goal and key facts; we can work from a simple goal → constraints → evidence → next-step structure.",
                "hub": "general",
                "hubLabel": "General",
                "confidence": "fallback",
                "engine": "revelaai-safe-fallback-v2",
                "networkUsed": False,
                "degraded": True,
            },
        }


@router.post("/vision/describe")
async def living_brain_vision(request: Request):
    payload = await _json_object(request)
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    prompt = str(payload.get("prompt") or "")
    try:
        result = describe_vision(analysis, prompt)
        _record_diagnostic(
            "vision-describe",
            "ok" if not result.get("fallback") else "math-fallback",
        )
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("RevelaAI vision description degraded: %s", type(exc).__name__)
        _record_diagnostic("vision-describe", "fallback", exc)
        return {
            "status": "success",
            "data": {
                "reply": "Vision analysis was unavailable, but chat is still working. Re-upload the image or describe what you want to inspect.",
                "fallback": True,
                "engine": "revelaai-safe-vision-fallback-v2",
                "networkUsed": False,
            },
        }


@router.get("/health")
async def living_brain_health():
    return {
        "status": "ok",
        "version": "2.0",
        "engine": "revelaai-local-global-brain-v2",
        "hubs": ["mkulima", "biashara", "elimu", "mahubiri", "general"],
        "selfHealing": "fallback-and-diagnostics",
        "selfLearning": "client-side-consented-local-memory",
        "externalModels": False,
        "networkUsedForInference": False,
    }
