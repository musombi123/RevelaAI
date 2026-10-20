"""Process-local security state shared by native FastAPI middleware and SCI controls."""
from __future__ import annotations

from collections import deque
from threading import Lock

SCI_THROTTLE = {"enabled": False, "reason": None, "since": None}
SCI_REQUEST_TIMES: deque[float] = deque()
SCI_RATE_LOCK = Lock()

__all__ = ["SCI_THROTTLE", "SCI_REQUEST_TIMES", "SCI_RATE_LOCK"]
