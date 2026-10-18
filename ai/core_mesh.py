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
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests


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
    return str(os.getenv(name, default) or "").strip().rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname.strip("[]")).is_loopback
    except ValueError:
        return False


def _validate_base(base: str) -> None:
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CoreMeshError("Core service URL is not configured as a valid HTTP(S) origin.", status_code=503, code="core_service_not_configured")
    # Never send service credentials to clear-text, non-loopback hosts.
    if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
        raise CoreMeshError("Non-loopback core services must use HTTPS.", status_code=503, code="core_service_tls_required")


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
        token = str(os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN") or "").strip()
        if token:
            headers["X-Genesis-Token"] = token
    if mutation:
        token = str(os.getenv("MIND_ADMIN_TOKEN") or "").strip()
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
    one_base = _base_url("GENESIS_BASE_URL", "http://127.0.0.1:8781")
    mind_base = _base_url("MIND_BASE_URL", "http://127.0.0.1:8782")
    genesis_headers = _upstream_headers(include_genesis=True)

    # All probes are read-only. Mind's proxy is the shared path for detailed
    # Core-One/Core-Zero state where the daemons are deployed separately.
    jobs = {
        "zero_health": (zero_base, "/v1/health", None),
        "zero_detail": (mind_base, "/v1/zero/status", None),
        "one_health": (one_base, "/v1/genesis/health", None),
        "one_status": (mind_base, "/v1/genesis/status", genesis_headers),
        "one_tools": (mind_base, "/v1/genesis/tools", genesis_headers),
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
    two_health = results["two_health"]
    two_metrics = results["two_metrics"]
    two_evolutions = results["two_evolutions"]
    two_learning = results["two_learning"]

    zero_online = _is_online(zero_health)
    one_online = _is_online(one_health)
    two_online = _is_online(two_health)

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
            },
            "one": {
                "id": "USECT-ONE",
                "name": "Genesis",
                "role": "Womb · guarded invention proposals",
                "status": "online" if one_online else "unavailable",
                "reachable": one_online,
                "version": one_health.get("version") or one_status.get("version"),
                "standalone": one_health.get("standalone", one_status.get("standalone")),
                "model_assisted": one_health.get("model_assisted", one_status.get("model_assisted")),
                "guardian_ready": guardian.get("ready"),
                "queue": {str(k): v for k, v in queue.items() if isinstance(v, (int, float))},
                "invention_count": one_status.get("invention_count", one_tools.get("count")),
                "automatic_merge": False,
            },
            "two": {
                "id": "USECT-TWO",
                "name": "Infinite Mind",
                "role": "Mind · observe, rank and propose improvements",
                "status": "online" if two_online else "unavailable",
                "reachable": two_online,
                "version": two_health.get("version"),
                "model_free": two_health.get("model_free", True),
                "integration_available": isinstance(two_health.get("integration"), dict),
                "mirror_observed": isinstance(two_health.get("mirror"), dict),
                "metrics_available": _is_online(two_metrics),
                "learning_feedback_count": learning_count,
                "evolution_count": two_evolutions.get("count", len(public_evolutions)),
                "automatic_merge": False,
            },
        },
        "recent_evolutions": public_evolutions,
        "learning": {
            "status": two_learning.get("status", "available" if two_online else "unavailable"),
            "feedback_count": learning_count,
        },
        "configuration": {
            "zero_url_configured": bool(os.getenv("USECT_ZERO_BASE_URL")),
            "genesis_url_configured": bool(os.getenv("GENESIS_BASE_URL")),
            "mind_url_configured": bool(os.getenv("MIND_BASE_URL")),
            "write_credentials_configured": bool(os.getenv("MIND_ADMIN_TOKEN")),
            "genesis_proxy_credential_configured": bool(os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")),
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


def propose_genesis_invention(demand: str) -> dict:
    demand = str(demand or "").strip()
    if not 3 <= len(demand) <= 500:
        raise CoreMeshError("Demand must contain between 3 and 500 characters.", status_code=400, code="invalid_invention_demand")
    mind_base = _base_url("MIND_BASE_URL", "http://127.0.0.1:8782")
    if not (os.getenv("GENESIS_ADMIN_TOKEN") or os.getenv("GENESIS_TOKEN")):
        raise CoreMeshError("GENESIS_ADMIN_TOKEN is not configured on the RevelaAI service.", status_code=503, code="genesis_admin_token_not_configured")
    payload = _request_json(
        mind_base,
        "/v1/genesis/invent",
        method="POST",
        payload={"demand": demand},
        headers=_upstream_headers(include_genesis=True, mutation=True),
        timeout=40.0,
    )
    return _public_proposal(payload)


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
    return _public_proposal(payload)


def orchestrator_core_context(message: str, domain: str = "general", intent: str = "general") -> dict:
    """Return advisory routing and public core health; never execute a mutation."""
    text = str(message or "").strip().lower()
    selected = "orchestrator"
    reason = "The existing RevelaAI orchestrator retains normal domain and provider routing."
    if re.search(r"\b(invent|build|create|design|develop|generate)\b.{0,100}\b(tool|module|software|system|engine|plugin|capability)\b", text) or re.search(r"\b(make|create|invent)\s+(me\s+)?(a|an)\s+(tool|module|engine|plugin)\b", text):
        selected = "core-one"
        reason = "A tool/invention request can be proposed through Genesis after explicit operator action."
    elif re.search(r"\b(evolve|optimise|optimize|improve|benchmark|upgrade)\b", text) and re.search(r"\b(core|tool|system|performance|architecture|engine|mutation)\b", text):
        selected = "core-two"
        reason = "An improvement request can be evaluated by Infinite Mind as a guarded proposal after explicit operator action."
    elif re.search(r"\b(diagnose|diagnostics|health check|audit|recover|repair)\b", text) and re.search(r"\b(core|repository|system|service|daemon|platform)\b", text):
        selected = "core-zero"
        reason = "A diagnostic/recovery request maps to ZERO's read-only checks or human-gated recovery proposals."

    dashboard = get_core_mesh_dashboard()
    cores = dashboard.get("cores", {})
    return {
        "mode": "advisory_only",
        "selected_core": selected,
        "route_reason": reason,
        "domain": str(domain or "general"),
        "intent": str(intent or "general"),
        "cores": {
            name: {
                "id": core.get("id"),
                "status": core.get("status", "unknown"),
                "reachable": bool(core.get("reachable")),
                "version": core.get("version"),
            }
            for name, core in cores.items()
        },
        "safety": {
            "operation_executed": False,
            "human_approval_required": True,
            "automatic_merge": False,
            "automatic_execution": False,
        },
    }
