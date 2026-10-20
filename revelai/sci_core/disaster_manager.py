"""Safe disaster diagnostics and reversible simulations; no process killing or forced restart."""
DEFENSIVE_ONLY = True
import os, json, time
from datetime import datetime, timezone
from pathlib import Path
from .storage import collection
from services.security_state import SCI_THROTTLE as THROTTLE
CACHE_PATH = Path(os.getenv("REVELAAI_LOCAL_CACHE_PATH","/tmp/revelai_cache.json"))
def simulate(kind):
    if kind not in {"db_down","api_overload","memory_leak"}: raise ValueError("unsupported disaster type")
    action, recovered = "diagnostics_only", False
    details = {}
    if kind == "db_down":
        try:
            from .storage import database
            db=database()
            if db is None: raise RuntimeError("Mongo URI not configured")
            db.command("ping"); action="database_ping_succeeded"; recovered=True
        except Exception:
            try:
                CACHE_PATH.parent.mkdir(parents=True,exist_ok=True)
                if not CACHE_PATH.exists(): CACHE_PATH.write_text(json.dumps({"mode":"bounded-fallback","createdAt":datetime.now(timezone.utc).isoformat(),"items":[]}),encoding="utf-8")
                action="local_cache_fallback_prepared"
                details={"cache_path":str(CACHE_PATH),"warning":"This prepares a fallback file only; it does not transparently replace MongoDB persistence."}
            except Exception: action="local_cache_unavailable"
    elif kind == "api_overload":
        THROTTLE.update({"enabled":True,"reason":"manual_disaster_simulation","since":datetime.now(timezone.utc).isoformat()})
        action="in_process_throttle_enabled"
        details={"threshold_rps":200,"note":"This flag only affects requests if the application throttle hook is registered; it does not infer real RPS from logs."}
    elif kind == "memory_leak":
        try:
            import psutil
            mem=psutil.virtual_memory()
            details={"system_memory_percent":mem.percent,"available_bytes":mem.available}
            action="memory_diagnostics_recorded"
            if mem.percent > 80: action="high_memory_alert_only"
        except Exception: action="memory_monitor_unavailable"
        details["note"]="No worker restart is attempted; use the process manager's graceful restart after operator review."
    record={"type":kind,"detectedAt":datetime.now(timezone.utc).isoformat(),"actionTaken":action,"recovered":recovered,"details":details,"defensive_only":True}
    collection("disasters").insert_one(record.copy())
    return record
