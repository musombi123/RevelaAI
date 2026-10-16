"""Authenticated primary chat adapter.

Normal requests use the existing orchestrator/provider pipeline. The deterministic
local brain is a last-resort fallback only; multimodal executable actions should
use the existing /ai application endpoint, which owns their execution.
"""
from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from ai.intent_router import classify_intent
from ai.living_brain import respond_local
from services.ai_service import process_message
from routes.memory_routes import _require_identity

chat_bp = Blueprint("chat_bp", __name__)
logger = logging.getLogger("revelaai.chat")


@chat_bp.route("/", methods=["POST"])
def chat():
    user_oid, user_id, auth_error = _require_identity()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    requested_user = str(payload.get("userId") or "").strip()
    if requested_user and requested_user != user_id:
        return jsonify({"status": "error", "code": "user_identity_mismatch"}), 403

    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    if len(message) > 8000:
        return jsonify({"status": "error", "message": "message must be 8,000 characters or fewer"}), 413

    context = payload.get("context") if isinstance(payload.get("context"), list) else []
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "default")[:128]
    intent = classify_intent(message)

    try:
        result = process_message(
            message=message,
            context=context[-12:],
            intent=intent,
            session_id=session_id,
            user_id=user_id,
        )
        if result.get("action_required"):
            return jsonify({
                "status": "success",
                "data": {
                    "userId": user_id,
                    "intent": result.get("intent", intent),
                    "action_required": True,
                    "action": result.get("action"),
                    "capability": result.get("capability"),
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                },
            }), 200

        reply = str(result.get("response") or "").strip()
        if reply and not result.get("error"):
            return jsonify({
                "status": "success",
                "data": {
                    "userId": user_id,
                    "intent": result.get("intent", intent),
                    "reply": reply,
                    "confidence": result.get("confidence", "medium"),
                    "hub": result.get("domain", "general"),
                    "engine": result.get("model") or result.get("provider") or "revelaai-orchestrator",
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "networkUsed": True,
                    "fallback": False,
                },
            }), 200
        logger.warning("Provider pipeline returned no usable answer; switching to local fallback")
    except Exception:
        logger.exception("Coordinated AI provider pipeline failed; using local fallback")

    # Graceful degradation: local deterministic response only when hosted
    # providers fail or return no usable answer. It is never misreported as a model.
    fallback = respond_local(
        message=message,
        preferred_hub=payload.get("hub", "auto"),
        context=context,
    )
    return jsonify({
        "status": "success",
        "data": {
            "userId": user_id,
            "intent": fallback.get("intent", intent),
            "reply": fallback.get("reply", ""),
            "confidence": "fallback",
            "hub": fallback.get("hub", "general"),
            "engine": "revelaai-local-fallback-v2",
            "provider": None,
            "model": None,
            "networkUsed": False,
            "fallback": True,
        },
    }), 200
