"""Native FastAPI voice endpoint.

Audio uploads are bounded and processed in memory. Generated speech files are
temporary and are served by the native system router. This module deliberately
uses the existing shared session store and provider services without importing
Flask request globals.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import app as legacy
from services.conversation_store import MAX_HISTORY, build_server_context, get_session, save_session

router = APIRouter(tags=["Voice"])
logger = logging.getLogger("revelaai.fastapi.voice")
VOICE_MAX_BYTES = int(getattr(legacy, "VOICE_MAX_BYTES", 12 * 1024 * 1024))


def _error(code: str, message: str, status_code: int):
    return JSONResponse(
        {
            "status": "error",
            "error": {"code": code, "message": message},
            "build_id": legacy.REVELAAI_BUILD_ID,
        },
        status_code=status_code,
    )


def _subject_from_bearer(authorization: str) -> str | None:
    secret = str(getattr(legacy, "JWT_SECRET", "") or "").strip()
    header = str(authorization or "").strip()
    if not secret or not header.startswith("Bearer ") or not header[7:].strip():
        return None
    try:
        claims = jwt.decode(
            header[7:].strip(),
            secret,
            algorithms=[getattr(legacy, "JWT_ALGORITHM", "HS256")],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    value = claims.get("sub") or claims.get("user_id") or claims.get("id")
    return str(value).strip() if value is not None and str(value).strip() else None


def _session_id(request: Request, subject: str | None) -> str:
    value = (
        request.headers.get("X-Session-ID", "").strip()
        or request.cookies.get("revelaai_session", "").strip()
        or uuid.uuid4().hex
    )[:128]
    if subject:
        value = f"{subject}:{value}"[:128]
    return value


def _voice_sync(
    audio_bytes: bytes,
    content_type: str,
    subject: str | None,
    session_id: str,
    request_base_url: str,
):
    legacy.cleanup_generated_files()

    if not audio_bytes:
        return _error("EMPTY_AUDIO", "Uploaded audio is empty.", 400)
    if len(audio_bytes) > VOICE_MAX_BYTES:
        return _error("AUDIO_TOO_LARGE", "Audio exceeds the maximum allowed size.", 413)

    try:
        transcription = legacy.transcribe_hf_audio(audio_bytes)
    except Exception:
        logger.exception("Voice transcription failed")
        return _error("VOICE_TRANSCRIPTION_FAILED", "Voice transcription is temporarily unavailable.", 502)

    if not isinstance(transcription, dict):
        transcription = {"text": str(transcription or "")}
    heard = str(transcription.get("text") or "").strip()
    if not heard:
        return _error("EMPTY_TRANSCRIPTION", "No speech could be transcribed.", 400)

    session = get_session(session_id)
    previous_context = build_server_context(session)
    intent = legacy.classify_intent(heard)
    capability = legacy.detect_capability(heard, intent=intent)
    if capability == "image_generation":
        intent = "image_generation"
        try:
            asset = legacy.generate_image_asset(heard)
            session["messages"].append({"role": "user", "content": heard})
            session["messages"].append({
                "role": "assistant",
                "content": f"Generated a design based on the request: {heard}",
            })
            save_session(session_id, session)
            asset_type = str(asset.get("asset_type") or "png")
            return {
                "status": "success",
                "heard": heard,
                "response": "Image generated successfully.",
                "image_url": asset.get("image_url"),
                "asset_type": asset_type,
                "audio_url": None,
                "voice": {
                    "input": transcription,
                    "output": {"available": False, "reason": "image_generation_request"},
                },
                "meta": {
                    "intent": "image_generation",
                    "domain": "image",
                    "provider": "huggingface" if asset_type == "png" else "huggingface-svg",
                    "model": legacy.configured_image_model() if asset_type == "png" else None,
                    "build_id": legacy.REVELAAI_BUILD_ID,
                    "image_engine": (asset.get("image_plan") or {}).get("engine"),
                    "memory": {
                        "enabled": True,
                        "type": "conversation",
                        "source": "server_session",
                        "context_messages": len(previous_context),
                        "session_id": session_id,
                    },
                },
            }
        except Exception:
            logger.exception("Voice image generation failed")
            return _error("VOICE_IMAGE_GENERATION_FAILED", "Image generation is temporarily unavailable.", 502)

    session["topic"] = intent
    session["messages"].append({"role": "user", "content": heard})
    session["messages"] = session["messages"][-MAX_HISTORY:]

    try:
        ai_result = legacy.process_message(
            message=heard,
            context=previous_context,
            intent=intent,
            session_id=session_id,
            user_id=subject,
        )
    except Exception:
        logger.exception("Voice AI processing failed")
        return _error("VOICE_AI_FAILED", "RevelaAI could not process the transcribed request.", 502)

    if not isinstance(ai_result, dict):
        ai_result = {}
    if ai_result.get("action_required", False):
        action = ai_result.get("action") if isinstance(ai_result.get("action"), dict) else {}
        action_type = str(action.get("type") or "").strip().lower()
        if action_type == "image_generation":
            try:
                asset = legacy.generate_image_asset(heard)
                legacy.save_image_conversation(session_id, session, heard, success=True)
                asset_type = str(asset.get("asset_type") or "png")
                return {
                    "status": "success",
                    "heard": heard,
                    "response": "Image generated successfully.",
                    "image_url": asset.get("image_url"),
                    "asset_type": asset_type,
                    "audio_url": None,
                    "voice": {
                        "input": transcription,
                        "output": {"available": False, "reason": "image_generation_request"},
                    },
                    "meta": {
                        "intent": "image_generation",
                        "domain": "image",
                        "provider": "huggingface" if asset_type == "png" else "huggingface-svg",
                        "model": legacy.configured_image_model() if asset_type == "png" else None,
                        "build_id": legacy.REVELAAI_BUILD_ID,
                        "image_engine": (asset.get("image_plan") or {}).get("engine"),
                    },
                }
            except Exception:
                logger.exception("Voice executable image action failed")
                return _error("VOICE_IMAGE_GENERATION_FAILED", "Image generation failed.", 502)
        return _error("UNSUPPORTED_AI_ACTION", "RevelaAI recognized an unsupported action.", 501)

    response_text = str(ai_result.get("response") or "").strip()
    if not response_text:
        return _error("EMPTY_AI_RESPONSE", "RevelaAI returned an empty response.", 502)

    session["messages"].append({"role": "assistant", "content": response_text})
    save_session(session_id, session)

    provider = ai_result.get("provider", legacy.get_active_text_provider())
    model = ai_result.get("model", legacy.get_active_text_model())
    memory_meta = {
        "enabled": True,
        "type": "conversation",
        "source": "server_session",
        "context_messages": len(previous_context),
        "session_id": session_id,
    }

    if not legacy.REVELAAI_ENABLE_HF_TTS:
        return {
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,
            "voice": {
                "input": transcription,
                "output": {"available": False, "reason": "tts_disabled"},
            },
            "meta": {
                "intent": ai_result.get("intent", intent),
                "domain": ai_result.get("domain", "general"),
                "provider": provider,
                "model": model,
                "build_id": legacy.REVELAAI_BUILD_ID,
                "memory": memory_meta,
            },
        }

    try:
        audio_output = legacy.generate_hf_speech(response_text)
    except Exception:
        logger.exception("Voice synthesis failed")
        audio_output = None

    if not audio_output:
        reason = "tts_provider_failed" if audio_output is None else "empty_tts_response"
        return {
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,
            "voice": {
                "input": transcription,
                "output": {"available": False, "reason": reason},
            },
            "meta": {
                "intent": ai_result.get("intent", intent),
                "domain": ai_result.get("domain", "general"),
                "provider": provider,
                "model": model,
                "build_id": legacy.REVELAAI_BUILD_ID,
                "memory": memory_meta,
            },
        }

    mime_type = str(os.getenv("HF_TTS_MIME_TYPE", "audio/wav")).strip() or "audio/wav"
    extension = legacy.audio_extension_for_mime(mime_type)
    filename = f"revelaai_voice_{uuid.uuid4().hex}{extension}"
    output_path = Path(legacy.AUDIO_DIR) / filename
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_output)
    except Exception:
        logger.exception("Voice audio could not be saved")
        return {
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,
            "voice": {
                "input": transcription,
                "output": {"available": False, "reason": "audio_save_failed"},
            },
            "meta": {
                "intent": ai_result.get("intent", intent),
                "domain": ai_result.get("domain", "general"),
                "provider": provider,
                "model": model,
                "build_id": legacy.REVELAAI_BUILD_ID,
                "memory": memory_meta,
            },
        }

    return {
        "status": "success",
        "heard": heard,
        "response": response_text,
        "audio_url": request_base_url.rstrip("/") + "/voice/audio/" + filename,
        "voice": {
            "input": {
                "provider": "huggingface",
                "model": transcription.get("model"),
            },
            "output": {
                "provider": "huggingface",
                "model": os.getenv("HF_TTS_MODEL", "hexgrad/Kokoro-82M"),
                "mime_type": mime_type,
                "available": True,
            },
        },
        "meta": {
            "intent": ai_result.get("intent", intent),
            "domain": ai_result.get("domain", "general"),
            "provider": provider,
            "model": model,
            "build_id": legacy.REVELAAI_BUILD_ID,
            "memory": memory_meta,
        },
    }


@router.post("/voice")
async def voice(request: Request):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > VOICE_MAX_BYTES + 1024 * 1024:
                return _error("AUDIO_TOO_LARGE", "Audio exceeds the maximum allowed size.", 413)
        except ValueError:
            return _error("INVALID_CONTENT_LENGTH", "Invalid Content-Length header.", 400)
    try:
        form = await request.form()
    except Exception:
        return _error("AUDIO_REQUIRED", "No audio file was provided.", 400)

    uploaded = form.get("audio")
    if uploaded is None or not hasattr(uploaded, "read"):
        return _error("AUDIO_REQUIRED", "No audio file was provided.", 400)
    try:
        audio_bytes = await uploaded.read()
        if len(audio_bytes) > VOICE_MAX_BYTES:
            return _error("AUDIO_TOO_LARGE", "Audio exceeds the maximum allowed size.", 413)
        subject = _subject_from_bearer(request.headers.get("Authorization", ""))
        session_id = _session_id(request, subject)
        return await run_in_threadpool(
            _voice_sync,
            audio_bytes,
            getattr(uploaded, "content_type", "") or "",
            subject,
            session_id,
            str(request.base_url),
        )
    finally:
        try:
            await uploaded.close()
        except Exception:
            pass
