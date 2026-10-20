"""Read signed Genesis tools and adapt declarations for the existing AI provider.

This module never imports or executes generated code. All execution requests are
sent to the Genesis service, which owns sandbox policy and artifact verification.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit

import requests

logger = logging.getLogger("revelaai.genesis_tools")
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_INPUT_BYTES = 64_000
_MAX_RESULT_BYTES = 32_000
_TIMEOUT_SECONDS = 8.0
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class GenesisToolRegistryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "genesis_tool_registry_error", status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _configuration() -> tuple[str, dict[str, str]]:
    raw_base = str(os.getenv("GENESIS_BASE_URL") or "").strip().rstrip("/")
    token = str(os.getenv("GENESIS_ADMIN_TOKEN") or "").strip()
    if not raw_base:
        raise GenesisToolRegistryError("Genesis is unavailable: GENESIS_BASE_URL is not configured.", code="genesis_unavailable", status_code=503)
    if not token:
        raise GenesisToolRegistryError("Genesis tool access is not configured.", code="genesis_admin_token_not_configured", status_code=503)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_base):
        raise GenesisToolRegistryError("Genesis service URL is invalid.", code="genesis_url_invalid", status_code=503)

    # Render injects a private service's hostport as a bare DNS label and
    # port (for example genesis-core-one:10000). Normalize only that narrow
    # authority form to HTTP; external hosts still require HTTPS.
    base = raw_base
    if "://" not in raw_base:
        authority = urlsplit("//" + raw_base)
        try:
            port = authority.port
        except ValueError:
            port = None
        host = authority.hostname or ""
        if (
            not host
            or port is None
            or authority.username is not None
            or authority.password is not None
            or authority.path
            or authority.query
            or authority.fragment
            or "." in host
            or host.lower() == "localhost"
        ):
            raise GenesisToolRegistryError("Bare Genesis URL must be a Render private hostport.", code="genesis_url_invalid", status_code=503)
        base = "http://" + raw_base

    parsed = urlsplit(base)
    try:
        parsed.port
    except ValueError:
        raise GenesisToolRegistryError("Genesis service URL contains an invalid port.", code="genesis_url_invalid", status_code=503) from None
    host = parsed.hostname or ""
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise GenesisToolRegistryError("Genesis service URL must be an HTTP(S) origin without credentials or a path.", code="genesis_url_invalid", status_code=503)
    if parsed.scheme != "https":
        is_loopback = host.lower() == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(host.strip("[]")).is_loopback
        except ValueError:
            pass
        is_render_private = "." not in host and host.lower() != "localhost"
        if not (is_loopback or is_render_private):
            raise GenesisToolRegistryError("Public Genesis hosts must use HTTPS.", code="genesis_url_tls_required", status_code=503)

    base = base.rstrip("/")
    return base, {"Accept": "application/json", "X-Genesis-Token": token}

def _request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, extra_headers: dict[str, str] | None = None, timeout: float = _TIMEOUT_SECONDS) -> dict[str, Any]:
    base, headers = _configuration()
    for key, value in (extra_headers or {}).items():
        if key not in {"X-Genesis-Owner-Approval", "X-Genesis-Action-Approval"}:
            raise GenesisToolRegistryError("Unsupported Genesis elevated-operation header.", code="invalid_elevated_header", status_code=400)
        if value:
            headers[key] = value
    try:
        response = requests.request(
            method,
            base + path,
            json=payload,
            headers=headers,
            timeout=max(1.0, min(float(timeout), 180.0)),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise GenesisToolRegistryError("Genesis is unavailable; normal RevelaAI chat can continue.", code="genesis_unavailable", status_code=503) from None
    if len(response.content or b"") > _MAX_RESPONSE_BYTES:
        raise GenesisToolRegistryError("Genesis returned an oversized tool registry response.", code="genesis_response_too_large")
    if 300 <= response.status_code < 400:
        raise GenesisToolRegistryError("Genesis redirects are not accepted.", code="genesis_redirect_rejected")
    if not response.ok:
        code = "genesis_unavailable" if response.status_code >= 500 else "genesis_tool_request_rejected"
        status = 503 if response.status_code >= 500 else response.status_code
        raise GenesisToolRegistryError("Genesis could not complete the tool registry request.", code=code, status_code=status)
    try:
        result = response.json()
    except ValueError:
        raise GenesisToolRegistryError("Genesis returned invalid JSON.", code="genesis_invalid_payload") from None
    if not isinstance(result, dict):
        raise GenesisToolRegistryError("Genesis returned an unexpected response shape.", code="genesis_invalid_payload")
    return result


def list_active_tools(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Return verified active tool records; registry failures are explicit."""
    result = _request("/v1/genesis/registry/tools")
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise GenesisToolRegistryError("Genesis tool registry response is missing tools.", code="genesis_invalid_payload")
    active: list[dict[str, Any]] = []
    for item in tools[:128]:
        if not isinstance(item, dict) or item.get("active") is not True:
            continue
        manifest = item.get("manifest")
        if not isinstance(manifest, dict) or not _valid_manifest_shape(manifest):
            continue
        active.append(item)
    return active


def _valid_manifest_shape(manifest: dict[str, Any]) -> bool:
    name = str(manifest.get("name") or "")
    if not _NAME_RE.fullmatch(name):
        return False
    if manifest.get("schema_version") != "genesis.tool-manifest.v1":
        return False
    if manifest.get("language") not in {"go", "python"}:
        return False
    if manifest.get("risk_tier") not in {0, 1, 2}:
        return False
    permissions = manifest.get("permissions")
    if not isinstance(permissions, dict):
        return False
    derived = 2 if permissions.get("hardware") is True else 1 if any(
        permissions.get(key) is True for key in ("network", "filesystem", "secrets")
    ) else 0
    return derived == manifest.get("risk_tier")


def gemini_function_declarations(tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return Gemini REST functionDeclarations for already-active signed tools."""
    tools = list_active_tools() if tools is None else tools
    declarations: list[dict[str, Any]] = []
    for item in tools[:64]:
        manifest = item.get("manifest") if isinstance(item, dict) else None
        if not isinstance(manifest, dict) or not _valid_manifest_shape(manifest):
            continue
        name = str(manifest["name"])
        input_schema = manifest.get("input_schema")
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            continue
        declarations.append({
            "name": "genesis_" + name,
            "description": (
                f"Call the signed Genesis tool {name} version {manifest.get('version', 'unknown')}. "
                f"Risk tier {manifest['risk_tier']}; tool execution is sandboxed by Genesis."
            )[:1000],
            "parameters": input_schema,
        })
    return declarations


def prompt_based_tool_catalog(tools: list[dict[str, Any]] | None = None) -> str:
    """Fallback catalogue for non-Gemini providers; it does not execute tools."""
    tools = list_active_tools() if tools is None else tools
    rows: list[dict[str, Any]] = []
    for item in tools[:64]:
        manifest = item.get("manifest") if isinstance(item, dict) else None
        if not isinstance(manifest, dict) or not _valid_manifest_shape(manifest):
            continue
        rows.append({
            "function": "genesis_" + manifest["name"],
            "version": manifest.get("version"),
            "risk_tier": manifest["risk_tier"],
            "parameters": manifest.get("input_schema"),
            "description": "Invoke only by emitting a structured tool request; never claim execution before the gateway confirms it.",
        })
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))[:32_000]


def get_signed_tool_version(name: str, version: str, artifact_hash: str) -> dict[str, Any]:
    """Fetch a specific signed version and let Genesis re-verify its signature/hash."""
    if not _NAME_RE.fullmatch(str(name or "")):
        raise GenesisToolRegistryError("Invalid Genesis tool name.", code="invalid_tool_name", status_code=400)
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}", str(version or "")):
        raise GenesisToolRegistryError("Invalid Genesis tool version.", code="invalid_tool_version", status_code=400)
    if not re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")):
        raise GenesisToolRegistryError("Invalid Genesis artifact hash.", code="invalid_artifact_hash", status_code=400)
    result = _request(
        "/v1/genesis/registry/tools/" + quote(name, safe="") + "/" + quote(version, safe="") + "/" + quote(artifact_hash, safe="")
    )
    record = result.get("artifact")
    if not isinstance(record, dict) or not isinstance(record.get("manifest"), dict):
        raise GenesisToolRegistryError("Genesis returned an invalid signed version record.", code="genesis_invalid_payload")
    return record


def list_signed_tools() -> list[dict[str, Any]]:
    """Return every verified append-only registry version, active or inactive."""
    result = _request("/v1/genesis/registry/tools")
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise GenesisToolRegistryError("Genesis tool registry response is missing tools.", code="genesis_invalid_payload")
    return [item for item in tools[:512] if isinstance(item, dict) and isinstance(item.get("manifest"), dict)]


def provider_tool_context(provider: str, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Choose Gemini function declarations or a provider-neutral prompt catalogue."""
    provider = str(provider or "").strip().lower()
    if provider not in {"gemini", "hf", "mvi"}:
        raise GenesisToolRegistryError("Provider must be one of the existing text providers.", code="invalid_provider", status_code=400)
    tools = list_active_tools() if tools is None else tools
    if provider == "gemini":
        return {"mode": "native_function_declarations", "provider": "gemini", "function_declarations": gemini_function_declarations(tools)}
    return {"mode": "prompt_based", "provider": provider, "tool_catalog": prompt_based_tool_catalog(tools)}


def activate_signed_tool(name: str, version: str, artifact_hash: str) -> dict[str, Any]:
    """Activate a signed version via the Gateway; owner credential stays server-side."""
    if not _NAME_RE.fullmatch(str(name or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")):
        raise GenesisToolRegistryError("Invalid Genesis artifact reference.", code="invalid_artifact_reference", status_code=400)
    owner_token = str(os.getenv("GENESIS_OWNER_APPROVAL_TOKEN") or "").strip()
    if not owner_token:
        raise GenesisToolRegistryError("Owner approval is not configured; activation remains disabled.", code="owner_approval_not_configured", status_code=503)
    return _request(
        "/v1/genesis/registry/tools/" + quote(name, safe="") + "/" + quote(str(version), safe="") + "/" + quote(artifact_hash, safe="") + "/activate",
        method="POST",
        payload={"owner_approval_hash": artifact_hash},
        extra_headers={"X-Genesis-Owner-Approval": owner_token},
        timeout=15.0,
    )


def deactivate_signed_tool(name: str) -> dict[str, Any]:
    if not _NAME_RE.fullmatch(str(name or "")):
        raise GenesisToolRegistryError("Invalid Genesis tool name.", code="invalid_tool_name", status_code=400)
    return _request("/v1/genesis/registry/tools/" + quote(name, safe="") + "/deactivate", method="POST", payload={}, timeout=15.0)


def rollback_signed_tool(name: str, version: str, artifact_hash: str) -> dict[str, Any]:
    if not _NAME_RE.fullmatch(str(name or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")):
        raise GenesisToolRegistryError("Invalid Genesis artifact reference.", code="invalid_artifact_reference", status_code=400)
    owner_token = str(os.getenv("GENESIS_OWNER_APPROVAL_TOKEN") or "").strip()
    if not owner_token:
        raise GenesisToolRegistryError("Owner approval is not configured; rollback remains disabled.", code="owner_approval_not_configured", status_code=503)
    return _request(
        "/v1/genesis/registry/tools/" + quote(name, safe="") + "/rollback",
        method="POST",
        payload={"version": version, "artifact_hash": artifact_hash, "owner_approval_hash": artifact_hash},
        extra_headers={"X-Genesis-Owner-Approval": owner_token},
        timeout=15.0,
    )


def publish_signed_tool(name: str) -> dict[str, Any]:
    if not _NAME_RE.fullmatch(str(name or "")):
        raise GenesisToolRegistryError("Invalid Genesis tool name.", code="invalid_tool_name", status_code=400)
    return _request(
        "/v1/genesis/registry/tools/" + quote(name, safe="") + "/publish",
        method="POST", payload={}, timeout=180.0,
    )


def confirm_tier2_action(
    name: str,
    version: str,
    artifact_hash: str,
    arguments: dict[str, Any],
    *,
    action_approval_token: str,
) -> dict[str, Any]:
    """Issue a one-use confirmation for exact Tier 2 arguments after an operator action."""
    if not _NAME_RE.fullmatch(str(name or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")):
        raise GenesisToolRegistryError("Invalid Genesis artifact reference.", code="invalid_artifact_reference", status_code=400)
    if not action_approval_token:
        raise GenesisToolRegistryError("A separate per-action human approval credential is required.", code="action_approval_required", status_code=403)
    try:
        raw = json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise GenesisToolRegistryError("Tool arguments must be JSON-serializable.", code="invalid_tool_arguments", status_code=400) from None
    if not isinstance(arguments, dict) or not raw or len(raw) > _MAX_INPUT_BYTES:
        raise GenesisToolRegistryError("Tool arguments are invalid or oversized.", code="invalid_tool_arguments", status_code=400)
    path = (
        "/v1/genesis/registry/tools/" + quote(name, safe="")
        + "/" + quote(str(version), safe="")
        + "/" + quote(artifact_hash, safe="")
        + "/confirm"
    )
    return _request(
        path,
        method="POST",
        payload={"arguments": arguments},
        extra_headers={"X-Genesis-Action-Approval": action_approval_token},
        timeout=15.0,
    )


def execute_active_tool(
    name: str,
    version: str,
    artifact_hash: str,
    arguments: dict[str, Any],
    *,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """Delegate execution to Genesis; never run generated code in the Python gateway."""
    if not _NAME_RE.fullmatch(str(name or "")):
        raise GenesisToolRegistryError("Invalid Genesis tool name.", code="invalid_tool_name", status_code=400)
    if not re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")):
        raise GenesisToolRegistryError("Invalid signed artifact hash.", code="invalid_artifact_hash", status_code=400)
    if not isinstance(arguments, dict):
        raise GenesisToolRegistryError("Tool arguments must be a JSON object.", code="invalid_tool_arguments", status_code=400)
    try:
        raw = json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise GenesisToolRegistryError("Tool arguments must be JSON-serializable.", code="invalid_tool_arguments", status_code=400) from None
    if len(raw) > _MAX_INPUT_BYTES:
        raise GenesisToolRegistryError("Tool arguments exceed the size limit.", code="tool_arguments_too_large", status_code=413)

    started = time.monotonic()
    success = False
    error_class = "none"
    try:
        path = (
            "/v1/genesis/registry/tools/"
            + quote(name, safe="")
            + "/" + quote(str(version), safe="")
            + "/" + quote(artifact_hash, safe="")
            + "/invoke"
        )
        payload: dict[str, Any] = {"arguments": arguments}
        if confirmation_token:
            payload["confirmation_token"] = confirmation_token
        result = _request(path, method="POST", payload=payload)
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_RESULT_BYTES:
            raise GenesisToolRegistryError("Tool result exceeds the size limit.", code="tool_result_too_large", status_code=502)
        success = result.get("status") in {"success", "completed"}
        if not success:
            error_class = str(result.get("error_class") or "tool_execution_failed")[:80]
        return result
    except GenesisToolRegistryError as exc:
        error_class = exc.code
        raise
    finally:
        # No prompt, arguments, or result content is logged.
        logger.info(
            "genesis_tool_call tool=%s version_hash=%s success=%s latency_ms=%d error_class=%s",
            name,
            artifact_hash,
            success,
            int((time.monotonic() - started) * 1000),
            error_class,
        )
