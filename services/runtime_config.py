"""Framework-neutral runtime configuration for the RevelaAI gateway.

This module contains environment-backed settings and provider diagnostics only.
It has no Flask dependency and is shared by the ASGI entry point and legacy
compatibility adapter.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from ai.ai_client import get_image_provider_status, get_text_provider_status, hf_configured

load_dotenv()
logger = logging.getLogger("revelaai.runtime")

BASE_DIR = Path(__file__).resolve().parent.parent
APP_NAME = (os.getenv("APP_NAME", "RevelaAI").strip() or "RevelaAI")
ENVIRONMENT = (os.getenv("ENVIRONMENT", "production").strip().lower() or "production")
PORT = int(os.getenv("PORT", "5000"))
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(25 * 1024 * 1024)))
DOCUMENT_MAX_MODEL_CHARS = int(os.getenv("DOCUMENT_MAX_MODEL_CHARS", "90000"))
VOICE_MAX_BYTES = int(os.getenv("VOICE_MAX_BYTES", str(10 * 1024 * 1024)))
IMAGE_RETENTION_SECONDS = int(os.getenv("IMAGE_RETENTION_SECONDS", str(60 * 60)))
AUDIO_RETENTION_SECONDS = int(os.getenv("AUDIO_RETENTION_SECONDS", str(60 * 60)))

REVELAAI_BUILD_ID = (
    os.getenv("REVELAAI_BUILD_ID", "canva-image-v1-memory-v1-gemini-text-v2").strip()
    or "canva-image-v1-memory-v1-gemini-text-v2"
)
REVELAAI_ENABLE_HF_TTS = (
    os.getenv("REVELAAI_ENABLE_HF_TTS", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
REVELAAI_IMAGE_ENGINE_VERSION = (
    os.getenv("REVELAAI_IMAGE_ENGINE_VERSION", "canva-studio-v1").strip()
    or "canva-studio-v1"
)

DEFAULT_IMAGE_DIR = os.path.join(tempfile.gettempdir(), "revelaai_images")
DEFAULT_AUDIO_DIR = os.path.join(tempfile.gettempdir(), "revelaai_audio")
IMAGE_DIR = os.getenv("REVELAAI_IMAGE_DIR", DEFAULT_IMAGE_DIR).strip() or DEFAULT_IMAGE_DIR
AUDIO_DIR = os.getenv("REVELAAI_AUDIO_DIR", DEFAULT_AUDIO_DIR).strip() or DEFAULT_AUDIO_DIR
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)


def configured_image_model() -> str:
    """Report the model actually selected by ai.ai_client's image provider."""
    try:
        status = get_image_provider_status()
        model = status.get("model") if isinstance(status, dict) else None
        return str(model).strip() if model else ""
    except Exception as exc:
        logger.warning("Could not resolve image provider model | error_type=%s", type(exc).__name__)
        return ""


def get_revelaai_text_status() -> dict[str, Any]:
    """Return safe provider diagnostics without exposing credentials."""
    try:
        result = get_text_provider_status()
        if isinstance(result, dict):
            return result
        return {"provider_order": [], "providers": {}}
    except Exception as exc:
        logger.warning("Could not resolve text provider status | error_type=%s", type(exc).__name__)
        return {"provider_order": [], "providers": {}}


def get_active_text_provider() -> str:
    status = get_revelaai_text_status()
    order = status.get("provider_order", [])
    providers = status.get("providers", {})
    if not isinstance(order, list) or not isinstance(providers, dict):
        return "none"
    aliases = {
        "google": "gemini", "google-ai": "gemini", "googleai": "gemini",
        "hf": "huggingface", "hugging-face": "huggingface",
        "mvi-ai": "mvi", "mvi_ai": "mvi",
    }
    # Mirror ask_hf(): configured Gemini always precedes legacy provider order.
    gemini = providers.get("gemini", {})
    if isinstance(gemini, dict) and gemini.get("enabled") is True:
        return "gemini"
    for value in order:
        name = str(value or "").strip().lower()
        canonical = aliases.get(name, name)
        info = providers.get(canonical, {})
        if isinstance(info, dict) and info.get("enabled") is True:
            return canonical
    return "none"


def get_active_text_model() -> str | None:
    status = get_revelaai_text_status()
    provider = get_active_text_provider()
    providers = status.get("providers", {})
    if not isinstance(providers, dict):
        return None
    canonical = {
        "hf": "huggingface", "hugging-face": "huggingface",
        "google": "gemini", "google-ai": "gemini", "googleai": "gemini",
        "mvi-ai": "mvi", "mvi_ai": "mvi",
    }.get(provider, provider)
    info = providers.get(canonical, {})
    if not isinstance(info, dict):
        return None
    model = info.get("primary_model") or info.get("model")
    return str(model) if model else None


def cleanup_generated_files() -> None:
    """Delete expired generated media; never follow directories or arbitrary paths."""
    now = time.time()
    for directory, retention in (
        (IMAGE_DIR, IMAGE_RETENTION_SECONDS),
        (AUDIO_DIR, AUDIO_RETENTION_SECONDS),
    ):
        try:
            for path in Path(directory).iterdir():
                try:
                    if path.is_file() and now - path.stat().st_mtime > retention:
                        path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    continue
        except OSError:
            continue
