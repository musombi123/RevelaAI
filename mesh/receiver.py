"""Reusable FastAPI router for Python peers speaking the encrypted RVXP1 protocol.

Existing Go cores do not implement this router; install an equivalent receiver
in a core before directing production mesh calls to that service.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from rvx.crypto import RecipeError, open_packet, seal_packet

RVX_CONTENT_TYPE = "application/vnd.revelacode.rvx+json"
MAX_PACKET_BYTES = 2_000_000


def create_rvx_receiver_router(
    handlers: Mapping[str, Callable[[Any], Any]],
    *,
    secret: bytes | None = None,
    prefix: str = "/internal/rvx",
) -> APIRouter:
    """Create an internal router with explicit route-to-handler allowlisting.

    Handlers receive only authenticated/decrypted payloads. They should validate
    payload schemas and treat user_id as a claim forwarded by the authenticated
    gateway, not as a substitute for their own entitlement/policy checks.
    """
    routes = dict(handlers)
    if not routes or any(not isinstance(name, str) or not name or len(name) > 160 for name in routes):
        raise ValueError("At least one bounded named RVX handler is required.")
    router = APIRouter(prefix=prefix)

    @router.post("/{route:path}")
    async def dispatch_rvx_packet(route: str, request: Request) -> Response:
        handler = routes.get(route)
        if handler is None:
            raise HTTPException(status_code=404, detail="RVX route is not registered")
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != RVX_CONTENT_TYPE:
            raise HTTPException(status_code=415, detail="RVX content type required")
        raw = await request.body()
        if not raw or len(raw) > MAX_PACKET_BYTES:
            raise HTTPException(status_code=413 if raw else 400, detail="Invalid RVX packet size")
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Malformed RVX envelope") from exc
        try:
            payload = open_packet(envelope, route=route, secret=secret)
        except RecipeError as exc:
            raise HTTPException(status_code=401, detail="RVX packet authentication or freshness check failed") from exc
        try:
            result = handler(payload)
            if inspect.isawaitable(result):
                result = await result
            response_envelope = seal_packet(result, route=route, secret=secret)
            body = json.dumps(response_envelope, separators=(",", ":"), sort_keys=True).encode()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="RVX handler failed") from exc
        return Response(content=body, status_code=200, media_type=RVX_CONTENT_TYPE)

    return router
