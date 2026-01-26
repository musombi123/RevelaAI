from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId

memory_bp = Blueprint("memory_bp", __name__)

# TEMP in-memory memory store (replace with Mongo)
MEMORY_STORE = {}
HISTORY_STORE = {}


@memory_bp.route("/<user_id>", methods=["GET"])
def get_memory(user_id):
    items = MEMORY_STORE.get(user_id, [])
    return jsonify({"status": "success", "data": items})


@memory_bp.route("/<user_id>", methods=["POST"])
def add_memory(user_id):
    payload = request.get_json(silent=True) or {}

    key = (payload.get("key") or "").strip()
    value = (payload.get("value") or "").strip()
    mem_type = (payload.get("type") or "general").strip()

    if not key or not value:
        return jsonify({"status": "error", "message": "key and value are required"}), 400

    item = {
        "_id": str(ObjectId()),
        "userId": user_id,
        "key": key,
        "value": value,
        "type": mem_type,
        "createdAt": datetime.utcnow().isoformat()
    }

    MEMORY_STORE.setdefault(user_id, []).insert(0, item)

    return jsonify({"status": "success", "data": item}), 201


@memory_bp.route("/<user_id>/history", methods=["GET"])
def get_history(user_id):
    history = HISTORY_STORE.get(user_id, [])
    return jsonify({"status": "success", "data": history})


@memory_bp.route("/<user_id>/history", methods=["POST"])
def add_history(user_id):
    """
    Optional endpoint: frontend can push conversation logs here.
    Body: { "role": "user|assistant", "content": "..." }
    """
    payload = request.get_json(silent=True) or {}

    role = (payload.get("role") or "").strip()
    content = (payload.get("content") or "").strip()

    if role not in ["user", "assistant"]:
        return jsonify({"status": "error", "message": "role must be user or assistant"}), 400

    if not content:
        return jsonify({"status": "error", "message": "content is required"}), 400

    msg = {
        "_id": str(ObjectId()),
        "userId": user_id,
        "role": role,
        "content": content,
        "createdAt": datetime.utcnow().isoformat()
    }

    HISTORY_STORE.setdefault(user_id, []).insert(0, msg)

    return jsonify({"status": "success", "data": msg}), 201
