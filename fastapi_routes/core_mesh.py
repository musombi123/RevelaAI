"""Native FastAPI routes for authenticated USECT Core Mesh and user-taught learning."""
from __future__ import annotations

import logging
import os
from typing import Any

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ai.core_mesh import (
    CoreMeshError,
    get_core_mesh_dashboard,
    propose_genesis_invention,
    propose_mind_evolution,
)
from ai.tool_registry import (
    GenesisToolRegistryError,
    activate_signed_tool,
    confirm_tier2_action,
    deactivate_signed_tool,
    execute_active_tool,
    list_active_tools,
    list_signed_tools,
    provider_tool_context,
    publish_signed_tool,
    rollback_signed_tool,
)

from ai.unknown_learning import (
    attach_genesis_proposal,
    attach_improvement_proposal,
    list_known,
    publish_known,
    save_teaching,
)

router = APIRouter(tags=["Core Mesh", "Living Brain Learning"])
logger = logging.getLogger("revelaai.fastapi.core_mesh")
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
JWT_ALGORITHM = "HS256"


def _resolve_user(authorization: str) -> str | None:
    """Preserve the existing Core Mesh JWT contract (identity only)."""
    header = (authorization or "").strip()
    if not JWT_SECRET or not header.startswith("Bearer ") or not header[7:].strip():
        return None
    try:
        claims = jwt.decode(
            header[7:].strip(),
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    user_id = claims.get("sub") or claims.get("user_id") or claims.get("id")
    user_id = str(user_id or "").strip()
    return user_id or None


def _operator_allowed(user_id: str) -> bool:
    configured = (
        os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
        or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    )
    allowed = {value.strip() for value in configured.split(",") if value.strip()}
    return bool(user_id and allowed and user_id in allowed)


def _auth_failure():
    return JSONResponse(
        {
            "status": "error",
            "error": {
                "code": "authentication_required",
                "message": "Sign in with a valid RevelaCode session to access core status.",
            },
        },
        status_code=401,
    )


def _operator_failure(user_id: str):
    configured = (
        os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
        or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    ).strip()
    if not configured:
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "core_mesh_operator_not_configured",
                    "message": "Configure CORE_MESH_ADMIN_USER_IDS server-side before enabling invention/evolution actions.",
                },
            },
            status_code=503,
        )
    if not _operator_allowed(user_id):
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "core_mesh_operator_required",
                    "message": "This operation is restricted to an approved Core Mesh operator.",
                },
            },
            status_code=403,
        )
    return None


def _core_mesh_dashboard(authorization: str, refresh: str):
    user_id = _resolve_user(authorization)
    if not user_id:
        return _auth_failure()
    try:
        snapshot = get_core_mesh_dashboard(force_refresh=(refresh or "").strip() == "1")
    except Exception:
        logger.warning("Core Mesh dashboard snapshot failed.")
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "core_mesh_status_unavailable",
                    "message": "Core Mesh status could not be assembled.",
                },
            },
            status_code=503,
        )
    return {"status": "success", "data": snapshot}


def _proposal(authorization: str, body: Any, kind: str):
    user_id = _resolve_user(authorization)
    if not user_id:
        return _auth_failure()
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    if not isinstance(body, dict):
        message = (
            "Send a JSON object containing demand."
            if kind == "genesis"
            else "Send a JSON object containing objective and tool_name."
        )
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": message}},
            status_code=400,
        )
    try:
        if kind == "genesis":
            result = propose_genesis_invention(body.get("demand", ""))
        else:
            result = propose_mind_evolution(
                body.get("objective", ""),
                body.get("tool_name", "offline_vault_fixture"),
            )
    except CoreMeshError as exc:
        return JSONResponse(
            {"status": "error", "error": {"code": exc.code, "message": str(exc)}},
            status_code=exc.status_code,
        )
    except Exception:
        logger.warning("Core Mesh %s proposal request failed.", kind.title())
        code = "genesis_proposal_failed" if kind == "genesis" else "mind_evolution_failed"
        message = "Genesis could not create the proposal." if kind == "genesis" else "Infinite Mind could not create the proposal."
        return JSONResponse(
            {"status": "error", "error": {"code": code, "message": message}},
            status_code=502,
        )
    return JSONResponse({"status": "success", "data": result}, status_code=202)


def _learn_unknown(
    authorization: str,
    body: Any,
    country_query: str,
    language_query: str,
):
    user_id = _resolve_user(authorization)
    if not user_id:
        return _auth_failure()
    if not isinstance(body, dict):
        return JSONResponse(
            {
                "status": "error",
                "error": {"code": "invalid_json", "message": "Send topic and steps."},
            },
            status_code=400,
        )
    country = str(country_query or body.get("country") or "KE").strip()[:80]
    language = str(language_query or body.get("language") or "").strip()[:20]
    try:
        saved = save_teaching(
            topic=body.get("topic", ""),
            user_id=user_id,
            steps=body.get("steps"),
            country=country,
            language=language,
            photo_hash=str(body.get("photo_hash") or "").strip(),
            consent_to_share=body.get("consent_to_share") is True,
            source_request=str(body.get("source_request") or ""),
        )
    except PermissionError as exc:
        return JSONResponse(
            {"status": "blocked", "error": {"code": "worldwide_guardian_block", "message": str(exc)}},
            status_code=403,
        )
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_teaching_submission", "message": str(exc)}},
            status_code=400,
        )
    except OSError:
        logger.warning("Living Brain could not persist a teaching record.")
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "learning_storage_unavailable",
                    "message": "Knowledge could not be saved; no tool proposal was triggered.",
                },
            },
            status_code=503,
        )

    result: dict[str, Any] = {
        "saved": True,
        **saved,
        "genesis": {"status": "not_requested"},
    }
    if saved.get("genesis_needed") and saved.get("consent_to_share") is True:
        steps = body.get("steps") if isinstance(body.get("steps"), list) else []
        short_steps = "; ".join(
            str(step).strip()[:90] for step in steps[:3] if str(step).strip()
        )
        demand = (
            f"Create a safe reviewable tool proposal for {str(body.get('topic') or '')[:140]}. "
            f"Country {saved.get('country')}; language {saved.get('language')}. "
            f"Unverified user notes: {short_steps[:170]}. Include a localized supplier directory, quote-required BOM, "
            "hardware guide, tests and safety gates. Await human merge."
        )[:495]
        try:
            proposal = propose_genesis_invention(
                demand, country=saved["country"], language=saved["language"]
            )
            attached = attach_genesis_proposal(saved["topic_key"], proposal)
            result["genesis"] = {
                "status": attached.get("status", "await_merge"),
                "proposal": attached.get("proposal", {}),
                "human_approval_required": True,
                "automatic_execution": False,
                "automatic_merge": False,
            }
        except CoreMeshError as exc:
            result["genesis"] = {
                "status": "awaiting_genesis",
                "error_code": exc.code,
                "retry_allowed": True,
            }
    elif not saved.get("consent_to_share"):
        result["genesis"] = {
            "status": "private_until_explicit_sharing_consent",
            "proposal_created": False,
        }
    return JSONResponse({"status": "accepted", "data": result}, status_code=202)


def _publish_known(authorization: str, topic_key: str, body: Any):
    user_id = _resolve_user(authorization)
    if not user_id:
        return _auth_failure()
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    if not isinstance(body, dict):
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "invalid_json",
                    "message": "Send tool_name, endpoint and merge_commit.",
                },
            },
            status_code=400,
        )
    try:
        result = publish_known(
            topic_key=topic_key,
            operator_id=user_id,
            tool_name=body.get("tool_name", ""),
            endpoint=body.get("endpoint", ""),
            merge_commit=body.get("merge_commit", ""),
        )
    except PermissionError as exc:
        return JSONResponse(
            {"status": "error", "error": {"code": "learning_consent_required", "message": str(exc)}},
            status_code=403,
        )
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "error": {"code": "learning_publish_rejected", "message": str(exc)}},
            status_code=422,
        )

    result["mind"] = {"status": "not_staged"}
    tool_name = str(result.get("tool_name") or "")
    try:
        objective = f"Review measured worldwide outcomes for {tool_name}; propose one evidence-gated improvement."
        proposal = propose_mind_evolution(objective, tool_name)
        attach_improvement_proposal(topic_key, proposal)
        result["mind"] = {
            "status": "await_merge",
            "proposal": {
                key: proposal[key]
                for key in ("status", "version", "tool_name", "selected_mutation", "await_merge_path")
                if key in proposal
            },
            "human_approval_required": True,
            "automatic_merge": False,
        }
    except CoreMeshError as exc:
        result["mind"] = {
            "status": "not_staged",
            "error_code": exc.code,
            "retry_allowed": True,
        }
    except ValueError:
        result["mind"] = {
            "status": "not_staged",
            "error_code": "mind_proposal_rejected",
            "retry_allowed": True,
        }
    return JSONResponse({"status": "success", "data": result}, status_code=202)


async def _body_or_none(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@router.get("/api/core-mesh/dashboard")
async def core_mesh_dashboard_api(request: Request, refresh: str = ""):
    return await run_in_threadpool(
        _core_mesh_dashboard, request.headers.get("Authorization", ""), refresh
    )


@router.post("/api/core-mesh/genesis/invent")
async def core_mesh_genesis_invent_api(request: Request):
    body = await _body_or_none(request)
    return await run_in_threadpool(
        _proposal, request.headers.get("Authorization", ""), body, "genesis"
    )


@router.post("/api/core-mesh/mind/evolve")
async def core_mesh_mind_evolve_api(request: Request):
    body = await _body_or_none(request)
    return await run_in_threadpool(
        _proposal, request.headers.get("Authorization", ""), body, "mind"
    )




def _tool_registry_error(exc: GenesisToolRegistryError):
    return JSONResponse(
        {"status": "error", "error": {"code": exc.code, "message": str(exc)}},
        status_code=exc.status_code,
    )


def _authenticated_tool_user(request: Request) -> str | JSONResponse:
    user_id = _resolve_user(request.headers.get("Authorization", ""))
    if not user_id:
        return _auth_failure()
    return user_id


def _approved_tool_operator(user_id: str):
    return _operator_failure(user_id)


@router.get("/api/core-mesh/tools")
async def core_mesh_tools_api(request: Request, provider: str = ""):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    configured_order = [
        item.strip().lower()
        for item in os.getenv("REVELAAI_TEXT_PROVIDERS", "gemini").split(",")
        if item.strip()
    ]
    selected_provider = (
        str(provider or os.getenv("REVELAAI_ACTIVE_TEXT_PROVIDER") or "").strip().lower()
        or (configured_order[0] if configured_order else "gemini")
    )
    try:
        tools = await run_in_threadpool(list_active_tools)
        context = await run_in_threadpool(provider_tool_context, selected_provider, tools)
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {
        "status": "success",
        "data": {
            "provider": selected_provider,
            "active_tools": tools,
            "tool_context": context,
            "execution_policy": "signed-artifacts-only; generated source never runs in the gateway",
        },
    }


@router.get("/api/core-mesh/tools/registry")
async def core_mesh_tool_registry_api(request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    try:
        records = await run_in_threadpool(list_signed_tools)
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {"status": "success", "data": {"count": len(records), "tools": records}}


@router.post("/api/core-mesh/tools/execute")
async def core_mesh_tool_execute_api(request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    body = await _body_or_none(request)
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Send a JSON object with name, version, artifact_hash and arguments."}},
            status_code=400,
        )
    try:
        result = await run_in_threadpool(
            execute_active_tool,
            str(body.get("name") or ""),
            str(body.get("version") or ""),
            str(body.get("artifact_hash") or ""),
            body.get("arguments"),
            confirmation_token=str(body.get("confirmation_token") or "") or None,
        )
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {"status": "success", "data": result}


@router.post("/api/core-mesh/tools/{name}/{version}/{artifact_hash}/publish")
async def core_mesh_tool_publish_api(name: str, version: str, artifact_hash: str, request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(publish_signed_tool, name)
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return JSONResponse({"status": "success", "data": result}, status_code=201)


@router.post("/api/core-mesh/tools/{name}/{version}/{artifact_hash}/activate")
async def core_mesh_tool_activate_api(name: str, version: str, artifact_hash: str, request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(activate_signed_tool, name, version, artifact_hash)
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {"status": "success", "data": result}


@router.post("/api/core-mesh/tools/{name}/{version}/{artifact_hash}/confirm")
async def core_mesh_tool_confirm_api(name: str, version: str, artifact_hash: str, request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    body = await _body_or_none(request)
    if not isinstance(body, dict) or not isinstance(body.get("arguments"), dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Confirmation requires the exact tool arguments."}},
            status_code=400,
        )
    action_approval = os.getenv("GENESIS_ACTION_APPROVAL_TOKEN", "").strip()
    try:
        result = await run_in_threadpool(
            confirm_tier2_action,
            name,
            version,
            artifact_hash,
            body["arguments"],
            action_approval_token=action_approval,
        )
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return JSONResponse({"status": "success", "data": result}, status_code=201)


@router.post("/api/core-mesh/tools/{name}/deactivate")
async def core_mesh_tool_deactivate_api(name: str, request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(deactivate_signed_tool, name)
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {"status": "success", "data": result}


@router.post("/api/core-mesh/tools/{name}/rollback")
async def core_mesh_tool_rollback_api(name: str, request: Request):
    user_id = _authenticated_tool_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    body = await _body_or_none(request)
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Rollback requires version and artifact_hash."}},
            status_code=400,
        )
    try:
        result = await run_in_threadpool(
            rollback_signed_tool,
            name,
            str(body.get("version") or ""),
            str(body.get("artifact_hash") or ""),
        )
    except GenesisToolRegistryError as exc:
        return _tool_registry_error(exc)
    return {"status": "success", "data": result}


@router.post("/v1/learn/unknown")
async def learn_unknown_api(request: Request, country: str = "", lang: str = ""):
    body = await _body_or_none(request)
    return await run_in_threadpool(
        _learn_unknown,
        request.headers.get("Authorization", ""),
        body,
        country,
        lang,
    )


@router.get("/v1/learn/known")
async def learn_known_api(request: Request):
    user_id = _resolve_user(request.headers.get("Authorization", ""))
    if not user_id:
        return _auth_failure()
    records = await run_in_threadpool(list_known)
    return {"status": "success", "data": {"count": len(records), "known": records}}


@router.post("/v1/learn/known/{topic_key}/publish")
async def publish_known_learning_api(topic_key: str, request: Request):
    body = await _body_or_none(request)
    return await run_in_threadpool(
        _publish_known, request.headers.get("Authorization", ""), topic_key, body
    )
