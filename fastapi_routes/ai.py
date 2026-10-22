"""Native FastAPI implementation of the main multimodal /ai endpoint.

Provider orchestration and domain intelligence are reused from RevelaAI's
existing service layer. HTTP body parsing, upload validation, authentication
bridging, image URL construction and responses are native ASGI responsibilities.
"""
from __future__ import annotations

import io
import json
import logging
import os
import uuid
from types import SimpleNamespace
from typing import Any, Mapping

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ai.global_brain_adapter import build_global_context
from ai.hub_prompts import HUB_LABELS, get_identity_answer
from ai.intent_router import classify_intent
from ai.json_utils import enforce_base_schema, error_response, extract_json
from fastapi_routes.auth import JWT_ALGORITHM, JWT_SECRET, authenticate_identity
from revelai.core.agi_manifest import get_self_description_answer
from services.ai_service import detect_capability, process_message
from services.revenue_entitlements import check_entitlement
from services.conversation_store import save_image_conversation
from services.document_service import process_uploaded_document
from services.expert_law import analyze_legal_query
from services.expert_medicine import analyze_medical_query
from services.image_service import generate_image_asset, parse_image_options
from fastapi_routes.chat import _load_personalization_context, _persist_turn
from services.conversation_store import MAX_HISTORY, get_session, resolve_conversation_context, save_session
from services.runtime_config import (
    MAX_CONTENT_LENGTH, REVELAAI_BUILD_ID, REVELAAI_IMAGE_ENGINE_VERSION, cleanup_generated_files,
    configured_image_model, get_active_text_provider,
)

router = APIRouter(tags=["AI"])
logger = logging.getLogger("revelaai.fastapi.ai")
MAX_BODY_BYTES = MAX_CONTENT_LENGTH


def _error(code: str, message: str, status_code: int, request_id: str | None = None):
    body = error_response(code, message)
    if isinstance(body, dict) and request_id:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status_code)


def _subject_from_bearer(authorization: str) -> str | None:
    secret = JWT_SECRET
    header = str(authorization or "").strip()
    if not secret or not header.startswith("Bearer ") or not header[7:].strip():
        return None
    try:
        claims = jwt.decode(
            header[7:].strip(),
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    raw_id = claims.get("sub") or claims.get("user_id") or claims.get("id")
    value = str(raw_id or "").strip()
    return value or None


def _session_id(headers: Mapping[str, str], cookies: Mapping[str, str], subject: str | None) -> str:
    header_id = next(
        (str(v).strip() for k, v in headers.items() if str(k).casefold() == "x-session-id"),
        "",
    )
    cookie_id = str(cookies.get("revelaai_session") or "").strip()
    session_id = (header_id or cookie_id or uuid.uuid4().hex)[:128]
    if subject:
        session_id = f"{subject}:{session_id}"[:128]
    return session_id


def _safe_tool_metadata(ai_result: dict[str, Any]) -> dict[str, Any] | None:
    raw_tool_execution = ai_result.get("tool_execution")
    if not isinstance(raw_tool_execution, dict):
        orchestrator = ai_result.get("orchestrator")
        raw_tool_execution = (
            orchestrator.get("usect_zero_tool")
            if isinstance(orchestrator, dict) else None
        )
    if not isinstance(raw_tool_execution, dict):
        return None

    result = {
        "name": str(raw_tool_execution.get("name") or raw_tool_execution.get("tool") or "usect_zero")[:80],
        "operation": str(raw_tool_execution.get("operation") or "unknown")[:40],
        "status": str(raw_tool_execution.get("status") or "unknown")[:40],
        "executed": bool(raw_tool_execution.get("executed", False)),
        "fallback": bool(raw_tool_execution.get("fallback", False)),
    }
    for field in ("http_status", "error_code"):
        value = raw_tool_execution.get(field)
        if isinstance(value, (int, str)) and not isinstance(value, bool):
            result[field] = str(value)[:100] if isinstance(value, str) else value
    message = raw_tool_execution.get("message")
    if isinstance(message, str) and message.strip():
        result["message"] = message.strip()[:240]

    source = raw_tool_execution.get("result")
    allowed = (
        "file_count", "language_counts", "git_head", "manifest_sha256",
        "read_only", "target", "proposal_id", "id", "status", "compiled",
        "artifact_count", "source_count",
    )
    if isinstance(source, dict):
        summary: dict[str, Any] = {}
        for field in allowed:
            if field not in source:
                continue
            value = source[field]
            if isinstance(value, str):
                summary[field] = value[:240]
            elif isinstance(value, (int, float, bool)) or value is None:
                summary[field] = value
            elif isinstance(value, dict):
                summary[field] = {
                    str(k)[:60]: v
                    for k, v in list(value.items())[:12]
                    if isinstance(v, (str, int, float, bool)) or v is None
                }
            elif isinstance(value, list):
                summary[field] = [
                    item[:160] if isinstance(item, str) else item
                    for item in value[:6]
                    if isinstance(item, (str, int, float, bool)) or item is None
                ]
        if summary:
            result["result_summary"] = summary
    return result


def _image_response(
    message: str,
    image_options: dict[str, Any],
    session_id: str,
    session: dict[str, Any],
    request_id: str,
    base_url: str,
):
    try:
        asset = generate_image_asset(
            message,
            image_options=image_options,
            request_base_url=base_url,
            request_id=request_id,
        )
    except ValueError as exc:
        return _error("IMAGE_REQUEST_INVALID", str(exc), 400, request_id)
    except Exception:
        logger.exception("Image generation failed | request_id=%s", request_id)
        return _error(
            "IMAGE_GENERATION_FAILED",
            "RevelaAI could not generate the requested design.",
            502,
            request_id,
        )

    save_image_conversation(session_id, session, message, success=True)
    response = enforce_base_schema(
        query=message,
        mode="image",
        data={
            "type": "image",
            "format": asset["asset_type"],
            "urls": [asset["image_url"]],
        },
        sources=[],
        meta={
            "provider": "huggingface" if asset["asset_type"] == "png" else "huggingface-svg",
            "model": configured_image_model() if asset["asset_type"] == "png" else None,
            "build_id": REVELAAI_BUILD_ID,
            "image_engine": asset["image_plan"].get("engine"),
            "engine_version": REVELAAI_IMAGE_ENGINE_VERSION,
            "intent": "image_generation",
            "design": asset["image_plan"],
            "image": {
                "width": asset["width"],
                "height": asset["height"],
                "aspect_ratio": asset["aspect_ratio"],
                "seed": asset["seed"],
                "text_aware": bool(asset["image_plan"].get("has_text")),
            },
            "multimodal": {
                "type": "image",
                "format": asset["asset_type"],
                "editable": asset["asset_type"] == "svg",
            },
        },
    )
    return JSONResponse(response, status_code=200)


def _ai_sync(
    payload: dict[str, Any],
    upload_name: str | None,
    upload_mime: str | None,
    upload_bytes: bytes | None,
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
    request_id: str,
    base_url: str,
):
    cleanup_generated_files()
    authorization = next(
        (str(v) for k, v in headers.items() if str(k).casefold() == "authorization"),
        "",
    )
    user_id = _subject_from_bearer(authorization)
    session_id = _session_id(headers, cookies, user_id)
    session = get_session(session_id)

    memory_user_oid = None
    if user_id:
        try:
            memory_user_oid, verified_id, auth_error = authenticate_identity(
                authorization, headers, payload
            )
            if auth_error or verified_id != user_id:
                memory_user_oid = None
                logger.info("Smart memory identity verification unavailable; AI continues without saved memory")
        except Exception:
            memory_user_oid = None
            logger.warning("Smart memory identity verification failed; continuing without saved memory", exc_info=True)

    message = ""
    attachment_metadata = None
    raw_client_context: Any = None
    brain_payload: dict[str, Any] = payload
    image_options: dict[str, Any] = {}

    if upload_name is not None:
        if not upload_bytes:
            return _error("INVALID_DOCUMENT", "Uploaded file is empty.", 400, request_id)
        if len(upload_bytes) > MAX_BODY_BYTES:
            return _error("REQUEST_TOO_LARGE", "The uploaded file or request exceeds the allowed size.", 413, request_id)
        file_storage = SimpleNamespace(
            filename=upload_name,
            mimetype=upload_mime or "application/octet-stream",
            read=lambda: upload_bytes,
        )
        brain_payload = {
            "hub": payload.get("hub", "general"),
            "visionDescription": payload.get("visionDescription", ""),
        }
        raw_client_context = payload.get("context", "") or ""
        try:
            image_options = parse_image_options({
                "aspect_ratio": payload.get("aspect_ratio"),
                "width": payload.get("width"),
                "height": payload.get("height"),
                "seed": payload.get("seed"),
            })
        except ValueError as exc:
            return _error("INVALID_IMAGE_OPTIONS", str(exc), 400, request_id)
        try:
            message, attachment_metadata = process_uploaded_document(
                file_storage,
                prompt=str(payload.get("message") or ""),
            )
        except ValueError as exc:
            return _error("INVALID_DOCUMENT", str(exc), 400, request_id)
        except RuntimeError as exc:
            return _error("DOCUMENT_PROCESSING_FAILED", str(exc), 502, request_id)
    else:
        message = str(payload.get("message") or "").strip()
        raw_client_context = payload.get("context", [])
        try:
            image_options = parse_image_options(payload)
        except ValueError as exc:
            return _error("INVALID_IMAGE_OPTIONS", str(exc), 400, request_id)

    if not message:
        return _error("EMPTY_MESSAGE", "Message or file required.", 400, request_id)
    if len(message) > 80_000:
        return _error("MESSAGE_TOO_LARGE", "Message exceeds the allowed size.", 413, request_id)

    try:
        previous_context, memory_source = resolve_conversation_context(
            session, raw_client_context
        )
        brain_context, interaction = build_global_context(
            message=message,
            hub=brain_payload.get("hub") or "auto",
            payload=brain_payload,
        )
        previous_context = (previous_context + [brain_context])[-MAX_HISTORY:]
        if memory_user_oid is not None:
            personalization = _load_personalization_context(memory_user_oid)
            if personalization:
                previous_context = (previous_context + [personalization])[-MAX_HISTORY:]

        intent = classify_intent(message)
        capability = detect_capability(message, intent=intent)
        image_request = capability == "image_generation"
        if image_request:
            intent = "image_generation"
        session["topic"] = intent

        if image_request:
            # Generation costs provider credits. Entitlements are checked against
            # RevelaCode's central service; outages fail closed for this premium
            # capability without breaking free text chat.
            _, entitlement_error = check_entitlement(
                authorization,
                hub="smart_ai",
                feature="image_generation",
            )
            if entitlement_error is not None:
                return entitlement_error
            return _image_response(
                message, image_options, session_id, session, request_id, base_url
            )

        session["messages"].append({"role": "user", "content": message})
        session["messages"] = session["messages"][-MAX_HISTORY:]

        lowered = message.lower()
        expert_payload = None
        if "law" in intent or "legal" in lowered:
            expert_payload = analyze_legal_query(message)
        elif "medical" in intent or "medicine" in lowered:
            expert_payload = analyze_medical_query(message)

        identity_reply = get_identity_answer(message, interaction.get("hub", "auto"))
        self_description_reply = get_self_description_answer(message)
        if identity_reply or self_description_reply:
            direct_reply = identity_reply or self_description_reply
            ai_result = {
                "response": direct_reply,
                "confidence": "high",
                "intent": "identity" if identity_reply else "self_description",
                "domain": interaction.get("hub", "auto"),
                "provider": "revelaai-manifest" if self_description_reply else "revelaai-hub-identity",
                "model": "agi-manifest-policy" if self_description_reply else "hub-identity-policy",
            }
        else:
            ai_result = process_message(
                message=message,
                context=previous_context,
                intent=intent,
                session_id=session_id,
                user_id=user_id,
                country=str(brain_payload.get("country") or "KE"),
                language=str(brain_payload.get("language") or ""),
            )

        if not isinstance(ai_result, dict):
            ai_result = {}
        if ai_result.get("action_required", False):
            action = ai_result.get("action") if isinstance(ai_result.get("action"), dict) else {}
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "image_generation":
                return _image_response(
                    message, image_options, session_id, session, request_id, base_url
                )
            return _error(
                "UNSUPPORTED_AI_ACTION",
                "RevelaAI recognized an unsupported executable action.",
                501,
                request_id,
            )

        assistant_text = str(ai_result.get("response") or "").strip()
        if ai_result.get("error") or not assistant_text:
            return _error(
                "MODEL_UNAVAILABLE",
                "RevelaAI's configured text model did not return a usable answer. Please try again shortly.",
                503,
                request_id,
            )

        requested_hub = interaction.get("hubRequested", "auto")
        selected_hub = interaction.get("hub", "general")
        if requested_hub == "auto" and selected_hub != "auto":
            route_tag = f"[Auto → {HUB_LABELS.get(selected_hub, selected_hub.title())}]"
            if not assistant_text.startswith("[Auto →"):
                assistant_text = route_tag + "\n\n" + assistant_text

        session["messages"].append({"role": "assistant", "content": assistant_text})
        if memory_user_oid is not None:
            _persist_turn(
                memory_user_oid,
                session_id,
                str(interaction.get("hub") or ai_result.get("domain") or intent or "general"),
                message,
                assistant_text,
            )
        save_session(session_id, session)

        wants_json = any(
            keyword in lowered for keyword in ("respond in json", "return json", "output json")
        )
        data = extract_json(assistant_text) if wants_json else {"content": assistant_text}
        if not isinstance(data, dict):
            data = {"content": assistant_text}
        if expert_payload:
            data["expert_module"] = expert_payload

        orchestrator_data = ai_result.get("orchestrator")
        if not isinstance(orchestrator_data, dict):
            orchestrator_data = {}
        online_data = orchestrator_data.get("online")
        if not isinstance(online_data, dict):
            online_data = {}
        sources = online_data.get("sources", [])
        if not isinstance(sources, list):
            sources = []

        core_mesh_raw = orchestrator_data.get("core_mesh", {})
        if not isinstance(core_mesh_raw, dict):
            core_mesh = {}
        else:
            raw_safety = core_mesh_raw.get("safety")
            if not isinstance(raw_safety, dict):
                raw_safety = {}
            core_mesh = {
                "mode": str(core_mesh_raw.get("mode") or "advisory_only")[:40],
                "target_core": str(core_mesh_raw.get("target_core") or "")[:40],
                "operation_kind": str(core_mesh_raw.get("operation_kind") or "")[:80],
                "execution_status": str(core_mesh_raw.get("execution_status") or "not_run")[:40],
                "failure_reason": str(core_mesh_raw.get("failure_reason") or "")[:100] or None,
                "selected_core": str(core_mesh_raw.get("selected_core") or "orchestrator")[:40],
                "route_reason": str(core_mesh_raw.get("route_reason") or "")[:280],
                "domain": str(core_mesh_raw.get("domain") or "general")[:80],
                "intent": str(core_mesh_raw.get("intent") or "general")[:80],
                "mesh_status": str(core_mesh_raw.get("mesh_status") or "not_probed")[:40],
                "cores": {
                    str(name)[:16]: {
                        "id": str(info.get("id") or "")[:40],
                        "status": str(info.get("status") or "unknown")[:40],
                        "reachable": info.get("reachable") if info.get("reachable") in (True, False, None) else None,
                        "version": str(info.get("version") or "")[:40],
                        "failure_reason": str(info.get("failure_reason") or "")[:100] or None,
                    }
                    for name, info in core_mesh_raw.get("cores", {}).items()
                    if isinstance(name, str) and isinstance(info, dict)
                } if isinstance(core_mesh_raw.get("cores"), dict) else {},
                "safety": {
                    "operation_executed": raw_safety.get("operation_executed") is True,
                    "target_mutation_performed": raw_safety.get("target_mutation_performed") is True,
                    "candidate_source_execution": raw_safety.get("candidate_source_execution") is True,
                    "human_approval_required": raw_safety.get("human_approval_required", True) is True,
                    "automatic_merge": raw_safety.get("automatic_merge") is True,
                    "automatic_execution": raw_safety.get("automatic_execution") is True,
                },
            }

        unknown = orchestrator_data.get("unknown_learning", {})
        if not isinstance(unknown, dict):
            unknown = {}
        unknown_public = {
            "is_unknown": bool(unknown.get("is_unknown", False)),
            "topic": str(unknown.get("topic") or "")[:120],
            "wisdom_score": unknown.get("wisdom_score"),
            "threshold": unknown.get("threshold", 0.5),
            "next_action": str(unknown.get("next_action") or "use_existing_knowledge")[:40],
            "automatic_retries": False,
            "known_matches": unknown.get("known_matches", [])[:3] if isinstance(unknown.get("known_matches"), list) else [],
        }

        meta = {
            "unknown_learning": unknown_public,
            "ai_model": ai_result.get("model"),
            "provider": ai_result.get("provider", get_active_text_provider()),
            "memory": {
                "enabled": True,
                "type": "conversation",
                "source": memory_source,
                "context_messages": len(previous_context),
                "session_id": session_id,
                "server_session": "bounded_in_memory",
                "browser_restore_supported": True,
            },
            "intent": ai_result.get("intent", intent),
            "domain": interaction.get("hub") or ai_result.get("domain", "general"),
            "hub": interaction.get("hub", "general"),
            "hub_used": interaction.get("hub", "general"),
            "hub_requested": interaction.get("hubRequested", "auto"),
            "hub_detected": interaction.get("hubDetected", "general"),
            "domains": ai_result.get("domains", []),
            "emotion": ai_result.get("emotion", "unknown"),
            "interaction_tone": interaction.get("interactionTone", "neutral"),
            "capabilities": interaction.get("capabilities", []),
            "confidence": ai_result.get("confidence", "medium"),
            "online": online_data,
            "biashara": orchestrator_data.get("biashara", {}),
            "agriculture": orchestrator_data.get("agriculture", {}),
            "ecosystem": orchestrator_data.get("ecosystem", {}),
            "multimodal": attachment_metadata or orchestrator_data.get("multimodal", {}),
            "usect_zero_tool": _safe_tool_metadata(ai_result),
            "core_mesh": core_mesh,
            "build_id": REVELAAI_BUILD_ID,
        }
        response_body = enforce_base_schema(
            query=message,
            mode=intent,
            data=data,
            sources=sources,
            meta=meta,
        )
        return JSONResponse(response_body, status_code=200)
    except Exception:
        logger.exception("Native /ai request failed | request_id=%s", request_id)
        return _error("SERVER_ERROR", "RevelaAI encountered an unexpected server error.", 500, request_id)


async def _parse_body(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return None, None, None, _error(
                    "REQUEST_TOO_LARGE",
                    "The uploaded file or request exceeds the allowed size.",
                    413,
                    getattr(request.state, "request_id", None),
                )
        except ValueError:
            return None, None, None, _error(
                "INVALID_CONTENT_LENGTH", "Invalid Content-Length header.", 400,
                getattr(request.state, "request_id", None),
            )

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "multipart/form-data":
        try:
            form = await request.form()
        except Exception:
            return None, None, None, _error(
                "INVALID_MULTIPART",
                "Unable to parse the uploaded form.",
                400,
                getattr(request.state, "request_id", None),
            )
        payload: dict[str, Any] = {str(k): v for k, v in form.multi_items() if isinstance(v, str)}
        uploaded = form.get("file") or form.get("attachment")
        if uploaded is None or not hasattr(uploaded, "read") or not getattr(uploaded, "filename", ""):
            return payload, None, None, None
        data = await uploaded.read()
        filename = str(uploaded.filename or "")
        mime = str(getattr(uploaded, "content_type", "") or "")
        try:
            await uploaded.close()
        except Exception:
            pass
        if len(data) > MAX_BODY_BYTES:
            return None, None, None, _error(
                "REQUEST_TOO_LARGE", "The uploaded file or request exceeds the allowed size.",
                413, getattr(request.state, "request_id", None),
            )
        return payload, (filename, mime), data, None

    try:
        body = await request.json()
    except Exception:
        body = {}
    return (body if isinstance(body, dict) else {}), None, None, None


@router.post("/ai")
async def ai_assistant(request: Request):
    payload, upload_meta, upload_bytes, error = await _parse_body(request)
    if error:
        return error
    if payload is None:
        payload = {}
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    upload_name, upload_mime = upload_meta if upload_meta else (None, None)
    return await run_in_threadpool(
        _ai_sync,
        payload,
        upload_name,
        upload_mime,
        upload_bytes,
        dict(request.headers),
        dict(request.cookies),
        request_id,
        str(request.base_url),
    )
