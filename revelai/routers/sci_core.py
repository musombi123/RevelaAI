"""Sci-Core route registration and administrator-only oversight dashboard."""
DEFENSIVE_ONLY = True
from flask import Blueprint, jsonify
from . import research_engine, defensive_shield, disaster_manager, hardware_lab
from ..sci_core.storage import collection
sci_router=Blueprint("sci_core",__name__)
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
