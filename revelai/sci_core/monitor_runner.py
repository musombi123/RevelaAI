"""Scheduled defensive checks with incident deduplication and explicit alert status.

Checks are read-only evidence collection. This runner does not block IPs, mutate
firewall rules, restart services, or claim complete malware detection.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
DEDUP_WINDOW_HOURS = 24
ALERT_TIMEOUT_SECONDS = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fingerprint(finding: dict[str, Any]) -> str:
    # IP is only included in the one-way fingerprint material, never in stored
    # incident detail or webhook payload.
    identity = {
        "type": finding.get("type", "unknown"),
        "file": finding.get("file"),
        "line": finding.get("line"),
        "package": finding.get("package"),
        "vulnerability_id": finding.get("id"),
        "source_hash": hashlib.sha256(str(finding.get("ip", "")).encode("utf-8")).hexdigest()[:12]
        if finding.get("ip") else None,
        "check": finding.get("check"),
    }
    material = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _public_finding(finding: dict[str, Any]) -> dict[str, Any]:
    severity = str(finding.get("severity") or "medium").lower()
    if severity not in SEVERITY_ORDER:
        severity = "medium"
    allowed = ("type", "file", "line", "package", "version_constraint", "id", "count", "fix_suggestion", "check")
    public = {key: finding[key] for key in allowed if key in finding and isinstance(finding[key], (str, int, float, bool))}
    public["severity"] = severity
    public["fingerprint"] = _fingerprint(finding)
    return public


def _collect_checks() -> dict[str, list[dict[str, Any]]]:
    from . import defensive_shield

    checks: dict[str, list[dict[str, Any]]] = {}
    functions = {
        "code": defensive_shield.scan_codebase,
        "auth": defensive_shield.scan_auth_logs,
        "dependencies": defensive_shield.dependency_scan,
    }
    for name, function in functions.items():
        try:
            value = function()
            checks[name] = value if isinstance(value, list) else []
        except Exception:
            # Do not include raw exception text: it can contain paths or secrets.
            checks[name] = [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": name,
                "fix_suggestion": "Inspect the monitor runner logs and repair the failing check.",
            }]
    return checks


def _was_recently_sent(col, fingerprint: str, now: datetime) -> bool:
    cutoff = now - timedelta(hours=DEDUP_WINDOW_HOURS)
    try:
        rows = list(col.find({"fingerprint": fingerprint}).sort("created_at", -1).limit(20))
    except Exception:
        # If deduplication storage is unavailable, fail closed rather than
        # risk unbounded repeated alerts.
        raise RuntimeError("incident deduplication store unavailable")
    for row in rows:
        if row.get("alert_status") != "sent":
            continue
        created = _parse_time(row.get("created_at"))
        if created and cutoff <= created <= now:
            return True
    return False


def _send_alert(alert_url: str, incidents: list[dict[str, Any]]) -> None:
    response = requests.post(
        alert_url,
        json={
            "source": "RevelaAI Brain OS",
            "event_type": "defensive_monitor_incident",
            "generated_at": _now().isoformat(),
            "incidents": incidents,
        },
        timeout=ALERT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def monitor_once(
    alert_url: str | None = None,
    checks: dict[str, list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run checks or use injected fixtures; deliver deduplicated alerts or fail clearly."""
    now = now or _now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    configured_url = str(alert_url if alert_url is not None else os.getenv("REVELAAI_ALERT_WEBHOOK_URL", "")).strip()
    check_results = checks if checks is not None else _collect_checks()
    findings: list[dict[str, Any]] = []
    check_failures: list[str] = []
    for check_name, items in check_results.items():
        if not isinstance(items, list):
            check_failures.append(check_name)
            continue
        for item in items:
            if not isinstance(item, dict):
                check_failures.append(check_name)
                continue
            value = dict(item)
            value.setdefault("check", check_name)
            normalized = _public_finding(value)
            if SEVERITY_ORDER[normalized["severity"]] >= SEVERITY_ORDER["medium"]:
                findings.append({**normalized, "_fingerprint": normalized["fingerprint"]})

    from .storage import collection
    col = collection("monitor_incidents")
    new_incidents: list[dict[str, Any]] = []
    suppressed = 0
    for item in findings:
        fingerprint = item["_fingerprint"]
        if _was_recently_sent(col, fingerprint, now):
            suppressed += 1
            continue
        new_incidents.append({key: value for key, value in item.items() if key != "_fingerprint"})

    if not configured_url:
        for item in new_incidents:
            col.insert_one({
                **item,
                "created_at": now.isoformat(),
                "alert_status": "not_configured",
                "dedup_window_hours": DEDUP_WINDOW_HOURS,
            })
        return {
            "status": "misconfigured",
            "checks_run": sorted(check_results.keys()),
            "findings_count": len(findings),
            "alerts_sent": 0,
            "duplicates_suppressed": suppressed,
            "check_failures": check_failures,
            "alert_adapter": {"configured": False, "delivery_status": "not_configured", "required_env": "REVELAAI_ALERT_WEBHOOK_URL"},
        }

    if new_incidents:
        try:
            _send_alert(configured_url, new_incidents)
            alert_status = "sent"
        except Exception:
            alert_status = "failed"
        for item in new_incidents:
            col.insert_one({
                **item,
                "created_at": now.isoformat(),
                "alert_status": alert_status,
                "dedup_window_hours": DEDUP_WINDOW_HOURS,
            })
    else:
        alert_status = "no_new_incidents"

    status = "ok" if alert_status in {"sent", "no_new_incidents"} and not check_failures else "degraded"
    return {
        "status": status,
        "checks_run": sorted(check_results.keys()),
        "findings_count": len(findings),
        "alerts_sent": len(new_incidents) if alert_status == "sent" else 0,
        "duplicates_suppressed": suppressed,
        "check_failures": check_failures,
        "alert_adapter": {
            "configured": True,
            "delivery_status": alert_status,
            "required_env": "REVELAAI_ALERT_WEBHOOK_URL",
        },
    }


def main() -> int:
    result = monitor_once()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
