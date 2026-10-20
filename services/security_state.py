"""Process-local security state owned by the native ASGI application."""
from __future__ import annotations

from collections import deque
from threading import Lock

# Shared object imported by the FastAPI middleware and the disaster simulation.
# Keep this module dependency-free to avoid importing legacy route frameworks.
SCI_THROTTLE = {"enabled": False, "reason": None, "since": None}
SCI_REQUEST_TIMES: deque[float] = deque()
SCI_RATE_LOCK = Lock()

__all__ = ["SCI_REQUEST_TIMES", "SCI_RATE_LOCK", "SCI_THROTTLE"]
