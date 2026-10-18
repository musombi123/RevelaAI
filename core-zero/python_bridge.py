"""Optional Python bridge to the deterministic Go CLI; it does not call a model or the network."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Any

class USECTZeroBridgeError(RuntimeError):
    pass

def scan_repository(repo_root: str | os.PathLike[str], binary: str | os.PathLike[str] = "core-zero/usect-zero", timeout: int = 20) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    executable = Path(binary)
    if not executable.is_absolute(): executable = (root / executable).resolve()
    if not executable.is_file(): raise USECTZeroBridgeError(f"USECT-ZERO CLI not found: {executable}; build core-zero first")
    try:
        result = subprocess.run([str(executable), "-mode", "scan", "-root", str(root)], cwd=root, check=False, capture_output=True, text=True, timeout=timeout, env={**os.environ, "USECT_ZERO_REPO_ROOT": str(root)})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise USECTZeroBridgeError(f"could not run bounded scan: {type(exc).__name__}") from exc
    if result.returncode != 0: raise USECTZeroBridgeError(f"scan failed with exit code {result.returncode}: {result.stderr[-1000:]}")
    try: return json.loads(result.stdout)
    except json.JSONDecodeError as exc: raise USECTZeroBridgeError("Go CLI returned invalid JSON evidence") from exc
