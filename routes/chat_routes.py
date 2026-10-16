"""Primary chat endpoint backed by RevelaAI's local-only global brain."""
from flask import Blueprint, jsonify, request

from ai.living_brain import respond_local

chat_bp = Blueprint("chat_bp", __name__)


@chat_bp.route("/", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("userId")
    message = str(payload.get("message") or "").strip()

    if not user_id:
        return jsonify({"status": "error", "message": "userId is required"}), 400
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    if len(message) > 8000:
        return jsonify({"status": "error", "message": "message must be 8,000 characters or fewer"}), 413

    # Main chat deliberately does not call Gemini, Hugging Face, Groq or other
    # hosted model providers. Browser-local memory remains the client's store.
    brain = respond_local(
        message=message,
        preferred_hub=payload.get("hub", "auto"),
        context=payload.get("context") if isinstance(payload.get("context"), list) else [],
    )

    return jsonify({
        "status": "success",
        "data": {
            "userId": user_id,
            "intent": brain.get("intent", "general_guidance"),
            "reply": brain.get("reply", ""),
            "confidence": brain.get("confidence", "heuristic"),
            "hub": brain.get("hub", "general"),
            "hubLabel": brain.get("hubLabel", "General"),
            "routeReason": brain.get("routeReason", ""),
            "emotion": brain.get("emotionEstimate", "neutral"),
            "engine": brain.get("engine", "revelaai-local-global-brain-v2"),
            "networkUsed": False,
        },
    }), 200
