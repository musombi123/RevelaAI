"""Stable device identity signals for license binding.

The result is a software fingerprint, not cryptographic proof of physical hardware.
For high-assurance deployments, bind enrollment to TPM-backed device attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from pathlib import Path
from typing import Any


def _machine_id() -> str:
    configured = os.getenv("REVELA_HARDWARE_ID", "").strip()
    if configured:
        return configured
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(candidate).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    if platform.system() == "Windows":
        try:
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                if value:
                    return str(value)
        except (OSError, ImportError):
            pass
    return ""


def hardware_fingerprint() -> str:
    """Return a stable, non-reversible fingerprint from available identity signals."""
    identity = {
        "machine_id": _machine_id(),
        "mac_node": f"{uuid.getnode():012x}",
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
    }
    if not identity["machine_id"] and not os.getenv("REVELA_HARDWARE_ID"):
        raise RuntimeError("Hardware identity unavailable; enroll this device explicitly.")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"revelacode-hardware-bind-v1\0" + encoded).hexdigest()


def compare_hardware_binding(claims: dict[str, Any], *, current: str | None = None) -> bool:
    expected = claims.get("hardware_fingerprint")
    if not expected:
        return False
    return hashlib.compare_digest(str(expected), current or hardware_fingerprint()) if hasattr(hashlib, "compare_digest") else __import__("hmac").compare_digest(str(expected), current or hardware_fingerprint())


def hardware_status() -> dict[str, Any]:
    try:
        return {"available": True, "fingerprint": hardware_fingerprint(), "attestation": "software-signals-only"}
    except RuntimeError:
        return {"available": False, "fingerprint": None, "attestation": "unavailable"}
