"""Authenticated, ephemeral model-based analysis of explicitly shared camera frames.

Frames are accepted only during a user-initiated request, are sent to the configured
Gemini provider for scene understanding, and are never persisted by this endpoint.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request
from PIL import Image, UnidentifiedImageError

from ai.ai_client import (
    GEMINI_API_BASE_URL,
    GEMINI_API_KEY,
    GEMINI_ENABLED,
    GEMINI_MODEL,
    get_gemini_headers,
)
from routes.memory_routes import _require_identity

vision_bp = Blueprint("vision_bp", __name__)
logger = logging.getLogger("revelaai.vision")

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
DEFAULT_PROMPT = (
    "Describe the visible surroundings, objects, readable text, layout, and notable "
    "hazards. State uncertainty when details are unclear. Do not identify people or "
    "infer sensitive traits. Do not claim anything that cannot be supported by the frame."
)
VISION_SYSTEM_INSTRUCTION = (
    "You are RevelaAI Live Vision. Analyze only the image attached to this request. "
    "Describe directly visible evidence, distinguish observations from guesses, and "
    "state when an object or detail is unclear. Never claim continuous awareness between "
    "frames. Do not identify people, infer sensitive personal traits, or overstate safety "
    "certainty. Keep the answer useful and concise."
)


def _decode_image(payload: dict) -> tuple[str, bytes]:
    """Validate and decode a small supported image. Never log or persist its bytes."""
    image_value = payload.get("image")
    mime_type = str(payload.get("mimeType") or "").strip().lower()

    if not isinstance(image_value, str) or not image_value.strip():
        raise ValueError("image is required")

    if image_value.startswith("data:"):
        header, separator, encoded = image_value.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("image must be base64 encoded")
        declared_mime = header[5:].split(";", 1)[0].lower()
        if mime_type and declared_mime != mime_type:
            raise ValueError("image MIME type does not match its data URL")
        mime_type = declared_mime
        image_value = encoded

    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError("mimeType must be image/jpeg, image/png, or image/webp")

    # Reject unreasonable input before allocating decoded bytes.
    if len(image_value) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8:
        raise ValueError("image exceeds the 4 MB limit")

    try:
        image_bytes = base64.b64decode(image_value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image is not valid base64") from exc

    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("image must be non-empty and no larger than 4 MB")

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            format_mime = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(str(image.format or "").upper())
            if format_mime != mime_type:
                raise ValueError("mimeType does not match the actual image format")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("image dimensions are invalid or too large")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("image content is invalid or unsupported") from exc

    return mime_type, image_bytes


@vision_bp.post("/analyze")
def analyze_camera_frame():
    """Analyze a single explicitly submitted camera frame without retaining media."""
    user_oid, user_id, auth_error = _require_identity()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "code": "invalid_json", "message": "A JSON body is required."}), 400

    requested_user = str(payload.get("userId") or payload.get("user_id") or "").strip()
    if requested_user and requested_user != str(user_id):
        return jsonify({"status": "error", "code": "user_identity_mismatch", "message": "The requested user does not match the authenticated account."}), 403

    try:
        mime_type, image_bytes = _decode_image(payload)
    except ValueError as exc:
        return jsonify({"status": "error", "code": "invalid_image", "message": str(exc)}), 400

    prompt = str(payload.get("prompt") or DEFAULT_PROMPT).strip()
    if not prompt:
        prompt = DEFAULT_PROMPT
    if len(prompt) > 1200:
        return jsonify({"status": "error", "code": "prompt_too_long", "message": "Prompt must be 1,200 characters or fewer."}), 413

    if not GEMINI_ENABLED or not GEMINI_API_KEY or not GEMINI_MODEL:
        return jsonify({
            "status": "error",
            "code": "vision_provider_not_configured",
            "message": "Live Vision is unavailable because the server vision provider is not configured.",
        }), 503

    request_body = {
        "systemInstruction": {
            "parts": [{"text": VISION_SYSTEM_INSTRUCTION}]
        },
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }},
            ],
        }],
        # Gemini 3.6+ models deprecate sampling parameters; omit temperature/topP/topK.
        # candidateCount also defaults to 1, so keep the request model-compatible.
        "generationConfig": {
            "maxOutputTokens": 768,
        },
    }

    encoded_model = quote(GEMINI_MODEL, safe="")
    url = f"{GEMINI_API_BASE_URL.rstrip('/')}/{encoded_model}:generateContent"

    try:
        response = requests.post(
            url,
            headers=get_gemini_headers(),
            json=request_body,
            timeout=(10, 40),
        )
    except Exception as exc:
        logger.warning("Live Vision provider request failed | error_type=%s", type(exc).__name__)
        return jsonify({
            "status": "error",
            "code": "vision_provider_unavailable",
            "message": "Live Vision could not reach its configured model. Please try again.",
        }), 503

    if not response.ok:
        provider_status = int(response.status_code)
        try:
            provider_body = response.json()
            provider_error = provider_body.get("error", {}) if isinstance(provider_body, dict) else {}
            provider_code = str(provider_error.get("status") or provider_error.get("code") or "")[:80]
        except (ValueError, TypeError, AttributeError):
            provider_code = ""

        # Log only upstream status/code, never request bodies, image bytes, or credentials.
        logger.warning(
            "Live Vision provider rejected request | http_status=%s | provider_code=%s",
            provider_status,
            provider_code or "unreported",
        )

        if provider_status in {401, 403}:
            error_code = "vision_provider_auth_failed"
            message = "The vision provider rejected its server credentials. Check GEMINI_API_KEY and project access in the backend deployment."
        elif provider_status == 404:
            error_code = "vision_model_not_found"
            message = "The configured Gemini model was not found or is unavailable to this API project. Check GEMINI_MODEL in the backend deployment."
        elif provider_status == 429:
            error_code = "vision_rate_limited"
            message = "The vision model is rate-limited or its quota is exhausted. Check Gemini API quota and retry shortly."
        elif provider_status in {400, 422}:
            error_code = "vision_provider_request_rejected"
            message = "Gemini rejected the Live Vision request. The endpoint now omits deprecated sampling settings; verify model access and retry."
        elif provider_status in {500, 502, 503, 504}:
            error_code = "vision_provider_unavailable"
            message = "The Gemini vision service is temporarily unavailable. Please retry shortly."
        else:
            error_code = "vision_provider_error"
            message = "The Gemini vision provider could not analyze this frame. Check the backend provider configuration."

        status = 503 if provider_status in {429, 500, 502, 503, 504} else 502
        return jsonify({
            "status": "error",
            "code": error_code,
            "message": message,
            "providerStatus": provider_status,
        }), status

    try:
        body = response.json()
        candidates = body.get("candidates") if isinstance(body, dict) else None
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        reply = "\n".join(
            str(part.get("text") or "").strip()
            for part in parts
            if isinstance(part, dict) and str(part.get("text") or "").strip()
        ).strip()
    except (ValueError, TypeError, IndexError, AttributeError):
        reply = ""

    if not reply:
        return jsonify({
            "status": "error",
            "code": "empty_vision_response",
            "message": "The vision model returned no usable description. Try another frame.",
        }), 502

    # Deliberately do not write image bytes, prompts, or model output to persistent memory.
    return jsonify({
        "status": "success",
        "data": {
            "reply": reply,
            "provider": "gemini",
            "model": GEMINI_MODEL,
            "visionUsed": True,
            "mediaRetained": False,
        },
    }), 200
