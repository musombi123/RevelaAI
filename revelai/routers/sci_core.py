"""Sci-Core route registration and administrator-only oversight dashboard."""
DEFENSIVE_ONLY = True
from flask import Blueprint, jsonify, request
from routes.meta_engineer_routes import _authenticated_admin
from ..sci_core import research_engine, defensive_shield, disaster_manager, hardware_lab
from ..sci_core.storage import collection
sci_router=Blueprint("sci_core",__name__)

@sci_router.before_request
def require_admin_for_sci_core():
    # CORS preflight requests do not include the Authorization bearer token.
    # Allow OPTIONS negotiation; every real GET/POST still runs the admin gate.
    if request.method == "OPTIONS":
        return None
    actor, error = _authenticated_admin()
    if error:
        return error
    return None
research_engine.register_routes(sci_router)
defensive_shield.register_routes(sci_router)
disaster_manager.register_routes(sci_router)
hardware_lab.register_routes(sci_router)
@sci_router.get("/shield/dashboard")
def dashboard():
    try:
        from datetime import datetime, timezone, timedelta
        since=datetime.now(timezone.utc)-timedelta(hours=24)
        return jsonify({"threats_last_24h":collection("threats").count_documents({"timestamp":{"$gte":since.isoformat()}}),"shields_active":1,"disasters_handled":collection("disasters").count_documents({}),"research_count":collection("research").count_documents({}),"defensive_only":True})
    except Exception: return jsonify({"status":"degraded","error":"Sci-Core dashboard unavailable"}),503
