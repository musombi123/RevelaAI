"""HTTP routes for the free five-hub persona engine."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.hub_personas import HUBS, respond

hub_bp = Blueprint("hub_bp", __name__, url_prefix="/api/revelaai/hubs")
MAX_MESSAGE_CHARS = 8000
MAX_VISION_CHARS = 8000


@hub_bp.get("/")
def hub_catalog():
    return jsonify({
        "ok": True,
        "engine": "regex-cache-local-json",
        "paidModel": False,
        "hubs": [
            {"id": key, "label": value["label"]}
            for key, value in HUBS.items()
        ],
    })


@hub_bp.post("/respond")
def hub_respond():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "A JSON request body is required."}), 400

    message = str(payload.get("message") or "").strip()
    vision_description = str(payload.get("visionDescription") or payload.get("vision_description") or "").strip()
    vision = payload.get("vision")
    hub = str(payload.get("hub") or "general").strip().lower()
    user_id = str(payload.get("userId") or payload.get("user_id") or payload.get("sessionId") or "anonymous").strip()

    if not message and not vision_description and not vision:
        return jsonify({"ok": False, "error": "Provide a message or a camera vision description."}), 400
    if len(message) > MAX_MESSAGE_CHARS or len(vision_description) > MAX_VISION_CHARS:
        return jsonify({"ok": False, "error": "Message or vision description exceeds the size limit."}), 413
    if len(user_id) > 256:
        return jsonify({"ok": False, "error": "userId must be 256 characters or fewer."}), 400
    if vision is not None and not isinstance(vision, dict):
        return jsonify({"ok": False, "error": "vision must be an object when supplied."}), 400

    try:
        result = respond(
            message=message or "What do you see?",
            hub=hub,
            user_id=user_id,
            vision=vision,
            vision_description=vision_description,
        )
        return jsonify(result)
    except Exception:
        # Keep internal filesystem and request details out of the public response.
        return jsonify({"ok": False, "error": "The local hub engine could not complete this request."}), 500
