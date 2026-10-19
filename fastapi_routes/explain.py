"""Native FastAPI explainability endpoint, preserving the legacy response contract."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Explainability"])


@router.post("/")
async def explain(request: Request):
    try:
        payload: Any = await request.json()
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return JSONResponse(
            {"status": "error", "message": "answer is required"},
            status_code=400,
        )
    return {
        "status": "success",
        "data": {
            "answer": answer,
            "explanation": "Explainability module active ✅ (upgrade logic later).",
            "confidence": "medium",
        },
    }
