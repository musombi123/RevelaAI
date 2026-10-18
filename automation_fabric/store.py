"""SQLite-backed consent, one-shot plans, run summaries, and hash-chained audit events."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


def default_db_path() -> str:
    configured = os.getenv("REVELAAI_AUTOMATION_DB", "").strip()
    if configured:
        return configured
    return "/tmp/revelaai-automation-fabric.sqlite3"


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = Path(db_path or default_db_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(str(path), timeout=8.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 8000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS consent_grants (
            principal TEXT NOT NULL,
            scope TEXT NOT NULL,
            reason TEXT NOT NULL,
            granted_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            PRIMARY KEY (principal, scope)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS plans_principal_created
           ON plans(principal, created_at DESC)"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            principal TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at REAL NOT NULL,
            details_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS audit_principal_sequence
           ON audit_events(principal, sequence DESC)"""
    )
    # Keep proposals and summaries bounded. Expired plans cannot execute,
    # and old records are pruned after seven days.
    connection.execute("DELETE FROM plans WHERE created_at < ?", (time.time() - 7 * 86400,))
    return connection


def grant_scopes(
    principal: str,
    scopes: list[str],
    *,
    reason: str,
    ttl_seconds: int,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    now = time.time()
    expires = now + ttl_seconds
    connection = _connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for scope in scopes:
            connection.execute(
                """INSERT INTO consent_grants(principal, scope, reason, granted_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(principal, scope) DO UPDATE SET
                     reason=excluded.reason, granted_at=excluded.granted_at,
                     expires_at=excluded.expires_at""",
                (principal, scope, reason[:240], now, expires),
            )
        connection.commit()
    finally:
        connection.close()
    for scope in scopes:
        audit_event(principal, "consent_granted", {"scope": scope, "ttl_seconds": ttl_seconds}, db_path=db_path)
    return list_scopes(principal, db_path=db_path)


def list_scopes(principal: str, *, db_path: str | None = None) -> list[dict[str, Any]]:
    now = time.time()
    connection = _connect(db_path)
    try:
        rows = connection.execute(
            """SELECT scope, reason, granted_at, expires_at
               FROM consent_grants WHERE principal=? AND expires_at>? ORDER BY scope""",
            (principal, now),
        ).fetchall()
        return [
            {"scope": row["scope"], "reason": row["reason"],
             "granted_at": row["granted_at"], "expires_at": row["expires_at"]}
            for row in rows
        ]
    finally:
        connection.close()



def revoke_scopes(
    principal: str,
    scopes: list[str],
    *,
    db_path: str | None = None,
) -> list[str]:
    connection = _connect(db_path)
    revoked: list[str] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for scope in scopes:
            cursor = connection.execute(
                "DELETE FROM consent_grants WHERE principal=? AND scope=?",
                (principal, scope),
            )
            if cursor.rowcount:
                revoked.append(scope)
        connection.commit()
    finally:
        connection.close()
    for scope in revoked:
        audit_event(principal, "consent_revoked", {"scope": scope}, db_path=db_path)
    return revoked



def has_scope(principal: str, scope: str, *, db_path: str | None = None) -> bool:
    connection = _connect(db_path)
    try:
        row = connection.execute(
            "SELECT 1 FROM consent_grants WHERE principal=? AND scope=? AND expires_at>?",
            (principal, scope, time.time()),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def save_plan(
    principal: str,
    plan_id: str,
    plan_hash: str,
    payload: dict[str, Any],
    *,
    created_at: float,
    expires_at: float,
    db_path: str | None = None,
) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            """INSERT INTO plans(plan_id, principal, plan_hash, status, payload_json,
                                 result_json, created_at, expires_at, updated_at)
               VALUES (?, ?, ?, 'planned', ?, NULL, ?, ?, ?)""",
            (plan_id, principal, plan_hash, json.dumps(payload, sort_keys=True), created_at, expires_at, created_at),
        )
    finally:
        connection.close()


def get_plan(principal: str, plan_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    connection = _connect(db_path)
    try:
        row = connection.execute(
            """SELECT plan_id, plan_hash, status, payload_json, result_json,
                      created_at, expires_at, updated_at
               FROM plans WHERE plan_id=? AND principal=?""",
            (plan_id, principal),
        ).fetchone()
        if row is None:
            return None
        return {
            "plan_id": row["plan_id"], "plan_hash": row["plan_hash"], "status": row["status"],
            "plan": json.loads(row["payload_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        connection.close()


def claim_plan(
    principal: str,
    plan_id: str,
    plan_hash: str,
    *,
    db_path: str | None = None,
) -> bool:
    connection = _connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """UPDATE plans SET status='running', updated_at=?
               WHERE plan_id=? AND principal=? AND plan_hash=?
                 AND status='planned' AND expires_at>?""",
            (time.time(), plan_id, principal, plan_hash, time.time()),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def finish_plan(
    principal: str,
    plan_id: str,
    status: str,
    result_summary: dict[str, Any],
    *,
    db_path: str | None = None,
) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            """UPDATE plans SET status=?, result_json=?, updated_at=?
               WHERE plan_id=? AND principal=? AND status='running'""",
            (status, json.dumps(result_summary, sort_keys=True)[:50000], time.time(), plan_id, principal),
        )
    finally:
        connection.close()


def audit_event(
    principal: str,
    event_type: str,
    details: dict[str, Any],
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    occurred_at = time.time()
    details_json = json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)
    connection = _connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "GENESIS"
        material = json.dumps(
            {"principal": principal, "event_type": event_type, "occurred_at": occurred_at,
             "details": json.loads(details_json), "previous_hash": previous_hash},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        event_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        cursor = connection.execute(
            """INSERT INTO audit_events(principal, event_type, occurred_at, details_json,
                                        previous_hash, event_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (principal, event_type, occurred_at, details_json, previous_hash, event_hash),
        )
        connection.commit()
        return {"sequence": cursor.lastrowid, "event_hash": event_hash, "previous_hash": previous_hash}
    finally:
        connection.close()


def read_audit(principal: str, limit: int = 50, *, db_path: str | None = None) -> list[dict[str, Any]]:
    count = max(1, min(int(limit), 100))
    connection = _connect(db_path)
    try:
        rows = connection.execute(
            """SELECT sequence, event_type, occurred_at, details_json, previous_hash, event_hash
               FROM audit_events WHERE principal=? ORDER BY sequence DESC LIMIT ?""",
            (principal, count),
        ).fetchall()
        return [
            {"sequence": row["sequence"], "event_type": row["event_type"], "occurred_at": row["occurred_at"],
             "details": json.loads(row["details_json"]), "previous_hash": row["previous_hash"],
             "event_hash": row["event_hash"]}
            for row in rows
        ]
    finally:
        connection.close()
