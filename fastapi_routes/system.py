"""Native FastAPI system routes for health, readiness, capabilities, and safe media delivery."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from services.conversation_store import MAX_HISTORY, MAX_SESSIONS, SESSION_MEMORY, SESSION_TTL_SECONDS
from services.feature_registry import FEATURES
from services.image_service import is_image_generation_request
from services.runtime_config import (
    APP_NAME, AUDIO_DIR, ENVIRONMENT, IMAGE_DIR, REVELAAI_BUILD_ID,
    REVELAAI_ENABLE_HF_TTS, REVELAAI_IMAGE_ENGINE_VERSION,
    cleanup_generated_files, get_active_text_model,
    get_active_text_provider, get_revelaai_text_status,
)
from ai.ai_client import get_image_provider_status, get_text_provider_status, hf_configured
from ai.json_utils import error_response

router = APIRouter(tags=["System"])
logger = logging.getLogger("revelaai.fastapi.system")


def _online_research_available() -> bool:
    try:
        from services.scraper import get_live_research, is_realtime_query
        return callable(get_live_research) and callable(is_realtime_query)
    except Exception:
        return False


def _pdf_available() -> bool:
    try:
        from ai.pdf_processor import process_pdf
        return callable(process_pdf)
    except Exception:
        return False


@router.get("/")
def root():
    return {
        "status": "success",
        "service": "revelaai",
        "app": APP_NAME,
        "environment": ENVIRONMENT,
        "build_id": REVELAAI_BUILD_ID,
        "text_provider": get_active_text_provider(),
        "text_model": get_active_text_model(),
        "image_engine": REVELAAI_IMAGE_ENGINE_VERSION,
        "message": "RevelaAI is live.",
    }


@router.get("/capabilities")
def capabilities():
    text_status = get_revelaai_text_status()
    active_provider = get_active_text_provider()
    active_model = get_active_text_model()
    providers = text_status.get("providers", {})
    gemini = providers.get("gemini", {}) if isinstance(providers, dict) else {}
    gemini = gemini if isinstance(gemini, dict) else {}
    image_status = get_image_provider_status()
    return {
        "status": "success",
        "service": "revelaai",
        "build_id": REVELAAI_BUILD_ID,
        "capabilities": {
            "text": {
                "enabled": active_provider != "none",
                "provider": active_provider,
                "model": active_model,
                "fallback_available": bool(gemini.get("fallback_model")),
                "providers": text_status,
            },
            "image_generation": {
                "enabled": True,
                "status": "ready" if image_status.get("enabled") else "partial",
                "provider": "pollinations",
                "raster": image_status,
                "structured_vector": {"enabled": True, "provider": "revelaai-svg"},
                "routing": {
                    "primary": "ai-client", "planner": "image_prompt",
                    "text_aware": True, "fallback": True,
                    "provider_aware": True, "server_execution": True,
                },
                "engines": {"raster": "pollinations", "structured_vector": "revelaai-svg"},
                "formats": [
                    "square", "portrait", "landscape", "wide", "story", "banner",
                    "social_portrait", "presentation", "phone",
                ],
                "canva_style": {
                    "enabled": True, "planner": "image_planner",
                    "structured_svg": True, "editable_assets": True,
                },
            },
            "online_research": {
                "enabled": True,
                "available": _online_research_available(),
                "provider": "services.scraper",
            },
            "pdf": {
                "enabled": True,
                "available": _pdf_available(),
                "processor": "PyMuPDF",
            },
            "voice": {
                "enabled": bool(hf_configured()),
                "provider": "huggingface",
                "asr_model": os.getenv("HF_ASR_MODEL", "openai/whisper-large-v3"),
                "tts_model": os.getenv("HF_TTS_MODEL", "hexgrad/Kokoro-82M"),
                "tts_enabled": REVELAAI_ENABLE_HF_TTS,
            },
            "ecosystem": {
                "enabled": True,
                "provider": "RevelaCode Backend",
                "gateway": "services.ai_service",
                "user_identity": "RevelaCode JWT",
                "domains": ["theology", "elimu", "shamba", "biashara", "community"],
            },
        },
    }


@router.get("/health")
def health():
    """Keep the public health response shape; optional modules degrade independently."""
    text_status = get_revelaai_text_status()
    active_provider = get_active_text_provider()
    active_model = get_active_text_model()
    image_status = get_image_provider_status()
    return {
        "status": "ok",
        "service": "revelaai",
        "environment": ENVIRONMENT,
        "build": {
            "id": REVELAAI_BUILD_ID,
            "image_routing": "ai-client-managed",
            "image_engine": REVELAAI_IMAGE_ENGINE_VERSION,
            "conversation_memory": "client-context-plus-session",
            "capability_routing": "server-authoritative",
        },
        "providers": {
            "text": {
                "provider": active_provider,
                "configured": active_provider != "none",
                "model": active_model,
                "status": text_status,
            },
            "image": {
                "provider": "pollinations",
                "configured": bool(image_status.get("enabled")),
                "primary_model": image_status.get("model"),
                "status": image_status,
                "structured_vector": {"enabled": True, "provider": "revelaai-svg"},
                "routing": {
                    "owner": "ai_client", "planner": "image_prompt",
                    "text_aware": True, "fallback": True,
                    "provider_aware": True, "server_execution": True,
                },
                "structured_svg": True,
            },
            "voice": {
                "provider": "huggingface",
                "configured": hf_configured(),
                "asr_model": os.getenv("HF_ASR_MODEL", "openai/whisper-large-v3"),
                "tts_model": os.getenv("HF_TTS_MODEL", "hexgrad/Kokoro-82M"),
                "tts_enabled": REVELAAI_ENABLE_HF_TTS,
            },
        },
        "online_research": {"available": _online_research_available()},
        "pdf": {"available": _pdf_available()},
        "ecosystem": {
            "enabled": True,
            "gateway": "services.ai_service",
            "authenticated_user_bridge": "RevelaCode JWT -> user_id",
            "domains": ["theology", "elimu", "shamba", "biashara", "community"],
        },
        "features_loaded": len(FEATURES),
        "session_memory": {
            "active_sessions": len(SESSION_MEMORY),
            "max_sessions": MAX_SESSIONS,
            "ttl_seconds": SESSION_TTL_SECONDS,
            "max_history_messages": MAX_HISTORY,
            "server_storage": "in_memory",
            "browser_context_supported": True,
        },
    }


@router.get("/ready")
def ready():
    provider = get_active_text_provider()
    model = get_active_text_model()
    provider_status = get_text_provider_status()
    image_status = get_image_provider_status()
    configured_providers = provider_status.get("providers", {})
    gemini_validation = provider_status.get("gemini_model_validation", {})
    provider_checks: dict[str, Any] = {}
    for public_name, status_name in (("gemini", "gemini"), ("hf", "huggingface"), ("mvi", "mvi")):
        info = configured_providers.get(status_name, {}) if isinstance(configured_providers, dict) else {}
        info = info if isinstance(info, dict) else {}
        is_configured = bool(info.get("configured"))
        provider_checks[public_name] = {
            "configured": is_configured,
            # Only Gemini currently has a startup reachability/model-list probe.
            "reachable": gemini_validation.get("reachable") if public_name == "gemini" else (None if is_configured else False),
            "model_valid": gemini_validation.get("model_valid") if public_name == "gemini" else (False if not is_configured else None),
            "model": info.get("primary_model") or info.get("model"),
        }
    checks: dict[str, Any] = {
        "providers": provider_checks,
        "text_provider": provider != "none",
        "text_model": bool(model),
        "huggingface": hf_configured(),
        "image_model": bool(image_status.get("enabled")),
        "structured_svg": True,
        "online_research": _online_research_available(),
        "pdf_processor": _pdf_available(),
    }
    core_ready = bool(checks["text_provider"] and checks["text_model"])
    selected_validation = (
        gemini_validation
        if provider == "gemini" and isinstance(gemini_validation, dict)
        else {}
    )
    readiness_evidence = (
        "gemini_model_list_validated"
        if selected_validation.get("reachable") is True and selected_validation.get("model_valid") is True
        else "provider_configured_generation_not_live_tested"
    )
    return JSONResponse(
        {
            "status": "ready" if core_ready else "degraded",
            "service": "revelaai",
            "build_id": REVELAAI_BUILD_ID,
            "text": {"provider": provider, "model": model},
            "checks": checks,
            "core": {
                "ready": core_ready,
                "text_required": True,
                "huggingface_multimodal_optional": True,
            "readiness_evidence": readiness_evidence,
            "generation_smoke_test_performed": False,
            },
        },
        status_code=200 if core_ready else 503,
    )


@router.get("/api/brain/status")
def brain_runtime_status():
    """Credential-free view of the director, provider chain, ecosystem and body cores."""
    provider_status = get_text_provider_status()
    active_provider = get_active_text_provider()
    active_model = get_active_text_model()

    try:
        from ai.ecosystem import ecosystem
        ecosystem_domains = ecosystem.domains()
    except Exception:
        ecosystem_domains = []

    try:
        from revelai.core.brain_os import capability_inventory
        inventory = capability_inventory()
    except Exception:
        inventory = {"capabilities": {}, "interpretation": "Inventory unavailable."}

    try:
        from ai.core_mesh import get_core_mesh_dashboard
        mesh = get_core_mesh_dashboard()
    except Exception as exc:
        mesh = {"status": "unavailable", "error_code": type(exc).__name__, "cores": {}}

    providers = provider_status.get("providers", {})
    providers = providers if isinstance(providers, dict) else {}
    gemini_status = providers.get("gemini", {})
    gemini_status = gemini_status if isinstance(gemini_status, dict) else {}
    gemini_validation = provider_status.get("gemini_model_validation", {})
    gemini_validation = gemini_validation if isinstance(gemini_validation, dict) else {}

    return {
        "status": "success",
        "service": "revelaai",
        "brain": {
            "director": "ai.orchestrator.Orchestrator",
            "global_adapter": "ai.global_brain_adapter.build_global_context",
            "decision_flow": [
                "global_brain_adapter",
                "intent_and_capability_routing",
                "orchestrator_context_assembly",
                "specialist_and_core_dispatch",
                "gemini_first_text_generation",
                "response_validation_and_memory",
                "brain_os_outcome_telemetry",
            ],
            "active_text_provider": active_provider,
            "active_text_model": active_model,
            "text_provider_configured": active_provider != "none" and bool(active_model),
            "gemini": {
                "enabled": gemini_status.get("enabled") is True,
                "model_validation": gemini_validation,
            },
            "provider_chain": provider_status,
            "ecosystem_domains": ecosystem_domains,
            "source_inventory": inventory,
            "body_cores": mesh,
            "safety": {
                "tool_dispatch_is_server_side": True,
                "signed_tool_registry_required": True,
                "human_approval_for_consequential_changes": True,
                "automatic_merge": False,
                "automatic_production_mutation": False,
            },
            "verification_note": (
                "Provider configuration and Gemini ListModels validation are separate evidence levels. "
                "This endpoint does not spend tokens on a synthetic generation request."
            ),
        },
    }


@router.post("/chat")
async def feature_chat(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    user_input = str(payload.get("message") or "").strip()
    if not user_input:
        return JSONResponse(error_response("EMPTY_MESSAGE", "Message required."), status_code=400)
    if is_image_generation_request(user_input):
        return {
            "status": "success",
            "mode": "image_generation",
            "message": "Use the /ai endpoint for image-generation requests.",
            "request_id": getattr(request.state, "request_id", None)
                or request.headers.get("X-Request-ID"),
            "build_id": REVELAAI_BUILD_ID,
        }

    def run_features():
        responses = {}
        for name, feature in FEATURES.items():
            try:
                responses[name] = feature.run(user_input)
            except Exception:
                logger.warning("Dynamic feature failed | feature=%s", name, exc_info=True)
                responses[name] = {"error": "Feature execution failed."}
        return responses

    responses = await run_in_threadpool(run_features)
    return {
        "status": "success",
        "input": user_input,
        "features_used": list(FEATURES.keys()),
        "responses": responses,
        "request_id": getattr(request.state, "request_id", None)
            or request.headers.get("X-Request-ID"),
        "build_id": REVELAAI_BUILD_ID,
    }


def _safe_generated_file(filename: str, directory: str, allowed_types: dict[str, str], not_found_code: str, not_found_message: str, allow_unknown_type: bool = False):
    cleanup_generated_files()
    safe_filename = os.path.basename(filename)
    if safe_filename != filename:
        return JSONResponse(
            {
                "status": "error",
                "error": {"code": "INVALID_FILENAME", "message": f"Invalid {('image' if not_found_code == 'IMAGE_NOT_FOUND' else 'audio')} filename."},
                "build_id": REVELAAI_BUILD_ID,
            },
            status_code=400,
        )
    filepath = os.path.join(directory, safe_filename)
    if not os.path.isfile(filepath):
        return JSONResponse(
            {
                "status": "error",
                "error": {"code": not_found_code, "message": not_found_message},
                "build_id": REVELAAI_BUILD_ID,
            },
            status_code=404,
        )
    media_type = allowed_types.get(Path(safe_filename).suffix.lower())
    if media_type is None and allow_unknown_type:
        media_type = "application/octet-stream"
    if media_type is None:
        return JSONResponse(
            {
                "status": "error",
                "error": {
                    "code": "UNSUPPORTED_IMAGE_FORMAT" if not_found_code == "IMAGE_NOT_FOUND" else "UNSUPPORTED_AUDIO_FORMAT",
                    "message": "Unsupported generated image format." if not_found_code == "IMAGE_NOT_FOUND" else "Unsupported generated audio format.",
                },
                "build_id": REVELAAI_BUILD_ID,
            },
            status_code=415,
        )
    return FileResponse(filepath, media_type=media_type, headers={"Cache-Control": "public, max-age=300"})


@router.get("/ai/images/{filename}")
def serve_generated_image(filename: str):
    return _safe_generated_file(
        filename,
        IMAGE_DIR,
        {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"},
        "IMAGE_NOT_FOUND",
        "Image not found.",
    )


@router.get("/voice/audio/{filename}")
def serve_audio(filename: str):
    return _safe_generated_file(
        filename,
        AUDIO_DIR,
        {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/opus", ".flac": "audio/flac", ".webm": "audio/webm"},
        "AUDIO_NOT_FOUND",
        "Audio not found.",
        allow_unknown_type=True,
    )
