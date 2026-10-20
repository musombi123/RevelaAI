"""Authenticated, date-scoped RVX dialect artifact rotation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rvx.crypto import RecipeError, load_master_key, open_blob, seal_blob
from rvx.dialect import ALPHABET, KEYWORDS


def _default_path() -> Path:
    return Path(os.getenv("REVELA_DIALECT_PATH", "rvx/dialect.json")).expanduser()


def evolve_dialect(
    *,
    master_key_path: str | Path | None = None,
    output_path: str | Path | None = None,
    now: datetime | None = None,
    reason: str = "scheduled_rotation",
) -> dict[str, Any]:
    """Write a newly encrypted dialect artifact atomically; never claim 50x gains."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    moment = moment.astimezone(timezone.utc)
    root = load_master_key(master_key_path)
    destination = Path(output_path).expanduser() if output_path else _default_path()
    previous_digest = None
    if destination.exists():
        previous_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    epoch = int(moment.timestamp())
    mapping: dict[str, str] = {}
    for word in KEYWORDS:
        digest = hashlib.sha256(root + f"{moment:%Y-%m-%d}:{epoch}:{word}:{secrets.token_hex(8)}".encode()).hexdigest()
        mapping[word] = f"rvx_{ALPHABET[int(digest[:4], 16) % len(ALPHABET)]}_{digest[4:14]}"
    document = {
        "schema_version": 2,
        "dialect_version": f"rvx-{moment:%Y.%m.%d}-{epoch}",
        "day": moment.strftime("%Y-%m-%d"),
        "generation": epoch,
        "reason": reason[:80],
        "keywords": mapping,
        "previous_artifact_sha256": previous_digest,
        "generated_at": moment.isoformat(),
    }
    encrypted = seal_blob(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        root,
        metadata={"type": "rvx-dialect", "day": document["day"], "generation": epoch},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(encrypted)
    try:
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "dialect_version": document["dialect_version"],
        "day": document["day"],
        "generation": epoch,
        "previous_artifact_sha256": previous_digest,
        "artifact_sha256": hashlib.sha256(encrypted).hexdigest(),
    }


def verify_dialect(path: str | Path | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    target = Path(path).expanduser() if path else _default_path()
    if not target.is_file():
        return {"valid": False, "reason": "dialect_artifact_missing", "path": str(target)}
    try:
        root = load_master_key()
        document = json.loads(open_blob(target.read_bytes(), root))
    except (OSError, ValueError, RecipeError, json.JSONDecodeError):
        return {"valid": False, "reason": "dialect_authentication_failed", "path": str(target)}
    today = moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if document.get("day") != today:
        return {"valid": False, "reason": "Dialect obsolete - Pull new", "path": str(target)}
    return {"valid": True, "day": today, "dialect_version": document.get("dialect_version"), "path": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate the encrypted RVX dialect artifact")
    parser.add_argument("--master-key", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reason", default="scheduled_rotation")
    args = parser.parse_args()
    print(json.dumps(evolve_dialect(master_key_path=args.master_key, output_path=args.output, reason=args.reason), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
