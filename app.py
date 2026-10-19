"""RevelaAI application entry point.

The application object is a native FastAPI instance defined in :mod:`asgi`.
This module exists for conventional imports and local execution only.
"""
from __future__ import annotations

import os

from asgi import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "asgi:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        reload=os.getenv("ENVIRONMENT", "production").strip().lower() == "development",
    )
