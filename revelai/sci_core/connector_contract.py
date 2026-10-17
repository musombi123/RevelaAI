"""Vendor-neutral connector contract and safe simulation registry.

This module provides no live hardware actuator. Real adapters must be reviewed,
explicitly allowlisted, least-privileged, and separately authorized.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

CONNECTOR_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ALLOWED_TYPES = {"api", "hardware_simulator"}
ALLOWED_CAPABILITIES = {"health_check", "read_telemetry", "read_events", "simulate_action", "device_status"}
ALLOWED_PERMISSIONS = {"read_health", "read_telemetry", "read_events", "simulate_action", "actuate"}
ALLOWED_AUTH_SCHEMES = {"none", "bearer_env", "mtls", "device_token_env"}
ALLOWED_ACTION_MODES = {"disabled", "simulation_only", "approval_gated"}


class ConnectorError(RuntimeError):
    """Base connector contract error."""


class ConnectorTimeout(ConnectorError):
    """A connector operation exceeded its declared timeout."""


class ConnectorTransientError(ConnectorError):
    """A bounded, retryable read operation failed transiently."""


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    connector_type: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    target_scope: str
    version: str = "1.0"
    auth_scheme: str = "none"
    healthcheck_timeout_seconds: float = 2.0
    request_timeout_seconds: float = 3.0
    supports_idempotency: bool = False
    action_mode: str = "disabled"
    action_ids: tuple[str, ...] = ()
    approved_device_ids: tuple[str, ...] = ()
    human_approval_required: bool = True


def validate_manifest(manifest: ConnectorManifest) -> dict[str, Any]:
    if not isinstance(manifest, ConnectorManifest):
        raise ValueError("manifest must be a ConnectorManifest")
    if not CONNECTOR_ID.fullmatch(manifest.connector_id):
        raise ValueError("invalid connector_id")
    if manifest.connector_type not in ALLOWED_TYPES:
        raise ValueError("unsupported connector_type")
    if not manifest.target_scope or len(manifest.target_scope) > 120:
        raise ValueError("target_scope must be a bounded non-empty scope")
    if not manifest.capabilities or set(manifest.capabilities) - ALLOWED_CAPABILITIES:
        raise ValueError("manifest declares an unsupported capability")
    if set(manifest.permissions) - ALLOWED_PERMISSIONS:
        raise ValueError("manifest declares an unsupported permission")
    if manifest.auth_scheme not in ALLOWED_AUTH_SCHEMES:
        raise ValueError("unsupported auth_scheme")
    if manifest.action_mode not in ALLOWED_ACTION_MODES:
        raise ValueError("unsupported action_mode")
    if not (0.05 <= manifest.healthcheck_timeout_seconds <= 30):
        raise ValueError("healthcheck timeout must be between 0.05 and 30 seconds")
    if not (0.05 <= manifest.request_timeout_seconds <= 60):
        raise ValueError("request timeout must be between 0.05 and 60 seconds")
    if manifest.action_mode == "approval_gated":
        if not manifest.human_approval_required or "actuate" not in manifest.permissions:
            raise ValueError("approval_gated actions require human approval and declared actuation permission")
        if not manifest.action_ids or not manifest.approved_device_ids:
            raise ValueError("approval_gated actions require explicit action and device allowlists")
    if manifest.action_mode == "simulation_only" and "simulate_action" not in manifest.permissions:
        raise ValueError("simulation_only requires simulate_action permission")
    if "actuate" in manifest.permissions and manifest.action_mode != "approval_gated":
        raise ValueError("actuation permission requires approval_gated declaration")
    if len(set(manifest.action_ids)) != len(manifest.action_ids):
        raise ValueError("action_ids must be unique")
    return {
        "connector_id": manifest.connector_id,
        "version": manifest.version,
        "connector_type": manifest.connector_type,
        "capabilities": list(manifest.capabilities),
        "permissions": list(manifest.permissions),
        "target_scope": manifest.target_scope,
        "auth_scheme": manifest.auth_scheme,
        "healthcheck_timeout_seconds": manifest.healthcheck_timeout_seconds,
        "request_timeout_seconds": manifest.request_timeout_seconds,
        "supports_idempotency": manifest.supports_idempotency,
        "action_mode": manifest.action_mode,
        "action_ids": list(manifest.action_ids),
        "approved_device_ids": list(manifest.approved_device_ids),
        "human_approval_required": manifest.human_approval_required,
        "live_actuation_available_in_registry": False,
    }


class ConnectorAdapter(Protocol):
    manifest: ConnectorManifest

    def health_check(self, timeout_seconds: float) -> dict[str, Any]: ...
    def read_telemetry(self, timeout_seconds: float) -> dict[str, Any]: ...
    def simulate_action(
        self, action_id: str, parameters: dict[str, Any],
        idempotency_key: str, timeout_seconds: float,
    ) -> dict[str, Any]: ...


class ConnectorRegistry:
    """Allowlisted registry with bounded read retries and simulation-only actions."""

    def __init__(self, allowed_connector_ids: set[str] | None = None):
        self.allowed_connector_ids = set(allowed_connector_ids or set())
        self._adapters: dict[str, ConnectorAdapter] = {}
        self._idempotency_cache: dict[tuple[str, str, str], dict[str, Any]] = {}

    def register(self, adapter: ConnectorAdapter) -> None:
        manifest = validate_manifest(adapter.manifest)
        connector_id = manifest["connector_id"]
        if connector_id not in self.allowed_connector_ids:
            raise PermissionError("connector is not in the configured allowlist")
        if connector_id in self._adapters:
            raise ValueError("connector is already registered")
        self._adapters[connector_id] = adapter

    def manifest(self, connector_id: str) -> dict[str, Any]:
        adapter = self._get(connector_id)
        return validate_manifest(adapter.manifest)

    def _get(self, connector_id: str) -> ConnectorAdapter:
        adapter = self._adapters.get(connector_id)
        if adapter is None:
            raise PermissionError("connector is not registered and allowlisted")
        return adapter

    def health_check(self, connector_id: str) -> dict[str, Any]:
        adapter = self._get(connector_id)
        manifest = adapter.manifest
        if "health_check" not in manifest.capabilities or "read_health" not in manifest.permissions:
            raise PermissionError("connector manifest does not allow health checks")
        started = time.monotonic()
        result = adapter.health_check(manifest.healthcheck_timeout_seconds)
        elapsed = time.monotonic() - started
        if elapsed > manifest.healthcheck_timeout_seconds:
            raise ConnectorTimeout("health check exceeded declared timeout")
        return {"ok": True, "connector_id": connector_id, "elapsed_ms": int(elapsed * 1000), "data": result}

    def read_telemetry(self, connector_id: str) -> dict[str, Any]:
        adapter = self._get(connector_id)
        manifest = adapter.manifest
        if "read_telemetry" not in manifest.capabilities or "read_telemetry" not in manifest.permissions:
            raise PermissionError("connector manifest does not allow telemetry reads")
        last_error: Exception | None = None
        for attempt in range(1, 3):
            started = time.monotonic()
            try:
                result = adapter.read_telemetry(manifest.request_timeout_seconds)
                elapsed = time.monotonic() - started
                if elapsed > manifest.request_timeout_seconds:
                    raise ConnectorTimeout("telemetry read exceeded declared timeout")
                return {
                    "ok": True, "connector_id": connector_id,
                    "attempts": attempt, "elapsed_ms": int(elapsed * 1000),
                    "data": result,
                }
            except ConnectorTransientError as exc:
                last_error = exc
                if attempt == 2:
                    break
        if last_error:
            raise last_error
        raise ConnectorError("telemetry read failed")

    def simulate_action(
        self,
        connector_id: str,
        action_id: str,
        parameters: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        adapter = self._get(connector_id)
        manifest = adapter.manifest
        if manifest.action_mode != "simulation_only":
            raise PermissionError("only simulation_only actions are callable in this registry")
        if "simulate_action" not in manifest.capabilities or "simulate_action" not in manifest.permissions:
            raise PermissionError("connector manifest does not allow action simulation")
        if action_id not in manifest.action_ids:
            raise PermissionError("action is not in the declared action allowlist")
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ValueError("invalid idempotency key")
        if not manifest.supports_idempotency:
            raise PermissionError("connector must declare idempotency support for simulated actions")
        key = (connector_id, action_id, idempotency_key)
        if key in self._idempotency_cache:
            return dict(self._idempotency_cache[key])
        started = time.monotonic()
        data = adapter.simulate_action(
            action_id, dict(parameters), idempotency_key, manifest.request_timeout_seconds,
        )
        elapsed = time.monotonic() - started
        if elapsed > manifest.request_timeout_seconds:
            raise ConnectorTimeout("simulated action exceeded declared timeout")
        result = {
            "ok": True,
            "connector_id": connector_id,
            "action_id": action_id,
            "idempotency_key_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16],
            "elapsed_ms": int(elapsed * 1000),
            "simulated": True,
            "executed": False,
            "external_side_effects": False,
            "data": data,
        }
        self._idempotency_cache[key] = dict(result)
        return result


class MockSecurityConnector:
    """Contract test double. It never contacts or actuates real hardware."""

    def __init__(
        self,
        connector_id: str = "mock-security-lab",
        fail_reads_remaining: int = 0,
        simulated_latency_ms: int = 0,
        request_timeout_seconds: float = 3.0,
        action_ids: tuple[str, ...] = (),
    ):
        self.read_attempts = 0
        self.simulated_action_count = 0
        self.fail_reads_remaining = fail_reads_remaining
        self.simulated_latency_ms = simulated_latency_ms
        self.manifest = ConnectorManifest(
            connector_id=connector_id,
            connector_type="hardware_simulator",
            capabilities=("health_check", "read_telemetry", "simulate_action"),
            permissions=("read_health", "read_telemetry", "simulate_action"),
            target_scope="test-lab-only",
            request_timeout_seconds=request_timeout_seconds,
            supports_idempotency=True,
            action_mode="simulation_only",
            action_ids=action_ids,
        )

    def health_check(self, timeout_seconds: float) -> dict[str, Any]:
        if self.simulated_latency_ms > timeout_seconds * 1000:
            raise ConnectorTimeout("mock health check exceeded timeout")
        return {"status": "healthy", "simulated": True}

    def read_telemetry(self, timeout_seconds: float) -> dict[str, Any]:
        self.read_attempts += 1
        if self.simulated_latency_ms > timeout_seconds * 1000:
            raise ConnectorTimeout("mock telemetry read exceeded timeout")
        if self.fail_reads_remaining > 0:
            self.fail_reads_remaining -= 1
            raise ConnectorTransientError("simulated transient read failure")
        return {"device_status": "simulated", "temperature_c": 24.0}

    def simulate_action(
        self, action_id: str, parameters: dict[str, Any],
        idempotency_key: str, timeout_seconds: float,
    ) -> dict[str, Any]:
        if self.simulated_latency_ms > timeout_seconds * 1000:
            raise ConnectorTimeout("mock action simulation exceeded timeout")
        self.simulated_action_count += 1
        return {"action": action_id, "parameters": parameters, "status": "simulated_only"}
