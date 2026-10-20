"""Framework-neutral HTTP configuration for the ASGI gateway."""
from __future__ import annotations

import os


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://revelacode-frontend.onrender.com",
    "https://revelacode.co.ke",
    "https://www.revelacode.co.ke",
    "https://localhost",
)


def parse_cors_origins() -> list[str]:
    """Read trusted frontend origins; configured values extend safe defaults."""
    configured = os.getenv("CORS_ORIGINS", "")
    origins: list[str] = []
    for item in (*DEFAULT_CORS_ORIGINS, *configured.split(",")):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


CORS_ORIGINS = parse_cors_origins()
