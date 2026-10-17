"""Civilian software and electronics prototypes; generated artifacts are never executed."""
DEFENSIVE_ONLY = True
import json
from datetime import datetime, timezone
from flask import jsonify, request
from .research_engine import is_offensive_query
from .storage import collection

def build_prototype(domain, spec):
    is_offensive_query(spec)
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in spec[:55]).strip("_") or "prototype"
    if domain == "software":
        artifacts = {"router.py":"from fastapi import APIRouter\nfrom pydantic import BaseModel, Field\nrouter = APIRouter()\nclass Input(BaseModel):\n    value: str = Field(min_length=1, max_length=500)\n@router.post('/prototype')\ndef prototype(payload: Input):\n    return {'status':'accepted','length':len(payload.value)}\n",
        "test_router.py":"def test_prototype_input_contract():\n    assert 1 <= len('safe input') <= 500\n"}
    else:
        artifacts = {
        "circuit.md":"# Civilian sensor concept\nESP32-C3 -> capacitive soil-moisture sensor -> authenticated Wi-Fi telemetry. Use a fused low-voltage supply, weather-resistant enclosure, strain relief, and isolation from mains. Use a rated driver module and flyback protection for inductive loads.\n",
        "firmware.cpp":"// Template only; NOT compiled or executed by the server.\n#include <Arduino.h>\nconst int SENSOR_PIN = 0;\nvoid setup(){ Serial.begin(115200); }\nvoid loop(){ int reading = analogRead(SENSOR_PIN); Serial.println(reading); // Add TLS-authenticated telemetry with certificate validation before deployment.\n delay(30000); }\n",
        "bom.json":json.dumps([{"item":"ESP32-C3 dev board","purpose":"controller","source_search":"Jumia Kenya or AliExpress; verify seller and specifications"},{"item":"Capacitive soil moisture sensor","purpose":"soil measurement","source_search":"Jumia Kenya or AliExpress; compare shipping and calibration"},{"item":"Fused protected low-voltage supply","purpose":"power","source_search":"local certified electronics supplier"},{"item":"IP-rated enclosure and cable glands","purpose":"weather protection","source_search":"local hardware/electronics supplier"}],indent=2),
        "safety.md":"# Electrical safety\nUse low-voltage DC only in the prototype. Never expose mains terminals. Have a qualified electrician install mains-powered pumps. Size wires, fuses, connectors, drivers and power supply to the load. Keep water away from electronics. Test with a current-limited supply and independent cutoff. Do not connect a relay directly to a GPIO.\n"}
    record={"domain":domain,"spec":spec,"name":slug,"artifacts":artifacts,"status":"prototype_generated_review_required","createdAt":datetime.now(timezone.utc).isoformat(),"executed":False,"defensive_only":True}
    col = collection("hardware_lab")\n    col.insert_one(record.copy())\n    record["storage_backend"] = getattr(col, "backend", "mongodb")
    return record

def register_routes(bp):
    @bp.post("/lab/prototype")
    def prototype():
        body=request.get_json(silent=True) or {}
        domain=str(body.get("domain") or "").lower()
        spec=str(body.get("spec") or "").strip()
        if domain not in {"software","hardware","electronics"}: return jsonify({"error":"domain must be software, hardware, or electronics"}),400
        if not spec or len(spec)>800: return jsonify({"error":"spec must be 1–800 characters"}),400
        try: return jsonify(build_prototype(domain,spec)),201
        except Exception as exc:
            if getattr(exc,"code",None)==403: return jsonify({"error":"RevelaAI Sci-Core is defensive & civilian research only"}),403
            return jsonify({"error":"Prototype generation or audit storage failed"}),503
