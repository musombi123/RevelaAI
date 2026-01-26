from flask import Blueprint, request, jsonify

explain_bp = Blueprint("explain_bp", __name__)


@explain_bp.route("/", methods=["POST"])
def explain():
    payload = request.get_json(silent=True) or {}

    answer = (payload.get("answer") or "").strip()
    if not answer:
        return jsonify({"status": "error", "message": "answer is required"}), 400

    # Placeholder explainability
    return jsonify({
        "status": "success",
        "data": {
            "answer": answer,
            "explanation": "Explainability module active ✅ (upgrade logic later).",
            "confidence": "medium"
        }
    })
