"""Append-only-by-policy JSONL audit chain with tamper detection.

The chain detects accidental/unsophisticated edits; an administrator who can
rewrite the entire file can recompute an unkeyed chain. Export checkpoints to
separately controlled immutable storage for stronger evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_ZERO_HASH = "0" * 64


class AuditLedgerError(RuntimeError):
    """Audit chain integrity or storage error."""


def ledger_path() -> Path:
    configured = os.getenv("REVELA_AUDIT_LEDGER_PATH", "").strip()
    return Path(configured).expanduser() if configured else (
        Path(os.getenv("REVELA_DATA_DIR", str(Path.home() / ".revelaai"))).expanduser() / "audit" / "events.jsonl"
    )


def _canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class AuditLedger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else ledger_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def verify(self) -> dict[str, Any]:
        prior_hash = _ZERO_HASH
        count = 0
        try:
            with _LOCK, self.path.open("rb") as stream:
                for line_number, raw_line in enumerate(stream, 1):
                    if not raw_line.endswith(b"\n"):
                        raise AuditLedgerError(f"Truncated audit record at line {line_number}.")
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise AuditLedgerError(f"Invalid JSON at line {line_number}.") from exc
                    record_hash = record.pop("record_hash", None)
                    if record.get("previous_hash") != prior_hash:
                        raise AuditLedgerError(f"Previous hash mismatch at line {line_number}.")
                    expected = hashlib.sha256(_canonical(record)).hexdigest()
                    if not isinstance(record_hash, str) or record_hash != expected:
                        raise AuditLedgerError(f"Record hash mismatch at line {line_number}.")
                    prior_hash = record_hash
                    count += 1
        except FileNotFoundError:
            return {"ok": True, "records": 0, "head_hash": _ZERO_HASH}
        except OSError as exc:
            raise AuditLedgerError("Could not read audit ledger.") from exc
        return {"ok": True, "records": count, "head_hash": prior_hash}

    def append(self, *, actor_user_id: str, action: str, object_id: str = "",
               detail: dict[str, Any] | None = None) -> dict[str, Any]:
        if not actor_user_id.strip() or not action.strip():
            raise AuditLedgerError("Actor and action are required.")
        safe_detail = detail or {}
        # Prevent accidental credential/token writes into evidence.
        rendered = json.dumps(safe_detail, ensure_ascii=False).lower()
        if any(term in rendered for term in ("license_key", "authorization", "master.key", "private_key", "secret_key", "password")):
            raise AuditLedgerError("Audit detail contains a prohibited secret-field marker.")
        with _LOCK:
            chain = self.verify()
            body = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor_user_id": actor_user_id[:160],
                "action": action[:100],
                "object_id": object_id[:160],
                "detail": safe_detail,
                "previous_hash": chain["head_hash"],
            }
            record_hash = hashlib.sha256(_canonical(body)).hexdigest()
            record = {**body, "record_hash": record_hash}
            raw = _canonical(record) + b"\n"
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                with os.fdopen(descriptor, "ab") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                raise
            return record
