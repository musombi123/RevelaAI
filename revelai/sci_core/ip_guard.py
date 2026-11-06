"""Persistent application-edge IP protection for Sci-Core.

This module blocks exact public IP addresses at the ASGI request boundary.
It does not mutate the Render host firewall, Nginx, or any external network.
MongoDB is required for persistence; the service fails closed for block/unblock
administrative actions when the persistent store is unavailable.
"""
from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


class IPGuardStoreUnavailable(RuntimeError):
    """Persistent IP guard storage is not configured or reachable."""


_EVENT_LOCK = threading.Lock()
_FAILED_LOGIN_EVENTS: dict[str, deque[float]] = defaultdict(deque)
_AUTO_BLOCKED_UNTIL: dict[str, float] = {}
_AUTO_BLOCK_THRESHOLD = 50
_AUTO_BLOCK_WINDOW_SECONDS = 300
_AUTO_BLOCK_DURATION_MINUTES = 30
_MAX_TRACKED_IPS = 10000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mongo_db():
    # Reuse the existing RevelaAI MongoDB connection; do not create a second DB.
    try:
        from revelai.sci_core.storage import database

        db = database()
        if db is None:
            raise IPGuardStoreUnavailable("MONGO_URI is not configured; IP blocks cannot be persisted.")
        db.command("ping")
        return db
    except IPGuardStoreUnavailable:
        raise
    except Exception as exc:
        raise IPGuardStoreUnavailable("Persistent IP protection storage is unavailable.") from exc


def ensure_indexes() -> dict[str, Any]:
    db = _mongo_db()
    db["sci_ip_blocks"].create_index([("ip", 1), ("active", 1)])
    db["sci_ip_blocks"].create_index([("expires_at", 1)])
    db["sci_ip_block_events"].create_index([("created_at", -1)])
    db["sci_auth_failures"].create_index([("created_at", -1)])
    return {"persistent": True, "backend": "mongodb"}


def _parse_ip(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 64:
        raise ValueError("Provide one IPv4 or IPv6 address.")
    if "/" in raw:
        raise ValueError("CIDR ranges are not accepted. Block one exact IP address.")
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise ValueError("The IP address is not valid.") from exc
    if not parsed.is_global:
        raise ValueError("Only globally routable public IP addresses can be blocked.")
    return parsed.compressed


def _allowlist():
    values = [
        part.strip()
        for part in os.getenv("SCI_CORE_IP_ALLOWLIST", "").split(",")
        if part.strip()
    ]
    parsed = []
    for value in values:
        try:
            parsed.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            # A malformed allowlist entry must not affect application startup.
            continue
    return parsed


def is_allowlisted(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(address in network for network in _allowlist())


def client_ip_from_headers(headers, peer_host: str | None = None) -> str | None:
    """Resolve a client IP, trusting X-Forwarded-For only when explicitly enabled.

    Render terminates TLS at its edge proxy. Configure the trusted proxy hop
    count in the service environment; never accept arbitrary XFF headers by
    default. The selected hop is counted from the right so proxy-appended
    client addresses take precedence over attacker-supplied leading entries.
    """
    trust_proxy = os.getenv("REVELAAI_TRUST_PROXY_HEADERS", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if trust_proxy:
        forwarded = headers.get("x-forwarded-for", "")
        candidates = [part.strip() for part in forwarded.split(",") if part.strip()]
        if candidates:
            try:
                hops = int(os.getenv("REVELAAI_TRUSTED_PROXY_HOPS", "1"))
            except (TypeError, ValueError):
                hops = 1
            hops = max(1, min(hops, 5))
            index = max(0, len(candidates) - hops - 1)
            try:
                return ipaddress.ip_address(candidates[index]).compressed
            except ValueError:
                return None
        real_ip = headers.get("x-real-ip", "").strip()
        if real_ip:
            try:
                return ipaddress.ip_address(real_ip).compressed
            except ValueError:
                return None
    if peer_host:
        try:
            return ipaddress.ip_address(peer_host).compressed
        except ValueError:
            return None
    return None


def _active_block(ip: str, now: datetime | None = None) -> dict[str, Any] | None:
    db = _mongo_db()
    current = now or utcnow()
    doc = db["sci_ip_blocks"].find_one({"ip": ip, "active": True}, sort=[("created_at", -1)])
    if not doc:
        return None
    expires = doc.get("expires_at")
    if expires is not None:
        if isinstance(expires, str):
            try:
                expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            except ValueError:
                expires = current
        if isinstance(expires, datetime):
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= current:
                db["sci_ip_blocks"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"active": False, "expired_at": current, "status": "expired"}},
                )
                return None
    return doc


def is_ip_blocked(ip: str | None) -> dict[str, Any] | None:
    if not ip:
        return None
    try:
        normalized = ipaddress.ip_address(ip).compressed
        if not ipaddress.ip_address(normalized).is_global or is_allowlisted(normalized):
            return None
        return _active_block(normalized)
    except (ValueError, IPGuardStoreUnavailable):
        # A storage outage must not lock out all traffic; health reports the
        # protection state, and manual block/unblock operations return 503.
        return None


def _audit(db, action: str, ip: str, actor: str, reason: str, source: str, metadata=None):
    db["sci_ip_block_events"].insert_one({
        "event_id": uuid4().hex,
        "action": action,
        "ip": ip,
        "actor": actor,
        "reason": reason[:300],
        "source": source,
        "metadata": metadata or {},
        "created_at": utcnow(),
    })


def block_ip(
    ip: str,
    *,
    actor: str,
    reason: str,
    duration_minutes: int = 60,
    source: str = "manual",
    current_ip: str | None = None,
) -> dict[str, Any]:
    normalized = _parse_ip(ip)
    if is_allowlisted(normalized):
        raise ValueError("This address is protected by the administrator IP allowlist.")
    if current_ip:
        try:
            if ipaddress.ip_address(current_ip) == ipaddress.ip_address(normalized):
                raise ValueError("You cannot block the IP address used by this administrator session.")
        except ValueError as exc:
            if str(exc).startswith("You cannot"):
                raise
    try:
        duration = int(duration_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("Block duration must be an integer number of minutes.") from exc
    if duration < 5 or duration > 10080:
        raise ValueError("Block duration must be between 5 minutes and 7 days.")
    reason = str(reason or "").strip()
    if len(reason) < 8 or len(reason) > 300:
        raise ValueError("Enter a reason between 8 and 300 characters.")
    db = _mongo_db()
    created = utcnow()
    expires = created + timedelta(minutes=duration)
    record = {
        "block_id": uuid4().hex,
        "ip": normalized,
        "active": True,
        "status": "active",
        "reason": reason,
        "source": source if source in {"manual", "auto_bruteforce"} else "manual",
        "created_by": str(actor or "unknown")[:128],
        "created_at": created,
        "expires_at": expires,
        "duration_minutes": duration,
    }
    db["sci_ip_blocks"].update_one(
        {"ip": normalized, "active": True},
        {"$set": record},
        upsert=True,
    )
    _audit(db, "blocked", normalized, str(actor or "unknown"), reason, record["source"])
    return {
        "ip": normalized,
        "status": "blocked",
        "reason": reason,
        "source": record["source"],
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "duration_minutes": duration,
    }


def unblock_ip(ip: str, *, actor: str, reason: str = "Administrator released the block") -> dict[str, Any]:
    normalized = _parse_ip(ip)
    db = _mongo_db()
    now = utcnow()
    result = db["sci_ip_blocks"].update_many(
        {"ip": normalized, "active": True},
        {"$set": {
            "active": False,
            "status": "unblocked",
            "unblocked_at": now,
            "unblocked_by": str(actor or "unknown")[:128],
        }},
    )
    if result.modified_count:
        _audit(db, "unblocked", normalized, str(actor or "unknown"), reason, "manual")
    return {"ip": normalized, "status": "unblocked", "records_released": int(result.modified_count)}


def list_active_blocks(limit: int = 100) -> list[dict[str, Any]]:
    db = _mongo_db()
    now = utcnow()
    rows = db["sci_ip_blocks"].find({"active": True}).sort("created_at", -1).limit(max(1, min(int(limit), 250)))
    result = []
    for row in rows:
        expires = row.get("expires_at")
        if isinstance(expires, datetime):
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                db["sci_ip_blocks"].update_one(
                    {"_id": row["_id"]},
                    {"$set": {"active": False, "status": "expired", "expired_at": now}},
                )
                continue
            expires = expires.isoformat()
        created = row.get("created_at")
        if isinstance(created, datetime):
            created = created.isoformat()
        result.append({
            "ip": row.get("ip"),
            "reason": row.get("reason", ""),
            "source": row.get("source", "manual"),
            "created_by": row.get("created_by", ""),
            "created_at": created,
            "expires_at": expires,
            "duration_minutes": row.get("duration_minutes"),
            "status": "active",
        })
    return result


def protection_status() -> dict[str, Any]:
    try:
        db = _mongo_db()
        active = db["sci_ip_blocks"].count_documents({"active": True})
        return {
            "enforcement": "application_edge",
            "persistent": True,
            "storage": "mongodb",
            "status": "active",
            "active_blocks": int(active),
            "automatic_blocking": True,
            "auto_block_threshold": _AUTO_BLOCK_THRESHOLD,
            "auto_block_window_seconds": _AUTO_BLOCK_WINDOW_SECONDS,
            "auto_block_duration_minutes": _AUTO_BLOCK_DURATION_MINUTES,
            "allowlist_configured": bool(_allowlist()),
        }
    except IPGuardStoreUnavailable as exc:
        return {
            "enforcement": "application_edge",
            "persistent": False,
            "storage": "unavailable",
            "status": "degraded",
            "active_blocks": 0,
            "automatic_blocking": False,
            "error": str(exc),
            "allowlist_configured": bool(_allowlist()),
        }


def record_failed_authentication(ip: str | None, path: str) -> dict[str, Any] | None:
    """Auto-block only repeated 401s on authentication endpoints.

    The threshold is intentionally high to reduce accidental blocks on shared
    NATs. IPs on the operator allowlist are never auto-blocked.
    """
    if not ip or not (path.startswith("/api/auth/") or path.startswith("/auth/")):
        return None
    try:
        normalized = ipaddress.ip_address(ip).compressed
        if not ipaddress.ip_address(normalized).is_global or is_allowlisted(normalized):
            return None
    except ValueError:
        return None

    now = time.time()
    with _EVENT_LOCK:
        events = _FAILED_LOGIN_EVENTS[normalized]
        while events and now - events[0] > _AUTO_BLOCK_WINDOW_SECONDS:
            events.popleft()
        events.append(now)
        count = len(events)
        if count < _AUTO_BLOCK_THRESHOLD or normalized in _AUTO_BLOCKED_UNTIL:
            return None
        _AUTO_BLOCKED_UNTIL[normalized] = now + (_AUTO_BLOCK_DURATION_MINUTES * 60)
        if len(_FAILED_LOGIN_EVENTS) > _MAX_TRACKED_IPS:
            stale = sorted(
                _FAILED_LOGIN_EVENTS,
                key=lambda key: _FAILED_LOGIN_EVENTS[key][-1] if _FAILED_LOGIN_EVENTS[key] else 0,
            )[: len(_FAILED_LOGIN_EVENTS) - _MAX_TRACKED_IPS]
            for key in stale:
                _FAILED_LOGIN_EVENTS.pop(key, None)
                _AUTO_BLOCKED_UNTIL.pop(key, None)

    reason = f"{count} failed authentication attempts within 5 minutes."
    try:
        return block_ip(
            normalized,
            actor="sci-core-auto-defence",
            reason=reason,
            duration_minutes=_AUTO_BLOCK_DURATION_MINUTES,
            source="auto_bruteforce",
        )
    except (IPGuardStoreUnavailable, ValueError):
        with _EVENT_LOCK:
            _AUTO_BLOCKED_UNTIL.pop(normalized, None)
        return None


def record_manual_block_event_count() -> int:
    try:
        return int(_mongo_db()["sci_ip_block_events"].count_documents({}))
    except IPGuardStoreUnavailable:
        return 0
