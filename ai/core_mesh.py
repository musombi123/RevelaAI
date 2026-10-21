"""Server-side integration for USECT-ZERO, Genesis (Core-One), and Infinite Mind (Core-Two).

This module only reads status automatically. Invention and evolution operations are
explicit, authenticated proposal requests and remain subject to the cores' Guardians.
No browser receives service URLs' credentials, and no operation auto-merges code.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlencode, urlsplit

import requests

from services.core_config import core_base_url, core_admin_token
from services.usect_zero_client import is_enabled as usect_zero_is_enabled


CACHE_TTL_SECONDS = 12.0
MAX_RESPONSE_BYTES = 1_000_000
_TIMEOUT_SECONDS = 1.8

_cache_lock = threading.Lock()
_cache_value: dict | None = None
_cache_time = 0.0


class CoreMeshError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, code: str = "core_mesh_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _base_url(name: str, default: str) -> str:
    core = {
        "USECT_ZERO_BASE_URL": "zero", "USECT_ZERO_URL": "zero",
        "GENESIS_BASE_URL": "genesis", "MIND_BASE_URL": "mind",
    }.get(name)
    if not core:
        return str(os.getenv(name, default) or "").strip().rstrip("/")
    raw = core_base_url(core, default=default)
    if raw and "://" not in raw:
        candidate = urlsplit("//" + raw)
        try:
            port = candidate.port
        except ValueError:
            port = None
        if (candidate.hostname and port is not None and candidate.username is None
                and candidate.password is None and not candidate.path
                and not candidate.query and not candidate.fragment):
            raw = "http://" + raw
    return raw.rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname.strip("[]")).is_loopback
    except ValueError:
        return False


def _is_render_private_service(hostname: str) -> bool:
    # Render's private service hostport is a single DNS label plus a port.
    # Do not treat public FQDNs or non-loopback IPs as private.
    if not hostname or "." in hostname:
        return False
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        return False
    except ValueError:
        return hostname.lower() != "localhost"


def _validate_base(base: str) -> None:
    parsed = urlsplit(base)
    try:
        parsed.port
    except ValueError:
        raise CoreMeshError("Core service URL contains an invalid port.", status_code=503, code="core_service_not_configured") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CoreMeshError("Core service URL is not configured as a valid HTTP(S) origin.", status_code=503, code="core_service_not_configured")
    # Clear-text HTTP is permitted only for loopback and Render private DNS
    # service labels, never for a public hostname.
    if parsed.scheme != "https" and not (
        _is_loopback(parsed.hostname) or _is_render_private_service(parsed.hostname)
    ):
        raise CoreMeshError("Non-loopback core services must use HTTPS unless they are Render private services.", status_code=503, code="core_service_tls_required")


def _request_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> dict:
    if not base:
        raise CoreMeshError("Core service URL is not configured.", status_code=503, code="core_service_not_configured")
    _validate_base(base)
    request_headers = {"Accept": "application/json", **(headers or {})}
    try:
        response = requests.request(
            method.upper(),
            base + path,
            json=payload if payload is not None else None,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=False,
            proxies={"http": "", "https": ""},
        )
    except requests.RequestException:
        raise CoreMeshError("Core service is unreachable.", status_code=502, code="core_service_unreachable") from None

    if len(response.content or b"") > MAX_RESPONSE_BYTES:
        raise CoreMeshError("Core service returned an oversized response.", status_code=502, code="core_response_too_large")
    if 300 <= response.status_code < 400:
        raise CoreMeshError("Core service redirects are not accepted.", status_code=502, code="core_redirect_rejected")
    if not response.ok:
        status_code = response.status_code if response.status_code in {400, 401, 403, 404, 409, 422, 503} else 502
        raise CoreMeshError(
            "Core service rejected or could not complete the request.",
            status_code=status_code,
            code=f"upstream_http_{response.status_code}",
        )
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        raise CoreMeshError("Core service returned invalid JSON.", status_code=502, code="core_invalid_json") from None
    if not isinstance(data, dict):
        raise CoreMeshError("Core service returned an unexpected JSON shape.", status_code=502, code="core_invalid_payload")
    return data


def _safe_fetch(base: str, path: str, *, headers: dict[str, str] | None = None) -> dict:
    try:
        return _request_json(base, path, headers=headers)
    except CoreMeshError as exc:
        return {"status": "unavailable", "reachable": False, "reason": exc.code}


def _upstream_headers(*, include_genesis: bool = False, mutation: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if include_genesis:
        token = core_admin_token("genesis")
        if token:
            headers["X-Genesis-Token"] = token
    if mutation:
        token = core_admin_token("mind")
        if not token:
            raise CoreMeshError("MIND_ADMIN_TOKEN is not configured on the RevelaAI service.", status_code=503, code="mind_admin_token_not_configured")
        headers["X-Mind-Token"] = token
    return headers


def _is_online(data: dict) -> bool:
    status = str(data.get("status") or "").strip().lower()
    return data.get("reachable") is True or status in {"ok", "success", "healthy", "online"}


def _public_evolution(item: dict) -> dict:
    keys = (
        "version", "tool_name", "status", "selected_mutation",
        "mutation_batch", "created_at", "selection_reason", "await_merge_path",
    )
    return {key: item[key] for key in keys if key in item}


def _dashboard_snapshot() -> dict:
    zero_base = _base_url("USECT_ZERO_BASE_URL", "http://127.0.0.1:8780")
    one_base = _base_url("GENESIS_BASE_URL", "")
    mind_base = _base_url("MIND_BASE_URL", "http://127.0.0.1:8782")
    genesis_headers = _upstream_headers(include_genesis=True)

    # All probes are read-only. Mind's proxy is the shared path for detailed
    # Core-One/Core-Zero state where the daemons are deployed separately.
    jobs = {
        "zero_health": (zero_base, "/v1/health", None),
        "zero_detail": (mind_base, "/v1/zero/status", None),
        "one_health": (one_base, "/v1/genesis/health", None),
        "one_status": (one_base, "/v1/genesis/status", genesis_headers),
        "one_tools": (one_base, "/v1/genesis/tools", genesis_headers),
        "one_registry": (one_base, "/v1/genesis/registry/tools", genesis_headers),
        "two_health": (mind_base, "/v1/mind/health", None),
        "two_metrics": (mind_base, "/v1/mind/metrics", None),
        "two_evolutions": (mind_base, "/v1/mind/evolutions", None),
        "two_learning": (mind_base, "/v1/mind/learning", None),
    }
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {
            key: pool.submit(_safe_fetch, base, path, headers=headers)
            for key, (base, path, headers) in jobs.items()
        }
        for key, future in futures.items():
            try:
                results[key] = future.result(timeout=_TIMEOUT_SECONDS + 1.0)
            except Exception:
                results[key] = {"status": "unavailable", "reachable": False, "reason": "probe_failed"}

    zero_health = results["zero_health"]
    zero_detail = results["zero_detail"]
    one_health = results["one_health"]
    one_status = results["one_status"]
    one_tools = results["one_tools"]
    one_registry = results["one_registry"]
    two_health = results["two_health"]
    two_metrics = results["two_metrics"]
    two_evolutions = results["two_evolutions"]
    two_learning = results["two_learning"]

    zero_online = _is_online(zero_health)
    one_online = _is_online(one_health) and _is_online(one_status)
    two_online = _is_online(two_health)
    # The registry list endpoint returns {tools, count} without a status field.
    registry_tools = one_registry.get("tools") if isinstance(one_registry.get("tools"), list) else []
    registry_ready = "reason" not in one_registry and isinstance(one_registry.get("tools"), list)
    active_signed_tools_count = sum(
        1 for item in registry_tools if isinstance(item, dict) and item.get("active") is True
    )

    guardian = one_status.get("guardian") if isinstance(one_status.get("guardian"), dict) else {}
    queue = one_status.get("queue") if isinstance(one_status.get("queue"), dict) else {}
    evolution_items = two_evolutions.get("evolutions") if isinstance(two_evolutions.get("evolutions"), list) else []
    if not evolution_items and isinstance(two_metrics.get("evolutions"), list):
        evolution_items = two_metrics["evolutions"]
    public_evolutions = [_public_evolution(item) for item in evolution_items if isinstance(item, dict)][:8]

    learning_count = 0
    for key in ("feedback_count", "count", "entries_count", "total"):
        value = two_learning.get(key)
        if isinstance(value, int) and value >= 0:
            learning_count = value
            break
    if not learning_count:
        entries = two_learning.get("entries")
        if isinstance(entries, list):
            learning_count = len(entries)

    return {
        "status": "online" if zero_online and one_online and two_online else "degraded",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "model_free_core_two": bool(two_health.get("model_free", False)),
            "human_approval_required": True,
            "automatic_merge": False,
            "generated_code_auto_execution": False,
        },
        "cores": {
            "zero": {
                "id": "USECT-ZERO",
                "name": "USECT-ZERO",
                "role": "Body · diagnostics and guarded recovery",
                "status": "online" if zero_online else "unavailable",
                "reachable": zero_online,
                "version": zero_health.get("version"),
                "model_free": zero_health.get("model_free", True),
                "offline_mode": zero_health.get("offline_mode"),
                "execution_policy": zero_health.get("execution_policy", "human-gated"),
                "audit_log_observed": zero_detail.get("audit_log_observed"),
                "healing_evidence_observed": zero_detail.get("healing_evidence_observed"),
                "failure_reason": None if zero_online else str(zero_health.get("reason") or "usect_zero_unavailable")[:80],
            },
            "one": {
                "id": "USECT-ONE",
                "name": "Genesis",
                "role": "Womb · guarded invention proposals",
                "status": "online" if one_online else "unavailable",
                "reachable": one_online,
                "reason": None if one_online else "genesis_unavailable",
                "version": one_health.get("version") or one_status.get("version"),
                "standalone": one_health.get("standalone", one_status.get("standalone")),
                "model_assisted": one_health.get("model_assisted", one_status.get("model_assisted")),
                "execution_policy": one_health.get("execution", one_status.get("execution")),
                "merge_policy": one_health.get("merge", one_status.get("merge")),
                "guardian_ready": guardian.get("ready"),
                "queue": {str(k): v for k, v in queue.items() if isinstance(v, (int, float))},
                "invention_count": one_status.get("invention_count", one_tools.get("count")),
                "signed_tool_registry_ready": registry_ready,
                "active_signed_tools_count": active_signed_tools_count,
                "failure_reason": None if one_online else str(one_health.get("reason") or one_status.get("reason") or "genesis_unavailable")[:80],
                "automatic_merge": False,
            },
            "two": {
                "id": "USECT-TWO",
                "name": "Infinite Mind",
                "role": "Mind · observe, rank and propose improvements",
                "status": "online" if two_online else "unavailable",
                "availability": "available" if two_online else "mind_unavailable",
                "reachable": two_online,
                "reason": None if two_online else "mind_unavailable",
                "availability_message": None if two_online else "Infinite Mind is unavailable; RevelaAI chat and the other cores remain available.",
                "version": two_health.get("version"),
                "model_free": two_health.get("model_free", True),
                "integration_available": isinstance(two_health.get("integration"), dict),
                "mirror_observed": isinstance(two_health.get("mirror"), dict),
                "metrics_available": _is_online(two_metrics),
                "learning_feedback_count": learning_count,
                "evolution_count": two_evolutions.get("count", len(public_evolutions)),
                "failure_reason": None if two_online else str(two_health.get("reason") or "mind_unavailable")[:80],
                "automatic_merge": False,
            },
        },
        "recent_evolutions": public_evolutions,
        "learning": {
            "status": two_learning.get("status", "available" if two_online else "unavailable"),
            "feedback_count": learning_count,
        },
        "configuration": {
            "zero_url_configured": bool(os.getenv("USECT_ZERO_URL") or os.getenv("USECT_ZERO_BASE_URL")),
            "zero_admin_token_configured": bool(core_admin_token("zero")),
            "zero_enabled": usect_zero_is_enabled(),
            "zero_brain_key_configured": bool(os.getenv("USECT_ZERO_BRAIN_API_KEY", "").strip()),
            "zero_tools_ready": bool(
                usect_zero_is_enabled()
                and (os.getenv("USECT_ZERO_URL") or os.getenv("USECT_ZERO_BASE_URL"))
                and core_admin_token("zero")
                and os.getenv("USECT_ZERO_BRAIN_API_KEY", "").strip()
            ),
            "genesis_url_configured": bool(os.getenv("GENESIS_BASE_URL")),
            "genesis_proxy_credential_configured": bool(os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")),
            "genesis_orchestrator_tools_enabled": os.getenv("GENESIS_ORCHESTRATOR_TOOLS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
            "genesis_signing_key_configured": one_health.get("signing_key_configured"),
            "genesis_registry_ready": registry_ready,
            "active_signed_tools_count": active_signed_tools_count,
            "mind_url_configured": bool(os.getenv("MIND_BASE_URL")),
            "write_credentials_configured": bool(core_admin_token("mind")),
            "core_mesh_operator_allowlist_configured": bool((os.getenv("CORE_MESH_ADMIN_USER_IDS") or os.getenv("META_ENGINEER_ADMIN_USER_IDS") or "").strip()),
        },
    }


def get_core_mesh_dashboard(*, force_refresh: bool = False) -> dict:
    """Return a short-lived cached, credential-free status snapshot."""
    global _cache_value, _cache_time
    now = time.monotonic()
    with _cache_lock:
        if not force_refresh and _cache_value is not None and now - _cache_time < CACHE_TTL_SECONDS:
            return deepcopy(_cache_value)
    value = _dashboard_snapshot()
    with _cache_lock:
        _cache_value = value
        _cache_time = time.monotonic()
    return deepcopy(value)


def _public_proposal(payload: dict) -> dict:
    keys = (
        "status", "id", "name", "title", "version", "tool_name",
        "selected_mutation", "mutation_batch", "candidate_count",
        "await_merge_path", "created_at",
    )
    result = {key: payload[key] for key in keys if key in payload}
    result["human_approval_required"] = True
    result["automatic_merge"] = False
    result["automatic_execution"] = False
    return result


def propose_genesis_invention(demand: str, country: str = "KE", language: str = "") -> dict:
    demand = str(demand or "").strip()
    if not 3 <= len(demand) <= 500:
        raise CoreMeshError("Demand must contain between 3 and 500 characters.", status_code=400, code="invalid_invention_demand")
    if not (os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")):
        raise CoreMeshError("GENESIS_ADMIN_TOKEN is not configured on the RevelaAI service.", status_code=503, code="genesis_admin_token_not_configured")
    genesis_base = _base_url("GENESIS_BASE_URL", "")
    try:
        payload = _request_json(
            genesis_base,
            "/v1/genesis/invent",
            method="POST",
            payload={"demand": demand, "country": str(country or "KE")[:80], "language": str(language or "")[:20]},
            headers=_upstream_headers(include_genesis=True),
            timeout=40.0,
        )
    except CoreMeshError as exc:
        if exc.code in {
            "core_service_not_configured",
            "core_service_unreachable",
            "core_service_tls_required",
            "core_redirect_rejected",
            "upstream_http_503",
        }:
            raise CoreMeshError(
                "Genesis is unavailable. Your normal RevelaAI chat remains available; retry the invention request later.",
                status_code=503,
                code="genesis_unavailable",
            ) from None
        raise
    return _public_proposal(payload)


def _genesis_request(path: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 8.0) -> dict:
    """Call Genesis with server-only credentials and a consistent unavailable error."""
    if not (os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")):
        raise CoreMeshError(
            "Genesis is unavailable because the server-to-server credential is not configured.",
            status_code=503,
            code="genesis_unavailable",
        )
    base = _base_url("GENESIS_BASE_URL", "")
    try:
        return _request_json(
            base,
            path,
            method=method,
            payload=payload,
            headers=_upstream_headers(include_genesis=True),
            timeout=timeout,
        )
    except CoreMeshError as exc:
        if exc.code in {
            "core_service_not_configured",
            "core_service_unreachable",
            "core_service_tls_required",
            "core_redirect_rejected",
            "upstream_http_503",
            "upstream_http_502",
            "upstream_http_504",
        }:
            raise CoreMeshError(
                "Genesis is unavailable. Normal RevelaAI chat remains available; retry this Genesis operation later.",
                status_code=503,
                code="genesis_unavailable",
            ) from None
        raise


def get_genesis_status() -> dict:
    return _genesis_request("/v1/genesis/status")


def list_genesis_proposals() -> dict:
    return _genesis_request("/v1/genesis/tools")


def get_genesis_proposal(name: str) -> dict:
    """Return a sanitized proposal summary, never raw saved research or source material."""
    name = str(name or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", name):
        raise CoreMeshError("Genesis tool name is invalid.", status_code=400, code="invalid_tool_name")
    payload = _genesis_request("/v1/genesis/tools/" + quote(name, safe=""))
    return _public_genesis_detail(payload)


def _public_genesis_detail(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise CoreMeshError("Genesis returned an invalid proposal response.", status_code=502, code="genesis_invalid_payload")
    result = {
        key: payload[key]
        for key in ("name", "status", "hardware_guide_url")
        if isinstance(payload.get(key), (str, int, float, bool))
    }
    raw_proposal = payload.get("proposal")
    if not isinstance(raw_proposal, dict):
        # Keep only the minimal safe metadata if Genesis returns a legacy shape.
        return result
    safe_proposal: dict[str, object] = {}
    for key in ("invention_id", "created_at", "status", "schema_version"):
        value = raw_proposal.get(key)
        if isinstance(value, (str, int, float, bool)):
            safe_proposal[key] = value
    raw_spec = raw_proposal.get("specification")
    if isinstance(raw_spec, dict):
        spec_keys = (
            "name", "title", "purpose", "category", "industry",
            "capabilities", "inputs", "outputs", "safeguards",
            "needs_hardware_guide", "model_assisted", "model_note",
        )
        safe_spec: dict[str, object] = {}
        for key in spec_keys:
            value = raw_spec.get(key)
            if isinstance(value, (str, int, float, bool)):
                safe_spec[key] = value
            elif isinstance(value, list) and len(value) <= 32 and all(isinstance(item, str) for item in value):
                safe_spec[key] = value[:32]
        safe_proposal["specification"] = safe_spec
    raw_research = raw_proposal.get("research")
    if isinstance(raw_research, dict):
        sources = raw_research.get("sources")
        findings = raw_research.get("findings")
        safe_proposal["research_summary"] = {
            "mode": str(raw_research.get("mode") or "")[:80],
            "collected_at": str(raw_research.get("collected_at") or "")[:80],
            "source_count": len(sources) if isinstance(sources, list) else 0,
            "finding_count": len(findings) if isinstance(findings, list) else 0,
        }
    result["proposal"] = safe_proposal
    result["human_approval_required"] = True
    result["automatic_execution"] = False
    result["automatic_merge"] = False
    return result


def get_genesis_hardware_guide(name: str, country: str = "KE", language: str = "") -> dict:
    name = str(name or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", name):
        raise CoreMeshError("Genesis tool name is invalid.", status_code=400, code="invalid_tool_name")
    query = urlencode({"country": str(country or "KE")[:3], "lang": str(language or "")[:20]})
    return _genesis_request(
        "/v1/genesis/tools/" + quote(name, safe="") + "/hardware_guide?" + query
    )


def get_genesis_capability_plan(name: str) -> dict:
    name = str(name or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", name):
        raise CoreMeshError("Genesis tool name is invalid.", status_code=400, code="invalid_tool_name")
    return _genesis_request(
        "/v1/genesis/tools/" + quote(name, safe="") + "/capability_plan"
    )


def queue_genesis_demand(
    demand: str,
    *,
    source: str = "revelaai-gateway",
    country: str = "KE",
    language: str = "",
) -> dict:
    demand = str(demand or "").strip()
    if not 1 <= len(demand) <= 3999:
        raise CoreMeshError("Demand must contain between 1 and 3999 characters.", status_code=400, code="invalid_invention_demand")
    payload = {
        "demand": demand,
        "source": str(source or "revelaai-gateway")[:100],
        "country": str(country or "KE")[:3],
        "language": str(language or "")[:20],
    }
    return _genesis_request("/v1/genesis/queue", method="POST", payload=payload, timeout=12.0)


def get_genesis_key_request_info() -> dict:
    return _genesis_request("/v1/genesis/key")


def request_genesis_provider_key(client_id: str, reason: str) -> dict:
    client_id = str(client_id or "").strip()
    reason = str(reason or "").strip()
    if not client_id or len(client_id) > 120 or not reason or len(reason) > 500:
        raise CoreMeshError(
            "client_id and reason are required within their size limits.",
            status_code=400,
            code="invalid_provider_key_request",
        )
    return _genesis_request(
        "/v1/genesis/key",
        method="POST",
        payload={"client_id": client_id, "reason": reason},
        timeout=12.0,
    )


def compile_genesis_rvx(source: str) -> dict:
    source = str(source or "")
    if not source.strip() or len(source.encode("utf-8")) > 16384:
        raise CoreMeshError("RVX source must contain 1 to 16384 UTF-8 bytes.", status_code=400, code="invalid_rvx_source")
    return _genesis_request(
        "/v1/rvx/compile",
        method="POST",
        payload={"source": source},
        timeout=12.0,
    )


def iter_genesis_events(*, max_events: int = 100):
    """Yield bounded SSE event objects from Genesis; callers control reconnects."""
    if not (os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")):
        raise CoreMeshError(
            "Genesis is unavailable because the server-to-server credential is not configured.",
            status_code=503,
            code="genesis_unavailable",
        )
    if not 1 <= int(max_events) <= 500:
        raise CoreMeshError("max_events must be between 1 and 500.", status_code=400, code="invalid_event_limit")
    base = _base_url("GENESIS_BASE_URL", "")
    _validate_base(base)
    url = base + "/v1/genesis/stream"
    try:
        with requests.get(
            url,
            headers={**_upstream_headers(include_genesis=True), "Accept": "text/event-stream"},
            timeout=(3.0, 25.0),
            allow_redirects=False,
            stream=True,
            proxies={"http": "", "https": ""},
        ) as response:
            if response.status_code in {401, 403}:
                raise CoreMeshError("Genesis rejected the server credential.", status_code=response.status_code, code="genesis_auth_rejected")
            if not response.ok:
                raise CoreMeshError(
                    "Genesis is unavailable. Normal RevelaAI chat remains available.",
                    status_code=503,
                    code="genesis_unavailable",
                )
            event_name = "message"
            data_lines: list[str] = []
            yielded = 0
            # Requests may yield bytes for event-stream responses that do
            # not declare a charset. Decode explicitly to avoid bytes/str
            # comparison errors on the first SSE line.
            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace")
                else:
                    line = str(raw_line or "")
                if len(line) > MAX_RESPONSE_BYTES:
                    raise CoreMeshError("Genesis event line is oversized.", status_code=502, code="genesis_response_too_large")
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()[:80] or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif not line:
                    if data_lines:
                        data_raw = "\n".join(data_lines)
                        try:
                            event = json.loads(data_raw)
                        except ValueError:
                            event = {"type": event_name, "data": data_raw[:4000]}
                        if isinstance(event, dict):
                            event.setdefault("type", event_name)
                            yield event
                            yielded += 1
                            if yielded >= max_events:
                                return
                    event_name = "message"
                    data_lines = []
    except CoreMeshError:
        raise
    except requests.RequestException:
        raise CoreMeshError(
            "Genesis event stream is unavailable. Normal RevelaAI chat remains available.",
            status_code=503,
            code="genesis_unavailable",
        ) from None


def propose_mind_evolution(objective: str, tool_name: str) -> dict:
    objective = str(objective or "").strip()
    tool_name = str(tool_name or "offline_vault_fixture").strip().lower()
    if not 3 <= len(objective) <= 500:
        raise CoreMeshError("Objective must contain between 3 and 500 characters.", status_code=400, code="invalid_evolution_objective")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", tool_name):
        raise CoreMeshError("Tool name must use lowercase letters, digits, underscores or hyphens.", status_code=400, code="invalid_tool_name")
    mind_base = _base_url("MIND_BASE_URL", "http://127.0.0.1:8782")
    payload = _request_json(
        mind_base,
        "/v1/mind/evolve",
        method="POST",
        payload={"objective": objective, "tool_name": tool_name},
        headers=_upstream_headers(mutation=True),
        timeout=40.0,
    )
    result = _public_proposal(payload)
    result.update({
        "target_core": "core-one",
        "operation_kind": "core_one_improvement_proposal",
        "target_modified": False,
        "human_approval_required": True,
        "automatic_merge": False,
        "automatic_execution": False,
    })
    return result


# Only immutable candidate metadata crosses this bridge. Source files and prompts
# are rejected before forwarding to Infinite Mind.
_MIND_CANDIDATE_FIELDS = frozenset({
    "candidate_id",
    "source_core",
    "tool_name",
    "objective",
    "baseline_version_hash",
    "candidate_version_hash",
    "source_sha256",
    "risk_tier",
    "sandbox_tested",
    "sandbox_evidence_ref",
})
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
_MIND_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_MIND_EVIDENCE_RE = re.compile(r"[A-Za-z0-9._:/#-]{1,500}\Z")


def score_mind_foundry_candidate(candidate: dict) -> dict:
    """Ask Mind to score a Core-One Foundry candidate without sending its source."""
    if not isinstance(candidate, dict):
        raise CoreMeshError("Candidate must be a JSON object.", status_code=400, code="invalid_mind_candidate")
    if set(candidate) != _MIND_CANDIDATE_FIELDS:
        raise CoreMeshError(
            "Candidate must contain exactly the declared metadata fields; source code and extra fields are not accepted.",
            status_code=400,
            code="invalid_mind_candidate",
        )

    text_limits = {
        "candidate_id": 64,
        "source_core": 64,
        "tool_name": 64,
        "objective": 500,
        "baseline_version_hash": 64,
        "candidate_version_hash": 64,
        "source_sha256": 64,
        "sandbox_evidence_ref": 500,
    }
    for field, limit in text_limits.items():
        value = candidate.get(field)
        if not isinstance(value, str) or not value or len(value) > limit or value != value.strip():
            raise CoreMeshError(
                f"Candidate field {field} is invalid.",
                status_code=400,
                code="invalid_mind_candidate",
            )
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise CoreMeshError(
                f"Candidate field {field} contains control characters.",
                status_code=400,
                code="invalid_mind_candidate",
            )

    if candidate["source_core"] != "core-one-foundry":
        raise CoreMeshError("Only Core-One Foundry candidates may be scored.", status_code=400, code="invalid_mind_candidate")
    if not _MIND_NAME_RE.fullmatch(candidate["candidate_id"]) or not _MIND_NAME_RE.fullmatch(candidate["tool_name"]):
        raise CoreMeshError("Candidate ID or tool name is invalid.", status_code=400, code="invalid_mind_candidate")
    if not 3 <= len(candidate["objective"]) <= 500:
        raise CoreMeshError("Objective must contain 3–500 characters.", status_code=400, code="invalid_mind_candidate")
    for field in ("baseline_version_hash", "candidate_version_hash", "source_sha256"):
        if not _SHA256_HEX_RE.fullmatch(candidate[field]):
            raise CoreMeshError(f"{field} must be lowercase SHA-256 hex.", status_code=400, code="invalid_mind_candidate")
    if candidate["baseline_version_hash"] == candidate["candidate_version_hash"]:
        raise CoreMeshError("Baseline and candidate version hashes must differ.", status_code=400, code="invalid_mind_candidate")
    if type(candidate["risk_tier"]) is not int or candidate["risk_tier"] not in (1, 2):
        raise CoreMeshError("Risk tier must be 1 or 2.", status_code=400, code="invalid_mind_candidate")
    if candidate["sandbox_tested"] is not True:
        raise CoreMeshError("The candidate must already pass Core-One Foundry sandbox tests.", status_code=422, code="mind_candidate_not_sandbox_tested")

    evidence_ref = candidate["sandbox_evidence_ref"]
    if "://" in evidence_ref:
        parsed = urlsplit(evidence_ref)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise CoreMeshError("Evidence URI must use HTTPS without credentials, query, or fragment.", status_code=400, code="invalid_mind_candidate")
    elif not _MIND_EVIDENCE_RE.fullmatch(evidence_ref):
        raise CoreMeshError("Evidence reference contains unsupported characters.", status_code=400, code="invalid_mind_candidate")

    mind_base = _base_url("MIND_BASE_URL", "http://127.0.0.1:8782")
    payload = _request_json(
        mind_base,
        "/v1/mind/candidates",
        method="POST",
        payload=dict(candidate),
        headers=_upstream_headers(mutation=True),
        timeout=25.0,
    )
    allowed_result_keys = (
        "status", "candidate_id", "tool_name", "candidate_version_hash",
        "source_sha256", "guardian_passed", "core_one_guardian_passed",
        "scored", "score", "ranking_context_score", "canary",
        "evidence_recorded_at", "evidence_path", "synthetic_fixture",
        "production_verified",
    )
    result = {key: payload[key] for key in allowed_result_keys if key in payload}
    result.update({
        "target_core": "core-one",
        "assessment_only": True,
        "human_approval_required": True,
        "automatic_merge": False,
        "promotion_executed": False,
        "rollback_executed": False,
    })
    return result


def core_mesh_operator_allowed(user_id: str) -> bool:
    """Use the same explicit operator allowlist for chat dispatch and HTTP routes."""
    configured = os.getenv("CORE_MESH_ADMIN_USER_IDS", "") or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    allowed = {value.strip() for value in configured.split(",") if value.strip()}
    normalized_user_id = str(user_id or "").strip()
    return bool(normalized_user_id and normalized_user_id in allowed)


def get_cached_core_mesh_dashboard() -> dict:
    """Return the last read-only snapshot without adding network latency to chat."""
    with _cache_lock:
        if _cache_value is not None:
            return deepcopy(_cache_value)
    return {
        "status": "not_probed",
        "cores": {
            "zero": {"id": "USECT-ZERO", "status": "not_probed", "reachable": None, "version": None},
            "one": {"id": "USECT-ONE", "status": "not_probed", "reachable": None, "version": None},
            "two": {"id": "USECT-TWO", "status": "not_probed", "reachable": None, "version": None},
        },
    }


def orchestrator_core_context(message: str, domain: str = "general", intent: str = "general") -> dict:
    """Return advisory routing and public status; never execute a mutation."""
    text = str(message or "").strip().lower()
    selected = "orchestrator"
    reason = "The existing RevelaAI orchestrator retains normal domain and provider routing."
    if re.search(r"\b(invent|build|create|design|develop|generate)\b.{0,100}\b(tool|module|software|system|engine|plugin|capability)\b", text) or re.search(r"\b(make|create|invent)\s+(me\s+)?(a|an)\s+(tool|module|engine|plugin)\b", text):
        selected = "core-one"
        reason = "A tool/invention request can be proposed through Genesis after explicit operator action."
    elif (
        re.search(r"\b(evolve|improve|improvement|benchmark|upgrade|optimise|optimize|enhance|harden|refine)\b", text)
        and re.search(r"\b(core(?:[- ]?one|[- ]?two|[- ]?zero)?|genesis|tool|system|performance|architecture|engine|mutation|foundry)\b", text)
    ):
        selected = "core-two"
        reason = (
            "Infinite Mind evaluates evidence-backed improvements for Core-One/Genesis; "
            "it stages a proposal for human review and never edits or merges Core-One."
        )
    elif re.search(r"\b(diagnose|diagnostics|health check|audit|recover|repair)\b", text) and re.search(r"\b(core|repository|system|service|daemon|platform)\b", text):
        selected = "core-zero"
        reason = "A diagnostic/recovery request maps to ZERO's read-only checks or human-gated recovery proposals."

    # Ordinary domain chat is not a mesh operation. Do not attach stale degraded
    # mesh status to it, and avoid health-probe fan-out on every conversation turn.
    asks_about_mesh = bool(re.search(r"\b(core[- ]?mesh|usect|genesis|infinite mind|core[- ]?(zero|one|two))\b", text))
    mesh_relevant = selected != "orchestrator" or asks_about_mesh
    if mesh_relevant:
        dashboard = get_core_mesh_dashboard()
    else:
        dashboard = {
            # The mesh is not applicable to this turn; no health probe ran.
            # Keep mesh_status not_probed so clients do not show a false outage.
            "status": "not_probed",
            "cores": {
                "zero": {"id": "USECT-ZERO", "status": "not_probed", "reachable": None, "version": None},
                "one": {"id": "USECT-ONE", "status": "not_probed", "reachable": None, "version": None},
                "two": {"id": "USECT-TWO", "status": "not_probed", "reachable": None, "version": None},
            },
        }
    cores = dashboard.get("cores", {})
    target_core = {
        "core-one": "core-one",
        "core-two": "core-one",
        "core-zero": "core-zero",
    }.get(selected)
    operation_kind = {
        "core-one": "invention_proposal",
        "core-two": "core_one_improvement_proposal",
        "core-zero": "diagnostics_advisory",
        "orchestrator": "normal_chat",
    }.get(selected, "advisory_only")

    return {
        "mode": "advisory_only" if mesh_relevant else "not_applicable",
        "selected_core": selected,
        "target_core": target_core,
        "operation_kind": operation_kind,
        "route_reason": reason,
        "domain": str(domain or "general"),
        "intent": str(intent or "general"),
        "mesh_status": dashboard.get("status", "unknown"),
        "cores": {
            name: {
                "id": core.get("id"),
                "status": core.get("status", "unknown"),
                "reachable": core.get("reachable"),
                "version": core.get("version"),
            }
            for name, core in cores.items()
        },
        "safety": {
            "operation_executed": False,
            "target_mutation_performed": False,
            "candidate_source_execution": False,
            "human_approval_required": True,
            "automatic_merge": False,
            "automatic_execution": False,
        },
    }
