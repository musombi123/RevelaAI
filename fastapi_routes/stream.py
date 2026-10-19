"""Native FastAPI Server-Sent Events endpoint for text and image generation."""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Iterator

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

import app as legacy
from services.conversation_store import MAX_HISTORY, get_session, resolve_conversation_context, save_session

router = APIRouter(tags=["AI Streaming"])
logger = logging.getLogger("revelaai.fastapi.stream")
MAX_BODY_BYTES = int(getattr(legacy, "MAX_CONTENT_LENGTH", 12 * 1024 * 1024))


def _subject(headers: Mapping[str, str]) -> str | None:
    authorization = next(
        (str(v) for k, v in headers.items() if str(k).casefold() == "authorization"),
        "",
    ).strip()
    secret = str(getattr(legacy, "JWT_SECRET", "") or "").strip()
    if not secret or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        return None
    try:
        claims = jwt.decode(
            authorization[7:].strip(),
            secret,
            algorithms=[getattr(legacy, "JWT_ALGORITHM", "HS256")],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    value = claims.get("sub") or claims.get("user_id") or claims.get("id")
    return str(value).strip() if value is not None and str(value).strip() else None


def _session_id(headers: Mapping[str, str], cookies: Mapping[str, str], subject: str | None) -> str:
    header_id = next(
        (str(v).strip() for k, v in headers.items() if str(k).casefold() == "x-session-id"),
        "",
    )
    session_id = (header_id or str(cookies.get("revelaai_session") or "").strip() or uuid.uuid4().hex)[:128]
    if subject:
        session_id = f"{subject}:{session_id}"[:128]
    return session_id


def _sse(event: str, payload: Any) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _image_payload(message: str, asset: dict[str, Any], session_id: str, memory_source: str, previous_context: list[dict[str, Any]]) -> dict[str, Any]:
    asset_type = asset["asset_type"]
    plan = asset["image_plan"]
    return {
        "success": True,
        "mode": "image",
        "query": message,
        "data": {
            "type": "image",
            "format": asset_type,
            "urls": [asset["image_url"]],
        },
        "sources": [],
        "meta": {
            "provider": "huggingface" if asset_type == "png" else "huggingface-svg",
            "model": legacy.configured_image_model() if asset_type == "png" else None,
            "build_id": legacy.REVELAAI_BUILD_ID,
            "intent": "image_generation",
            "image_engine": plan.get("engine"),
            "engine_version": legacy.REVELAAI_IMAGE_ENGINE_VERSION,
            "memory": {
                "enabled": True,
                "type": "conversation",
                "source": memory_source,
                "context_messages": len(previous_context),
                "session_id": session_id,
            },
            "design": plan,
            "image": {
                "width": asset["width"],
                "height": asset["height"],
                "aspect_ratio": asset["aspect_ratio"],
                "seed": asset["seed"],
            },
            "multimodal": {
                "type": "image",
                "format": asset_type,
                "editable": asset_type == "svg",
            },
        },
    }


@router.post("/ai/stream")
async def ai_stream(request: Request):
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    legacy.error_response("REQUEST_TOO_LARGE", "The request exceeds the allowed size."),
                    status_code=413,
                )
        except ValueError:
            return JSONResponse(
                legacy.error_response("INVALID_CONTENT_LENGTH", "Invalid Content-Length header."),
                status_code=400,
            )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    message = str(payload.get("message") or "").strip()
    if not message:
        return JSONResponse(legacy.error_response("EMPTY_MESSAGE", "Message required."), status_code=400)
    try:
        image_options = legacy.parse_image_options(payload)
    except ValueError as exc:
        return JSONResponse(
            legacy.error_response("INVALID_IMAGE_OPTIONS", str(exc)),
            status_code=400,
        )

    headers = dict(request.headers)
    cookies = dict(request.cookies)
    subject = _subject(headers)
    session_id = _session_id(headers, cookies, subject)
    session = get_session(session_id)
    raw_client_context = payload.get("context", [])
    previous_context, memory_source = resolve_conversation_context(
        session, raw_client_context
    )
    intent = legacy.classify_intent(message)
    capability = legacy.detect_capability(message, intent=intent)
    image_request = capability == "image_generation"
    if image_request:
        intent = "image_generation"
    session["topic"] = intent
    base_url = str(request.base_url)

    if image_request:
        def generate_image_stream() -> Iterator[str]:
            try:
                asset = legacy.generate_image_asset(
                    message,
                    image_options=image_options,
                    request_base_url=base_url,
                    request_id=request_id,
                )
                session["messages"].append({"role": "user", "content": message})
                session["messages"].append({
                    "role": "assistant",
                    "content": f"Generated a design based on the request: {message}",
                })
                save_session(session_id, session)
                yield _sse("image", _image_payload(message, asset, session_id, memory_source, previous_context))
                yield _sse("done", "[DONE]")
            except ValueError as exc:
                logger.warning("AI stream image request invalid | request_id=%s", request_id)
                yield _sse("error", {
                    "success": False,
                    "code": "IMAGE_REQUEST_INVALID",
                    "message": str(exc),
                })
            except Exception:
                logger.exception("AI stream image failed | request_id=%s", request_id)
                yield _sse("error", {
                    "success": False,
                    "code": "IMAGE_GENERATION_FAILED",
                    "message": "Image generation failed.",
                })

        response = StreamingResponse(generate_image_stream(), media_type="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    session["messages"].append({"role": "user", "content": message})
    session["messages"] = session["messages"][-MAX_HISTORY:]
    save_session(session_id, session)

    def generate() -> Iterator[str]:
        try:
            ai_result = legacy.process_message(
                message=message,
                context=previous_context,
                intent=intent,
                session_id=session_id,
                user_id=subject,
            )
            if not isinstance(ai_result, dict):
                ai_result = {}
            if ai_result.get("action_required", False):
                action = ai_result.get("action") if isinstance(ai_result.get("action"), dict) else {}
                action_type = str(action.get("type") or "").strip().lower()
                if action_type == "image_generation":
                    asset = legacy.generate_image_asset(
                        message,
                        image_options=image_options,
                        request_base_url=base_url,
                        request_id=request_id,
                    )
                    session["messages"].append({
                        "role": "assistant",
                        "content": f"Generated a design based on the request: {message}",
                    })
                    save_session(session_id, session)
                    yield _sse("image", _image_payload(message, asset, session_id, memory_source, previous_context))
                    yield _sse("done", "[DONE]")
                    return
                yield _sse("error", {
                    "success": False,
                    "code": "UNSUPPORTED_AI_ACTION",
                    "message": "RevelaAI recognized an unsupported action.",
                })
                return

            response_text = str(ai_result.get("response") or "").strip() or "No response generated."
            session["messages"].append({"role": "assistant", "content": response_text})
            save_session(session_id, session)
            yield _sse("message", response_text)
            metadata = {
                "intent": ai_result.get("intent", intent),
                "domain": ai_result.get("domain", "general"),
                "provider": ai_result.get("provider", legacy.get_active_text_provider()),
                "model": ai_result.get("model", legacy.get_active_text_model()),
                "capability": ai_result.get("capability", "text"),
                "build_id": legacy.REVELAAI_BUILD_ID,
                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": memory_source,
                    "context_messages": len(previous_context),
                    "session_id": session_id,
                },
            }
            yield _sse("metadata", metadata)
            yield _sse("done", "[DONE]")
        except Exception:
            logger.exception("AI stream failed | request_id=%s", request_id)
            yield _sse("error", {
                "success": False,
                "code": "STREAM_REQUEST_FAILED",
                "message": "RevelaAI could not complete the request.",
            })

    response = StreamingResponse(generate(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response
