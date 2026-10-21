"""Framework-neutral HTTP configuration for the ASGI gateway."""
from __future__ import annotations

import os


DEFAULT_CORS_ORIGINS: tuple[str, ...] = ()


def parse_cors_origins() -> list[str]:
    """Read only explicitly configured trusted frontend origins."""
    configured = os.getenv("CORS_ORIGINS", "")
    origins: list[str] = []
    for item in (*DEFAULT_CORS_ORIGINS, *configured.split(",")):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


CORS_ORIGINS = parse_cors_origins()
