from flask import Blueprint, request, jsonify

research_bp = Blueprint("research_bp", __name__)


@research_bp.route("/", methods=["POST"])
def research():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()

    if not query:
        return jsonify({"status": "error", "message": "query is required"}), 400

    # Placeholder: later connect to real sources
    return jsonify({
        "status": "success",
        "data": {
            "query": query,
            "sources": [],
            "summary": f'Research module ready. Query received: "{query}"'
        }
    })
