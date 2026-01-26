from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId

# If you already use MongoDB, connect here
# Example:
# from config.db import users_col

users_bp = Blueprint("users_bp", __name__)

# TEMP in-memory storage (replace with DB)
USERS = {}


@users_bp.route("/", methods=["POST"])
def create_user():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()

    if not name:
        return jsonify({"status": "error", "message": "User name is required"}), 400

    user_id = str(ObjectId())

    user = {
        "_id": user_id,
        "name": name,
        "email": email,
        "createdAt": datetime.utcnow().isoformat()
    }

    USERS[user_id] = user

    return jsonify({"status": "success", "data": user}), 201


@users_bp.route("/<user_id>", methods=["GET"])
def get_user(user_id):
    user = USERS.get(user_id)
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    return jsonify({"status": "success", "data": user})
