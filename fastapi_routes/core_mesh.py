"""Native FastAPI routes for authenticated USECT Core Mesh and user-taught learning."""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ai.core_mesh import (
    CoreMeshError,
    core_mesh_operator_allowed,
    get_core_mesh_dashboard,
    get_genesis_capability_plan,
    get_genesis_hardware_guide,
    get_genesis_key_request_info,
    get_genesis_proposal,
    get_genesis_status,
    iter_genesis_events,
    list_genesis_proposals,
    queue_genesis_demand,
    request_genesis_provider_key,
    compile_genesis_rvx,
    propose_genesis_invention,
    propose_mind_evolution,
    score_mind_foundry_candidate,
)
from ai.tool_registry import (
    GenesisToolRegistryError,
    activate_signed_tool,
    confirm_tier2_action,
    deactivate_signed_tool,
    execute_active_tool,
    get_signed_tool_version,
    list_active_tools,
    list_signed_tools,
    provider_tool_context,
    publish_signed_tool,
    rollback_signed_tool,
)

from fastapi_routes.auth import resolve_revelacode_user

from services.revenue_entitlements import check_entitlement

from ai.unknown_learning import (
    attach_genesis_proposal,
    attach_improvement_proposal,
    list_known,
    publish_known,
    save_teaching,
)

router = APIRouter(tags=["Core Mesh", "Living Brain Learning"])
logger = logging.getLogger("revelaai.fastapi.core_mesh")
def _resolve_user(authorization: str) -> tuple[str | None, JSONResponse | None]:
    """Ask RevelaCode to verify the bearer token and return its canonical user ID."""
    return resolve_revelacode_user(authorization)


def _operator_allowed(user_id: str) -> bool:
    return core_mesh_operator_allowed(user_id)


def _auth_failure():
    return JSONResponse(
        {
            "status": "error",
            "error": {
                "code": "authentication_required",
                "message": "Sign in with a valid RevelaCode session to access Core Mesh.",
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
    user_id, auth_error = _resolve_user(authorization)
    if auth_error:
        return auth_error
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
    cores = snapshot.get("cores") if isinstance(snapshot, dict) else {}
    mind = cores.get("two") if isinstance(cores, dict) else {}
    mind_available = isinstance(mind, dict) and mind.get("reachable") is True
    return {
        "status": "success",
        "data": snapshot,
        "mind_status": "online" if mind_available else "mind_unavailable",
        "chat_available": True,
    }


def _proposal(authorization: str, body: Any, kind: str):
    user_id, auth_error = _resolve_user(authorization)
    if auth_error:
        return auth_error
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
    user_id, auth_error = _resolve_user(authorization)
    if auth_error:
        return auth_error
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
    user_id, auth_error = _resolve_user(authorization)
    if auth_error:
        return auth_error
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


def _core_mesh_upstream_error(exc: CoreMeshError):
    return JSONResponse(
        {"status": "error", "error": {"code": exc.code, "message": str(exc)}},
        status_code=exc.status_code,
    )


def _authenticated_core_mesh_user(request: Request) -> str | JSONResponse:
    user_id, auth_error = _resolve_user(request.headers.get("Authorization", ""))
    if auth_error:
        return auth_error
    if not user_id:
        return _auth_failure()
    return user_id


@router.get("/api/core-mesh/genesis/status")
async def core_mesh_genesis_status_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    try:
        result = await run_in_threadpool(get_genesis_status)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.get("/api/core-mesh/genesis/proposals")
async def core_mesh_genesis_proposals_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    try:
        result = await run_in_threadpool(list_genesis_proposals)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.get("/api/core-mesh/genesis/proposals/{name}")
async def core_mesh_genesis_proposal_api(name: str, request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(get_genesis_proposal, name)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.get("/api/core-mesh/genesis/tools/{name}/hardware-guide")
async def core_mesh_genesis_hardware_guide_api(
    name: str, request: Request, country: str = "KE", lang: str = ""
):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(get_genesis_hardware_guide, name, country, lang)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.get("/api/core-mesh/genesis/tools/{name}/capability-plan")
async def core_mesh_genesis_capability_plan_api(name: str, request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    try:
        result = await run_in_threadpool(get_genesis_capability_plan, name)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.post("/api/core-mesh/genesis/queue")
async def core_mesh_genesis_queue_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    body = await _body_or_none(request)
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Send a JSON object containing demand, country and optional language."}},
            status_code=400,
        )
    try:
        result = await run_in_threadpool(
            queue_genesis_demand,
            body.get("demand", ""),
            source="revelaai-gateway",
            country=str(body.get("country") or "KE"),
            language=str(body.get("language") or ""),
        )
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return JSONResponse({"status": "success", "data": result}, status_code=202)


@router.get("/api/core-mesh/genesis/key")
async def core_mesh_genesis_key_info_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    try:
        result = await run_in_threadpool(get_genesis_key_request_info)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.post("/api/core-mesh/genesis/key/request")
async def core_mesh_genesis_key_request_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    body = await _body_or_none(request)
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Send client_id and reason."}},
            status_code=400,
        )
    try:
        result = await run_in_threadpool(
            request_genesis_provider_key,
            str(body.get("client_id") or ""),
            str(body.get("reason") or ""),
        )
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return JSONResponse({"status": "success", "data": result}, status_code=202)


@router.post("/api/core-mesh/genesis/rvx/compile")
async def core_mesh_genesis_rvx_compile_api(request: Request):
    entitlement_error = _smart_ai_automation_entitlement_error(request)
    if entitlement_error is not None:
        return entitlement_error

    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    body = await _body_or_none(request)
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Send an RVX source string."}},
            status_code=400,
        )
    try:
        result = await run_in_threadpool(compile_genesis_rvx, str(body.get("source") or ""))
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    return {"status": "success", "data": result}


@router.get("/api/core-mesh/genesis/events")
async def core_mesh_genesis_events_api(request: Request, limit: int = 100):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    if not 1 <= limit <= 250:
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_event_limit", "message": "limit must be between 1 and 250."}},
            status_code=400,
        )

    def event_stream():
        try:
            for event in iter_genesis_events(max_events=limit):
                if not isinstance(event, dict):
                    continue
                event_name = str(event.get("type") or "message").replace("\r", "").replace("\n", "")[:80] or "message"
                yield "event: " + event_name + "\n"
                yield "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
        except CoreMeshError as exc:
            payload = json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False)
            yield "event: error\n"
            yield "data: " + payload + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/core-mesh/dashboard")
async def core_mesh_dashboard_api(request: Request, refresh: str = ""):
    return await run_in_threadpool(
        _core_mesh_dashboard, request.headers.get("Authorization", ""), refresh
    )


@router.post("/api/core-mesh/genesis/invent")
async def core_mesh_genesis_invent_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    entitlement_error = _smart_ai_automation_entitlement_error(request)
    if entitlement_error is not None:
        return entitlement_error

    body = await _body_or_none(request)
    return await run_in_threadpool(
        _proposal, request.headers.get("Authorization", ""), body, "genesis"
    )


@router.post("/api/core-mesh/mind/evolve")
async def core_mesh_mind_evolve_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    entitlement_error = _smart_ai_automation_entitlement_error(request)
    if entitlement_error is not None:
        return entitlement_error

    body = await _body_or_none(request)
    return await run_in_threadpool(
        _proposal, request.headers.get("Authorization", ""), body, "mind"
    )


@router.post("/api/core-mesh/mind/candidates")
async def core_mesh_mind_candidates_api(request: Request):
    user_id = _authenticated_core_mesh_user(request)
    if not isinstance(user_id, str):
        return user_id
    operator_error = _operator_failure(user_id)
    if operator_error:
        return operator_error
    entitlement_error = _smart_ai_automation_entitlement_error(request)
    if entitlement_error is not None:
        return entitlement_error

    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16 * 1024:
            return JSONResponse(
                {"status": "error", "error": {
                    "code": "candidate_payload_too_large",
                    "message": "Candidate metadata must not exceed 16 KiB.",
                }},
                status_code=413,
            )
    try:
        body = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            {"status": "error", "error": {
                "code": "invalid_json",
                "message": "Candidate metadata must be a UTF-8 JSON object.",
            }},
            status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse(
            {"status": "error", "error": {
                "code": "invalid_mind_candidate",
                "message": "Candidate metadata must be a JSON object.",
            }},
            status_code=400,
        )

    try:
        result = await run_in_threadpool(score_mind_foundry_candidate, body)
    except CoreMeshError as exc:
        return _core_mesh_upstream_error(exc)
    except Exception:
        logger.warning("Mind candidate assessment request failed.")
        return JSONResponse(
            {"status": "error", "error": {
                "code": "mind_candidate_assessment_failed",
                "message": "Infinite Mind could not assess the candidate.",
            }},
            status_code=502,
        )
    return JSONResponse({"status": "success", "data": result}, status_code=200)




def _tool_registry_error(exc: GenesisToolRegistryError):
    return JSONResponse(
        {"status": "error", "error": {"code": exc.code, "message": str(exc)}},
        status_code=exc.status_code,
    )


def _authenticated_tool_user(request: Request) -> str | JSONResponse:
    user_id, auth_error = _resolve_user(request.headers.get("Authorization", ""))
    if auth_error:
        return auth_error
    if not user_id:
        return _auth_failure()
    return user_id


def _smart_ai_automation_entitlement_error(request: Request) -> JSONResponse | None:
    """Premium compute/engineering actions share the central Smart AI entitlement."""
    _, error = check_entitlement(
        request.headers.get("Authorization", ""),
        hub="smart_ai",
        feature="automation",
    )
    return error


def _approved_tool_operator(user_id: str):
    return _operator_failure(user_id)


def _genesis_owner_failure(user_id: str):
    """Tier 1-2 activation/rollback must be approved by an explicitly configured owner."""
    configured = os.getenv("GENESIS_OWNER_USER_IDS", "").strip()
    if not configured:
        return JSONResponse(
            {"status": "error", "error": {"code": "genesis_owner_not_configured", "message": "Configure GENESIS_OWNER_USER_IDS before approving Tier 1-2 tool activation or rollback."}},
            status_code=503,
        )
    allowed = {value.strip() for value in configured.split(",") if value.strip()}
    if not user_id or user_id not in allowed:
        return JSONResponse(
            {"status": "error", "error": {"code": "genesis_owner_required", "message": "This signed tool lifecycle action requires a Genesis owner approval."}},
            status_code=403,
        )
    return None


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
            "can_execute": _operator_allowed(user_id),
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
    operator_error = _approved_tool_operator(user_id)
    if operator_error:
        return operator_error
    entitlement_error = _smart_ai_automation_entitlement_error(request)
    if entitlement_error is not None:
        return entitlement_error
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


@router.post("/api/core-mesh/tools/{name}/publish")
async def core_mesh_tool_publish_api(name: str, request: Request):
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
        record = await run_in_threadpool(get_signed_tool_version, name, version, artifact_hash)
        manifest = record.get("manifest") if isinstance(record, dict) else {}
        risk_tier = manifest.get("risk_tier", 0) if isinstance(manifest, dict) else 0
        owner_approval_required = risk_tier in {1, 2}
        if owner_approval_required:
            owner_error = _genesis_owner_failure(user_id)
            if owner_error:
                return owner_error
        result = await run_in_threadpool(
            activate_signed_tool,
            name,
            version,
            artifact_hash,
            owner_approval_required=owner_approval_required,
        )
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
    owner_error = _genesis_owner_failure(user_id)
    if owner_error:
        return owner_error
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
    version = str(body.get("version") or "")
    artifact_hash = str(body.get("artifact_hash") or "")
    try:
        record = await run_in_threadpool(get_signed_tool_version, name, version, artifact_hash)
        manifest = record.get("manifest") if isinstance(record, dict) else {}
        risk_tier = manifest.get("risk_tier", 0) if isinstance(manifest, dict) else 0
        owner_approval_required = risk_tier in {1, 2}
        if owner_approval_required:
            owner_error = _genesis_owner_failure(user_id)
            if owner_error:
                return owner_error
        result = await run_in_threadpool(
            rollback_signed_tool,
            name,
            version,
            artifact_hash,
            owner_approval_required=owner_approval_required,
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
    user_id, auth_error = _resolve_user(request.headers.get("Authorization", ""))
    if auth_error:
        return auth_error
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
