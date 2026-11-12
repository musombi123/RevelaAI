"""Human-gated, hash-preconditioned source repair transactions.

Plans can only replace UTF-8 text files under the selected repository root.
No shell commands, installers, scripts or arbitrary executables can be invoked.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "revelaai.repair-plan.v1"
TRANSACTION_SCHEMA = "revelaai.repair-transaction.v1"
MAX_CHANGES = 100
MAX_FILE_BYTES = 2 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt",
    ".html", ".htm", ".css", ".scss", ".go", ".mod", ".sum",
    ".rs", ".java", ".kt", ".php", ".rb", ".cs", ".sh", ".ps1",
    ".xml", ".properties", ".sql", ".dockerfile",
}
BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", "authorized_keys",
}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".p7b", ".p7c"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("Repair plan contains an empty path.")
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"Unsafe repair path rejected: {relative!r}")
    if candidate.name.lower() in BLOCKED_NAMES or candidate.suffix.lower() in BLOCKED_SUFFIXES:
        raise ValueError(f"Sensitive credential/key material cannot be modified: {relative}")
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES and candidate.name.lower() not in {"dockerfile", "makefile"}:
        raise ValueError(f"Repair target is not an approved text-file type: {relative}")
    target = root.joinpath(candidate)
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"Symbolic-link path components are not permitted: {relative}")
    try:
        target.parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        # A new nested directory may not exist yet; verify the nearest existing parent.
        parent = target.parent
        while not parent.exists() and parent != root:
            parent = parent.parent
        try:
            parent.resolve(strict=True).relative_to(root.resolve(strict=True))
        except (OSError, ValueError):
            raise ValueError(f"Repair target escapes the selected root: {relative}") from None
    return target


def _atomic_write(path: Path, content: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError(f"Refusing to write through a symbolic link: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".revela-repair-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def apply_repair_plan(
    root: Path,
    plan_path: Path,
    backup_root: Path | None = None,
    *,
    authorized: bool = False,
    approved: bool = False,
) -> dict[str, Any]:
    if not authorized or not approved:
        raise ValueError("Repair requires both --authorized and --approve from the local operator.")
    root = root.expanduser()
    plan_path = plan_path.expanduser()
    if root.is_symlink():
        raise ValueError("Repair root cannot be a symbolic link; select its real target explicitly.")
    if plan_path.is_symlink() or not plan_path.is_file():
        raise ValueError("Repair plan must be a regular, non-symbolic-link file.")
    root = root.resolve(strict=True)
    plan_path = plan_path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repair root must be an existing directory.")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Repair plan is unreadable or invalid JSON.") from None
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported repair plan schema; expected {PLAN_SCHEMA}.")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes or len(changes) > MAX_CHANGES:
        raise ValueError(f"Repair plan must contain 1–{MAX_CHANGES} file changes.")
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            raise ValueError("Each repair change must be a JSON object.")
        relative = item.get("path")
        target = _safe_path(root, relative)
        normalized = target.relative_to(root).as_posix()
        if normalized in seen:
            raise ValueError(f"Duplicate repair target: {normalized}")
        seen.add(normalized)
        expected = item.get("expected_sha256")
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)):
            raise ValueError(f"Invalid expected_sha256 for {normalized}.")
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"Repair target is not a regular file: {normalized}")
            old = target.read_bytes()
            if len(old) > MAX_FILE_BYTES:
                raise ValueError(f"Existing repair target exceeds {MAX_FILE_BYTES} bytes: {normalized}")
            if expected is None or _sha256(old) != expected:
                raise ValueError(f"Hash precondition failed for {normalized}; refresh the plan before applying.")
            mode = target.stat().st_mode & 0o777
        else:
            old = None
            mode = None
            if expected is not None:
                raise ValueError(f"Expected file does not exist: {normalized}")
        encoded = item.get("new_content_base64")
        if not isinstance(encoded, str):
            raise ValueError(f"new_content_base64 is required for {normalized}.")
        try:
            new_bytes = base64.b64decode(encoded, validate=True)
            new_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ValueError(f"Repair content for {normalized} must be valid Base64 UTF-8 text.") from None
        if not new_bytes or len(new_bytes) > MAX_FILE_BYTES:
            raise ValueError(f"New content for {normalized} must be between 1 and {MAX_FILE_BYTES} bytes.")
        prepared.append({
            "path": normalized, "target": target, "old": old, "mode": mode,
            "new": new_bytes, "reason": str(item.get("reason") or "")[:1000],
        })

    backup_root = (backup_root or (Path.home() / ".revela-fieldkit" / "backups")).expanduser()
    if backup_root.is_symlink():
        raise ValueError("Backup directory cannot be a symbolic link.")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_root = backup_root.resolve(strict=True)
    try:
        backup_root.relative_to(root)
        raise ValueError("Backup directory must be outside the audited repository.")
    except ValueError as exc:
        if str(exc) == "Backup directory must be outside the audited repository.":
            raise
    transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    transaction_dir = backup_root / transaction_id
    transaction_dir.mkdir(mode=0o700)
    records = []
    written: list[dict[str, Any]] = []
    try:
        for item in prepared:
            backup_relative = Path("files") / item["path"]
            backup_file = transaction_dir / backup_relative
            if item["old"] is not None:
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                backup_file.write_bytes(item["old"])
            _atomic_write(item["target"], item["new"], item["mode"])
            written.append(item)
            records.append({
                "path": item["path"],
                "created": item["old"] is None,
                "backup": backup_relative.as_posix() if item["old"] is not None else None,
                "before_sha256": _sha256(item["old"]) if item["old"] is not None else None,
                "before_mode": item["mode"],
                "after_sha256": _sha256(item["new"]),
                "reason": item["reason"],
            })
        transaction = {
            "schema_version": TRANSACTION_SCHEMA, "transaction_id": transaction_id,
            "created_at": _now(), "root": str(root), "plan_id": str(plan.get("id") or "")[:120],
            "changes": records, "status": "applied",
        }
        transaction_file = transaction_dir / "transaction.json"
        transaction_file.write_text(json.dumps(transaction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        for item in reversed(written):
            if item["old"] is None:
                try:
                    item["target"].unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                try:
                    _atomic_write(item["target"], item["old"], item["mode"])
                except OSError:
                    pass
        raise
    return {
        "status": "applied", "transaction_id": transaction_id,
        "transaction": str(transaction_file.resolve()), "root": str(root),
        "files_changed": len(records),
        "backup_directory": str(transaction_dir.resolve()),
        "rollback_command": f"revela-fieldkit repair rollback --transaction {transaction_file} --authorized --approve",
        "human_review_required": True,
    }


def rollback_repair(
    transaction_path: Path,
    *,
    authorized: bool = False,
    approved: bool = False,
) -> dict[str, Any]:
    if not authorized or not approved:
        raise ValueError("Rollback requires both --authorized and --approve from the local operator.")
    transaction_path = transaction_path.expanduser()
    if transaction_path.is_symlink() or not transaction_path.is_file():
        raise ValueError("Transaction record must be a regular, non-symbolic-link file.")
    transaction_path = transaction_path.resolve(strict=True)
    try:
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Transaction record is unreadable or invalid JSON.") from None
    if not isinstance(transaction, dict) or transaction.get("schema_version") != TRANSACTION_SCHEMA:
        raise ValueError("Unsupported repair transaction schema.")
    if transaction.get("status") != "applied" or not isinstance(transaction.get("changes"), list):
        raise ValueError("Transaction is not in an applied state.")
    root = Path(str(transaction.get("root") or ""))
    if root.is_symlink():
        raise ValueError("Original repository root now resolves through a symbolic link.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Original repository root is unavailable.")
    transaction_dir = transaction_path.parent
    completed = []
    for item in reversed(transaction["changes"]):
        relative = item.get("path")
        target = _safe_path(root, relative)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"Rollback target is missing or unsafe: {relative}")
        current = target.read_bytes()
        if _sha256(current) != item.get("after_sha256"):
            raise ValueError(f"Rollback blocked because {relative} changed after the repair was applied.")
        if item.get("created") is True:
            target.unlink()
            completed.append(relative)
            continue
        backup_rel = Path(str(item.get("backup") or ""))
        if backup_rel.is_absolute() or any(part in {"", ".", ".."} for part in backup_rel.parts):
            raise ValueError(f"Unsafe backup reference for {relative}.")
        backup = transaction_dir.joinpath(backup_rel)
        try:
            backup.resolve(strict=True).relative_to(transaction_dir.resolve(strict=True))
        except (OSError, ValueError):
            raise ValueError(f"Backup file unavailable or outside the transaction: {relative}") from None
        if backup.is_symlink() or not backup.is_file():
            raise ValueError(f"Backup file unavailable: {relative}")
        original = backup.read_bytes()
        if _sha256(original) != item.get("before_sha256"):
            raise ValueError(f"Backup integrity check failed for {relative}.")
        original_mode = item.get("before_mode")
        _atomic_write(target, original, int(original_mode) if isinstance(original_mode, int) else (target.stat().st_mode & 0o777))
        completed.append(relative)
    transaction["status"] = "rolled_back"
    transaction["rolled_back_at"] = _now()
    transaction_path.write_text(json.dumps(transaction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "rolled_back", "transaction_id": transaction.get("transaction_id"),
        "files_restored": len(completed), "paths": completed,
    }
