"""Bounded HTTP client for the model-free USECT-ZERO Go core.

The FastAPI gateway is an HTTP proxy only: it never runs candidate code or performs
engineering operations itself. The Go core remains the source of truth for
scoped developer API keys and human-gated operation rules.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 5
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


class USECTZeroError(RuntimeError):
    """Base error for safe, user-facing USECT-ZERO integration failures."""


class USECTZeroDisabled(USECTZeroError):
    """The optional integration has not been enabled."""


class USECTZeroConfigurationError(USECTZeroError):
    """The operator-provided core configuration is invalid."""


class USECTZeroAdminTokenMissing(USECTZeroError):
    """Admin-only forwarding cannot run without a separately configured token."""


class USECTZeroUnavailable(USECTZeroError):
    """The core service could not be reached or returned invalid data."""


class USECTZeroPayloadTooLarge(USECTZeroError):
    """An inbound request exceeds the adapter's size limit."""


class USECTZeroResponseTooLarge(USECTZeroError):
    """The core service returned more data than the adapter permits."""


@dataclass(frozen=True)
class CoreReply:
    status_code: int
    payload: dict[str, Any]


def is_enabled() -> bool:
    """Fail closed unless USECT-ZERO is explicitly enabled."""
    return os.getenv("USECT_ZERO_ENABLED", "false").strip().lower() in _ENABLED_VALUES


def _timeout_seconds() -> int:
    raw = os.getenv("USECT_ZERO_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return min(max(value, 1), 15)


def _configured_base_url() -> str:
    """Resolve the canonical URL and its legacy alias without a production localhost fallback."""
    primary = os.getenv("USECT_ZERO_URL", "").strip()
    alias = os.getenv("USECT_ZERO_BASE_URL", "").strip()
    raw = primary or alias
    if not raw:
        # A loopback default is convenient for local development only. Render
        # and other production deployments must configure an explicit service URL.
        production = any(
            os.getenv(name, "").strip().lower() in _ENABLED_VALUES
            for name in ("RENDER", "RENDER_SERVICE_ID", "K_SERVICE", "DYNO")
        )
        if production:
            raise USECTZeroConfigurationError(
                "Set USECT_ZERO_URL or USECT_ZERO_BASE_URL for the deployed USECT-ZERO service."
            )
        raw = "http://127.0.0.1:8780"
    return raw


def _admin_token() -> str:
    """Read the server-side admin token through one configuration boundary."""
    return os.getenv("USECT_ZERO_ADMIN_TOKEN", "").strip()


def _base_url() -> str:
    raw = _configured_base_url()

    # Render Blueprints expose a service's internal host and port through
    # fromService.property=hostport (for example, "usect-zero-core:10000").
    # Accept that exact host:port form as HTTP; explicit schemes still undergo
    # the strict URL validation below.
    if "://" not in raw:
        endpoint = urlsplit("//" + raw)
        try:
            port = endpoint.port
        except ValueError as exc:
            raise USECTZeroConfigurationError(
                "USECT_ZERO_URL host:port reference has an invalid port."
            ) from exc
        if (
            not endpoint.hostname
            or port is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.path
            or endpoint.query
            or endpoint.fragment
        ):
            raise USECTZeroConfigurationError(
                "USECT_ZERO_URL must be an absolute HTTP(S) URL or a service host:port reference."
            )
        raw = "http://" + raw

    parsed = urlsplit(raw)
    try:
        parsed.port  # Force validation of malformed/out-of-range ports.
    except ValueError as exc:
        raise USECTZeroConfigurationError(
            "USECT_ZERO_URL contains an invalid port."
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise USECTZeroConfigurationError(
            "USECT_ZERO_URL must be an absolute HTTP(S) URL without credentials, query, or fragment."
        )
    return raw.rstrip("/")


def request_core(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    query: dict[str, str] | None = None,
    api_key: str | None = None,
    admin: bool = False,
) -> CoreReply:
    """Send one allowlisted, bounded request to the configured Go API.

    Caller-supplied Authorization headers are intentionally not accepted. The
    caller's X-API-Key is forwarded only for the Go core to verify its scope.
    Admin actions use a separate server-side secret after the native FastAPI admin check.
    """
    if not is_enabled():
        raise USECTZeroDisabled("USECT-ZERO is disabled by configuration.")

    normalized_method = method.strip().upper()
    if normalized_method not in {"GET", "POST"}:
        raise USECTZeroConfigurationError("Only GET and POST are supported.")

    if (
        not isinstance(path, str)
        or not path.startswith("/v1/")
        or "?" in path
        or "#" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise USECTZeroConfigurationError("Invalid internal USECT-ZERO path.")

    raw_body = body or b""
    if len(raw_body) > MAX_REQUEST_BYTES:
        raise USECTZeroPayloadTooLarge("Request body exceeds the 1 MiB limit.")

    headers = {"Accept": "application/json"}
    if raw_body:
        headers["Content-Type"] = "application/json"

    supplied_key = (api_key or "").strip()
    if supplied_key:
        if len(supplied_key) > 4096 or "\r" in supplied_key or "\n" in supplied_key:
            raise USECTZeroConfigurationError("Invalid developer API key header.")
        headers["X-API-Key"] = supplied_key

    if admin:
        admin_token = _admin_token()
        if not admin_token:
            raise USECTZeroAdminTokenMissing(
                "The backend's USECT_ZERO_ADMIN_TOKEN is not configured."
            )
        headers["X-Admin-Token"] = admin_token

    url = _base_url() + path
    response = None
    chunks: list[bytes] = []
    total_bytes = 0
    try:
        response = requests.request(
            normalized_method,
            url,
            params=query or None,
            data=raw_body if normalized_method == "POST" else None,
            headers=headers,
            timeout=(_timeout_seconds(), _timeout_seconds()),
            allow_redirects=False,
            stream=True,
        )
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > MAX_RESPONSE_BYTES:
                raise USECTZeroResponseTooLarge(
                    "Core response exceeds the 5 MiB limit."
                )
            chunks.append(chunk)
    except USECTZeroResponseTooLarge:
        raise
    except requests.RequestException as exc:
        raise USECTZeroUnavailable("The USECT-ZERO core service is unavailable.") from exc
    finally:
        if response is not None:
            response.close()

    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise USECTZeroUnavailable("The USECT-ZERO core returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise USECTZeroUnavailable("The USECT-ZERO core returned an unexpected response shape.")

    return CoreReply(status_code=int(response.status_code), payload=payload)
