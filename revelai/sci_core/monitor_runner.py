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
    allowed = ("type", "file", "line", "package", "version_constraint", "id", "count", "fix_suggestion", "check", "target_id", "status_code")
    public = {key: finding[key] for key in allowed if key in finding and isinstance(finding[key], (str, int, float, bool))}
    public["severity"] = severity
    public["fingerprint"] = _fingerprint(finding)
    return public



_TARGET_ID_PATTERN = __import__("re").compile(r"^[a-z][a-z0-9-]{1,39}$")


def collect_runtime_endpoint_checks(
    targets_json: str | None = None,
    allowed_hosts: str | None = None,
) -> list[dict[str, Any]]:
    """Probe explicitly allowlisted HTTPS health endpoints without following redirects.

    Target URLs are configuration, not model input. Request bodies and complete
    URLs are never stored in findings; only the configured target ID is emitted.
    """
    from urllib.parse import urlsplit
    import ipaddress
    import re

    raw_targets = targets_json if targets_json is not None else os.getenv("REVELAAI_MONITOR_TARGETS_JSON", "")
    raw_hosts = allowed_hosts if allowed_hosts is not None else os.getenv("REVELAAI_MONITOR_ALLOWED_HOSTS", "")
    hosts = {host.strip().lower().rstrip(".") for host in str(raw_hosts).split(",") if host.strip()}
    if not str(raw_targets).strip() or not hosts:
        return [{
            "type": "monitor_check_failed",
            "severity": "high",
            "check": "runtime_endpoints",
            "fix_suggestion": (
                "Configure REVELAAI_MONITOR_TARGETS_JSON and REVELAAI_MONITOR_ALLOWED_HOSTS "
                "with owned, public HTTPS health endpoints."
            ),
        }]

    try:
        targets = json.loads(raw_targets)
    except (TypeError, ValueError):
        targets = None
    if not isinstance(targets, list) or not 1 <= len(targets) <= 25:
        return [{
            "type": "monitor_check_failed",
            "severity": "high",
            "check": "runtime_endpoints",
            "fix_suggestion": "Targets config must be a JSON array with 1–25 target objects.",
        }]

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) - {"id", "url", "expected_statuses"}:
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": "Each target may only declare id, url and expected_statuses.",
            }]
        target_id = target.get("id")
        target_url = target.get("url")
        statuses = target.get("expected_statuses", [200])
        if not isinstance(target_id, str) or not _TARGET_ID_PATTERN.fullmatch(target_id):
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": "Every target requires a short lowercase id.",
            }]
        if target_id in seen_ids:
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": "Target IDs must be unique.",
            }]
        seen_ids.add(target_id)
        if not isinstance(target_url, str):
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": "Each target requires a URL string.",
            }]
        try:
            parsed = urlsplit(target_url)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
            host_is_ip = False
            try:
                ipaddress.ip_address(host)
                host_is_ip = True
            except ValueError:
                pass
        except ValueError:
            parsed, host, port, host_is_ip = None, "", None, True
        if (
            parsed is None
            or parsed.scheme.lower() != "https"
            or not host
            or host not in hosts
            or host_is_ip
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": (
                    "Target must use HTTPS on port 443, an exact configured hostname, "
                    "and no credentials, query string or fragment."
                ),
            }]
        if (
            not isinstance(statuses, list)
            or not statuses
            or any(type(status) is not int or not 200 <= status <= 299 for status in statuses)
        ):
            return [{
                "type": "monitor_check_failed",
                "severity": "high",
                "check": "runtime_endpoints",
                "fix_suggestion": "expected_statuses must be a non-empty list of HTTP 2xx integers.",
            }]
        normalized.append({"id": target_id, "url": target_url, "expected_statuses": statuses})

    findings: list[dict[str, Any]] = []
    for target in normalized:
        try:
            response = requests.get(
                target["url"],
                timeout=5,
                allow_redirects=False,
                headers={"User-Agent": "RevelaAI-Defensive-Monitor/1.0", "Accept": "application/json,text/plain,*/*"},
            )
            if response.status_code in target["expected_statuses"]:
                findings.append({
                    "type": "runtime_endpoint_healthy",
                    "severity": "info",
                    "check": "runtime_endpoints",
                    "target_id": target["id"],
                    "status_code": response.status_code,
                })
            else:
                severity = "critical" if response.status_code >= 500 else "high"
                findings.append({
                    "type": "runtime_endpoint_unhealthy",
                    "severity": severity,
                    "check": "runtime_endpoints",
                    "target_id": target["id"],
                    "status_code": response.status_code,
                    "fix_suggestion": "Inspect the service health endpoint and application logs; the monitor did not follow redirects.",
                })
        except requests.RequestException:
            findings.append({
                "type": "runtime_endpoint_unreachable",
                "severity": "high",
                "check": "runtime_endpoints",
                "target_id": target["id"],
                "fix_suggestion": "The configured HTTPS health endpoint did not respond within the bounded timeout.",
            })
    return findings


def _collect_checks() -> dict[str, list[dict[str, Any]]]:
    from . import defensive_shield

    checks: dict[str, list[dict[str, Any]]] = {}
    functions = {
        "code": defensive_shield.scan_codebase,
        "auth": defensive_shield.scan_auth_logs,
        "dependencies": defensive_shield.dependency_scan,
        "runtime_endpoints": collect_runtime_endpoint_checks,
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
            if value.get("type") == "monitor_check_failed":
                check_failures.append(check_name)
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
    runtime_checks = check_results.get("runtime_endpoints", [])
    runtime_config_errors = [item for item in runtime_checks if item.get("type") == "monitor_check_failed"]
    runtime_health_checks = [item for item in runtime_checks if str(item.get("type", "")).startswith("runtime_endpoint_")]
    runtime_summary = {
        "configured": not runtime_config_errors,
        "target_count": len(runtime_health_checks),
        "healthy_count": sum(1 for item in runtime_health_checks if item.get("type") == "runtime_endpoint_healthy"),
        "unhealthy_count": sum(1 for item in runtime_health_checks if item.get("type") in {"runtime_endpoint_unhealthy", "runtime_endpoint_unreachable"}),
        "redirects_followed": False,
        "response_bodies_stored": False,
    }
    return {
        "status": status,
        "checks_run": sorted(check_results.keys()),
        "runtime_endpoints": runtime_summary,
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
