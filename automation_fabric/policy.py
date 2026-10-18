"""Permission and path policy for Automation Fabric.

The tool runtime deliberately does not expose shell execution, arbitrary Python
imports, unrestricted filesystem access, or implicit hardware control.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

SCOPES: dict[str, str] = {
    "system:read": "Read non-secret runtime and platform information.",
    "workspace:read": "List or read files inside this user's automation workspace.",
    "workspace:write": "Create or replace files inside this user's automation workspace.",
    "tools:scaffold": "Create a non-executable tool proposal inside the workspace.",
    "research:public_web": "Fetch a public HTTPS page from the configured host allowlist.",
    "hardware:discover": "Read-only discovery of supported local device nodes.",
}

MAX_CONSENT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_CONSENT_TTL_SECONDS = 60 * 60
MAX_PLAN_TTL_SECONDS = 15 * 60


def normalize_scopes(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("scopes must be a non-empty array")
    if len(value) > len(SCOPES):
        raise ValueError("too many permission scopes")
    scopes: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in SCOPES:
            raise ValueError("unknown permission scope")
        if item not in scopes:
            scopes.append(item)
    return scopes


def resolve_workspace_path(workspace: str | Path, raw_path: Any, *, allow_root: bool = False) -> Path:
    """Resolve a relative path and reject traversal, drive paths, and workspace escapes."""
    if not isinstance(raw_path, str):
        raise ValueError("path must be a string")
    raw = raw_path.strip()
    if not raw or len(raw) > 512 or "\x00" in raw:
        raise ValueError("path must be 1–512 characters")
    windows_path = PureWindowsPath(raw)
    if raw.startswith(("/", "\\")) or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("absolute paths are not allowed")
    normalized_parts = raw.replace("\\", "/").split("/")
    if any(part == ".." for part in normalized_parts):
        raise ValueError("parent-directory traversal is not allowed")

    base = Path(workspace).expanduser().resolve()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("path escapes the isolated workspace") from exc
    if candidate == base and not allow_root:
        raise ValueError("the workspace root cannot be used for this operation")
    return candidate
