"""Native FastAPI manifest and runtime-status endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from revelai.core.agi_manifest import get_manifest, get_status_summary
from revelai.sci_core.storage import collection, database

router = APIRouter(prefix="/api/agi", tags=["AGI Manifest"])


def _persist_manifest() -> dict[str, Any]:
    payload = get_manifest()
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    try:
        db = database()
        if db is None:
            raise RuntimeError("MONGO_URI is not configured")
        db.command("ping")
        db["agi_manifest"].replace_one(
            {"_id": "canonical"},
            {"_id": "canonical", **payload},
            upsert=True,
        )
        return {"persisted": True, "backend": "mongodb", "collection": "agi_manifest"}
    except Exception:
        try:
            col = collection("agi_manifest")
            col.insert_one({"kind": "manifest_snapshot", **payload})
            return {
                "persisted": True,
                "backend": getattr(col, "backend", "local_cache"),
                "collection": "agi_manifest",
            }
        except Exception:
            return {"persisted": False, "backend": "unavailable", "collection": "agi_manifest"}


@router.get("/manifest")
def manifest():
    payload = get_manifest()
    payload["persistence"] = _persist_manifest()
    return JSONResponse(payload, status_code=200)


@router.get("/status")
def status():
    result = get_status_summary()
    result["database"] = {
        "configured": False,
        "reachable": False,
        "collection": "agi_manifest",
        "persisted": False,
    }
    try:
        db = database()
        if db is not None:
            db.command("ping")
            db["agi_manifest"].replace_one(
                {"_id": "canonical"},
                {
                    "_id": "canonical",
                    **get_manifest(),
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                },
                upsert=True,
            )
            result["database"] = {
                "configured": True,
                "reachable": True,
                "collection": "agi_manifest",
                "persisted": True,
            }
    except Exception:
        result["database"] = {
            "configured": bool(os.getenv("MONGO_URI")),
            "reachable": False,
            "collection": "agi_manifest",
            "persisted": False,
        }
    result["status"] = (
        "ok"
        if result.get("all_modules_present") and result["database"]["reachable"]
        else "degraded"
    )
    return JSONResponse(result, status_code=200)
