"""Local-only RevelaAI v2 endpoints: hub chat, visual fallback and health."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from flask import Blueprint, current_app, jsonify, request

from ai.living_brain import describe_vision, respond_local

living_brain_bp = Blueprint("living_brain_bp", __name__)
_DIAGNOSTIC_LOCK = Lock()
_DIAGNOSTIC_PATH = Path(os.getenv("REVELAAI_V2_DIAGNOSTICS", "instance/revelaai_v2_diagnostics.json"))


def _record_diagnostic(operation: str, status: str, error: Exception | None = None) -> None:
    """Best-effort bounded health log. Never record prompts, image data or identity fields."""
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
            _DIAGNOSTIC_PATH.write_text(json.dumps(existing[-100:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        # A read-only/ephemeral filesystem must never make chat unavailable.
        current_app.logger.debug("RevelaAI diagnostic persistence unavailable: %s", type(exc).__name__)


@living_brain_bp.post("/brain/chat")
def living_brain_chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    preferred_hub = str(payload.get("hub") or "auto").strip()
    context = payload.get("context") if isinstance(payload.get("context"), list) else []

    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    if len(message) > 8000:
        return jsonify({"status": "error", "message": "message must be 8,000 characters or fewer"}), 413

    try:
        result = respond_local(message, preferred_hub=preferred_hub, context=context[-8:])
        _record_diagnostic("brain-chat", "ok")
        return jsonify({"status": "success", "data": result}), 200
    except Exception as exc:
        current_app.logger.exception("RevelaAI local brain failed")
        _record_diagnostic("brain-chat", "fallback", exc)
        # Resilience contract: return a useful generic answer rather than a 500.
        return jsonify({
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
        }), 200


@living_brain_bp.post("/vision/describe")
def living_brain_vision():
    payload = request.get_json(silent=True) or {}
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    prompt = str(payload.get("prompt") or "")
    try:
        result = describe_vision(analysis, prompt)
        _record_diagnostic("vision-describe", "ok" if not result["fallback"] else "math-fallback")
        return jsonify({"status": "success", "data": result}), 200
    except Exception as exc:
        current_app.logger.warning("RevelaAI vision description degraded: %s", type(exc).__name__)
        _record_diagnostic("vision-describe", "fallback", exc)
        return jsonify({
            "status": "success",
            "data": {
                "reply": "Vision analysis was unavailable, but chat is still working. Re-upload the image or describe what you want to inspect.",
                "fallback": True,
                "engine": "revelaai-safe-vision-fallback-v2",
                "networkUsed": False,
            },
        }), 200


@living_brain_bp.get("/health")
def living_brain_health():
    return jsonify({
        "status": "ok",
        "version": "2.0",
        "engine": "revelaai-local-global-brain-v2",
        "hubs": ["mkulima", "biashara", "elimu", "mahubiri", "general"],
        "selfHealing": "fallback-and-diagnostics",
        "selfLearning": "client-side-consented-local-memory",
        "externalModels": False,
        "networkUsedForInference": False,
    }), 200
