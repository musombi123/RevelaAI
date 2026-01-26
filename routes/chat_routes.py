from flask import Blueprint, request, jsonify
from services.ai_service import process_message
from ai.intent_router import classify_intent

chat_bp = Blueprint("chat_bp", __name__)


@chat_bp.route("/", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}

    user_id = payload.get("userId")
    message = (payload.get("message") or "").strip()

    if not user_id:
        return jsonify({"status": "error", "message": "userId is required"}), 400

    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400

    intent = classify_intent(message)

    ai_result = process_message(
        message=message,
        context=[],
        intent=intent,
        session_id=str(user_id)
    )

    reply = ai_result.get("response", "")
    confidence = ai_result.get("confidence", "medium")

    return jsonify({
        "status": "success",
        "data": {
            "userId": user_id,
            "intent": intent,
            "reply": reply,
            "confidence": confidence
        }
    })
