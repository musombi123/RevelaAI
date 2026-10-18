"""Authenticated cloud control plane for RevelaAI Automation Fabric."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from automation_fabric.http import create_automation_blueprint


def _authenticate_user():
    """Reuse RevelaAI's existing JWT + authoritative RevelaCode user verification."""
    try:
        from routes.memory_routes import _require_identity
        _, user_id, error = _require_identity()
    except Exception:
        return None, ({"status": "error", "code": "authentication_unavailable"}, 503)
    if error:
        return None, error
    return "user:" + str(user_id), None


def _workspace_for_user(principal: str) -> Path:
    root = Path(os.getenv(
        "REVELAAI_AUTOMATION_SERVER_WORKSPACE",
        "/tmp/revelaai-automation-workspaces",
    )).expanduser()
    # Never use the raw account identifier as a path segment.
    key = hashlib.sha256(principal.encode("utf-8")).hexdigest()[:24]
    workspace = root / key
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        workspace.chmod(0o700)
    except OSError:
        pass
    return workspace


def _database_path() -> str:
    return os.getenv("REVELAAI_AUTOMATION_DB", "/tmp/revelaai-automation-fabric.sqlite3")


automation_fabric_bp = create_automation_blueprint(
    "automation_fabric_bp",
    auth_resolver=_authenticate_user,
    workspace_resolver=_workspace_for_user,
    database_resolver=_database_path,
    local_mode=False,
)
