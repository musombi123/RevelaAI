"""Non-destructive route deprecation audit. No source files are deleted."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from meta_engineer.integrator import audit, db, ideas_col

def audit_unused() -> dict:
    """Flag candidates with no observed route hits in the previous 30 days."""
    if db is None or ideas_col is None: return {"status": "unavailable", "reason": "MongoDB is not configured"}
    since = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        usage = list(db["logs"].aggregate([
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": "$route", "hits": {"$sum": 1}}}]))
        hit_counts = {str(row.get("_id")): int(row.get("hits", 0)) for row in usage}
        candidates = []
        for idea in ideas_col.find({"code_path": {"$exists": True}, "status": {"$in": ["implemented", "approved"]}}):
            path = str(idea.get("code_path", ""))
            if path and hit_counts.get(path, 0) == 0:
                ideas_col.update_one({"_id": idea["_id"]}, {"$set": {
                    "status": "candidate_for_deprecation", "deprecationAuditAt": datetime.now(timezone.utc),
                    "deprecationReason": "No route hits observed for 30 days; human review required."}})
                candidates.append(path)
        return {"status": "ok", "window_days": 30, "candidates": candidates, "deleted": []}
    except Exception:
        audit("pruner_audit_failed", "audit_unused", None, {"passed": False, "logs": "audit failed"}, "meta-engineer")
        return {"status": "error", "reason": "audit_failed"}
