"""RVX-only client for configured inter-core routes; no JSON fallback.

The HTTP body is an encrypted RVXP1 envelope. A receiving service must use the
same separately-provisioned mesh secret and verify the route + UTC dialect day.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from rvx.crypto import RecipeError, open_packet, seal_packet


class MeshCallError(RuntimeError):
    pass


def _routes() -> dict[str, str]:
    raw = os.getenv("REVELA_RVX_ROUTES", "").strip()
    if not raw:
        raise MeshCallError("REVELA_RVX_ROUTES is not configured; RVX mesh calls fail closed.")
    try:
        routes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeshCallError("REVELA_RVX_ROUTES must be a JSON object.") from exc
    if not isinstance(routes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in routes.items()):
        raise MeshCallError("REVELA_RVX_ROUTES must map route names to URLs.")
    return routes


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    host = (parsed.hostname or "").lower()
    allowed_local = host in {"127.0.0.1", "::1", "localhost"} or (host and "." not in host and host not in {"", "0.0.0.0"})
    if parsed.scheme == "http" and allowed_local:
        return
    raise MeshCallError("RVX mesh requires HTTPS except for loopback or internal single-label service names.")


def rvx_call(route: str, packet: Any, *, timeout: float = 8.0) -> Any:
    """Send one encrypted request to an explicitly configured mesh route."""
    routes = _routes()
    destination = routes.get(route)
    if not destination:
        raise MeshCallError(f"Unknown RVX mesh route: {route}")
    _validate_url(destination)
    envelope = seal_packet(packet, route=route)
    request = urllib.request.Request(
        destination,
        data=json.dumps(envelope, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/vnd.revelacode.rvx+json", "Accept": "application/vnd.revelacode.rvx+json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status < 200 or response.status >= 300:
                raise MeshCallError(f"RVX peer returned HTTP {response.status}.")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type != "application/vnd.revelacode.rvx+json":
                raise MeshCallError("RVX peer returned a non-RVX content type; plaintext/JSON fallback is disabled.")
            reply = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MeshCallError(f"RVX peer rejected request with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise MeshCallError("RVX mesh transport failed.") from exc
    try:
        return open_packet(reply, route=route)
    except RecipeError as exc:
        raise MeshCallError("RVX peer response failed authentication or dialect freshness checks.") from exc
