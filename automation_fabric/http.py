"""Shared HTTP API factory for cloud and loopback-local Automation Fabric runtimes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from . import store
from .engine import AutomationError, create_plan, execute_plan
from .policy import (
    DEFAULT_CONSENT_TTL_SECONDS,
    MAX_CONSENT_TTL_SECONDS,
    SCOPES,
    normalize_scopes,
)
from .registry import tool_catalog

logger = logging.getLogger("revelaai.automation_fabric")


AuthResolver = Callable[[], tuple[str | None, Any | None]]
WorkspaceResolver = Callable[[str], str | Path]
DatabaseResolver = Callable[[], str | None]


def create_automation_blueprint(
    name: str,
    *,
    auth_resolver: AuthResolver,
    workspace_resolver: WorkspaceResolver,
    database_resolver: DatabaseResolver,
    local_mode: bool,
) -> Blueprint:
    bp = Blueprint(name, __name__)

    def _principal():
        try:
            principal, error = auth_resolver()
        except Exception:
            logger.exception("Automation Fabric authentication resolver failed")
            return None, (jsonify(status="error", code="authentication_unavailable"), 503)
        if error is not None:
            return None, error
        if not isinstance(principal, str) or not principal:
            return None, (jsonify(status="error", code="authentication_required"), 401)
        return principal, None

    def _db() -> str | None:
        return database_resolver()

    def _workspace(principal: str) -> Path:
        root = Path(workspace_resolver(principal)).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return root

    @bp.get("/health")
    def health():
        return jsonify({
            "status": "ok",
            "module": "revelaai-automation-fabric",
            "version": "1.0.0",
            "mode": "local-device" if local_mode else "hosted-workspace",
            "execution": "deterministic",
            "models_required": False,
            "shell_execution": False,
            "generated_code_autorun": False,
            "hardware_actuation": False,
        }), 200

    @bp.get("/tools")
    def tools():
        principal, error = _principal()
        if error:
            return error
        return jsonify({
            "status": "ok",
            "tools": tool_catalog(),
            "consent": store.list_scopes(principal, db_path=_db()),
            "runtime": "local-device" if local_mode else "hosted-workspace",
            "note": "A hosted workspace is isolated from the user's personal device. Device-only tools require the separately installed local agent.",
        }), 200

    @bp.get("/consent")
    def get_consent():
        principal, error = _principal()
        if error:
            return error
        return jsonify({"status": "ok", "scopes": store.list_scopes(principal, db_path=_db())}), 200

    @bp.post("/consent")
    def grant_consent():
        principal, error = _principal()
        if error:
            return error
        body = request.get_json(silent=True) or {}
        if body.get("accepted") is not True:
            return jsonify(status="error", code="explicit_consent_required",
                           message="Set accepted=true only after reviewing the requested permission scopes."), 400
        try:
            scopes = normalize_scopes(body.get("scopes"))
            ttl = body.get("ttl_seconds", DEFAULT_CONSENT_TTL_SECONDS)
            if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 60 or ttl > MAX_CONSENT_TTL_SECONDS:
                raise ValueError("ttl_seconds must be an integer from 60 to 86400")
            reason = body.get("reason", "")
            if not isinstance(reason, str) or len(reason) > 240:
                raise ValueError("reason must be a string of at most 240 characters")
            grants = store.grant_scopes(principal, scopes, reason=reason.strip(), ttl_seconds=ttl, db_path=_db())
            return jsonify({"status": "ok", "granted": scopes, "scopes": grants, "expires_in_seconds": ttl}), 201
        except ValueError as exc:
            return jsonify(status="error", code="invalid_consent", message=str(exc)), 400
        except Exception:
            logger.exception("Automation Fabric could not persist consent")
            return jsonify(status="error", code="consent_storage_unavailable"), 503

    @bp.post("/consent/revoke")
    def revoke_consent():
        principal, error = _principal()
        if error:
            return error
        body = request.get_json(silent=True) or {}
        try:
            scopes = normalize_scopes(body.get("scopes"))
            revoked = store.revoke_scopes(principal, scopes, db_path=_db())
            return jsonify({"status": "ok", "revoked": revoked, "scopes": store.list_scopes(principal, db_path=_db())}), 200
        except ValueError as exc:
            return jsonify(status="error", code="invalid_consent", message=str(exc)), 400
        except Exception:
            logger.exception("Automation Fabric could not revoke consent")
            return jsonify(status="error", code="consent_storage_unavailable"), 503

    @bp.post("/plan")
    def plan():
        principal, error = _principal()
        if error:
            return error
        body = request.get_json(silent=True) or {}
        try:
            result = create_plan(
                principal, body.get("steps"), _workspace(principal),
                db_path=_db(), local_mode=local_mode,
            )
            return jsonify({"status": "planned", "plan": result}), 201
        except AutomationError as exc:
            return jsonify(status="error", code=exc.code, message=exc.message), exc.status_code
        except ValueError as exc:
            return jsonify(status="error", code="invalid_plan", message=str(exc)), 400
        except Exception:
            logger.exception("Automation Fabric failed to create a plan")
            return jsonify(status="error", code="planning_unavailable"), 503

    @bp.get("/plans/<plan_id>")
    def plan_status(plan_id: str):
        principal, error = _principal()
        if error:
            return error
        record = store.get_plan(principal, plan_id, db_path=_db())
        if record is None:
            return jsonify(status="error", code="plan_not_found"), 404
        return jsonify({"status": "ok", "record": record}), 200

    @bp.post("/execute")
    def execute():
        principal, error = _principal()
        if error:
            return error
        body = request.get_json(silent=True) or {}
        plan_id = body.get("plan_id")
        plan_hash = body.get("plan_hash")
        if not isinstance(plan_id, str) or not isinstance(plan_hash, str):
            return jsonify(status="error", code="invalid_execution_request",
                           message="plan_id and plan_hash are required"), 400
        try:
            result = execute_plan(
                principal, plan_id, plan_hash,
                approved=body.get("approved") is True,
                workspace=_workspace(principal),
                db_path=_db(),
                local_mode=local_mode,
            )
            return jsonify({"status": "ok", "execution": result}), 200
        except AutomationError as exc:
            return jsonify(status="error", code=exc.code, message=exc.message), exc.status_code
        except Exception:
            logger.exception("Automation Fabric execution stopped unexpectedly")
            return jsonify(status="error", code="execution_unavailable",
                           message="Execution stopped safely. Check the audit log and plan status."), 503

    @bp.get("/audit")
    def audit():
        principal, error = _principal()
        if error:
            return error
        try:
            limit = request.args.get("limit", default="50")
            if not str(limit).isdigit():
                raise ValueError("limit must be an integer")
            entries = store.read_audit(principal, int(limit), db_path=_db())
            return jsonify({"status": "ok", "entries": entries, "hash_chained": True}), 200
        except ValueError as exc:
            return jsonify(status="error", code="invalid_limit", message=str(exc)), 400
        except Exception:
            logger.exception("Automation Fabric audit log unavailable")
            return jsonify(status="error", code="audit_unavailable"), 503

    return bp
