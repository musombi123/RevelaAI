"""
RevelaAI AI Client
==================

Production-side provider client for:

    - Text generation
    - Image generation
    - Speech recognition
    - Text-to-speech


Architecture
------------

                    RevelaAI
                       |
                  Orchestrator
                       |
                    AI Client
                       |
          +------------+----------------+
          |            |                |
          v            v                v
        Gemini         MVI          Hugging Face
        Text AI      Optional        Images/Voice
          |
          +--> Primary:
          |      Gemini 3.8 Flash
          |
          +--> Fallback:
                 Gemini 3.5 Flash-Lite


TEXT
----

Primary provider:
    Gemini API

Primary model:
    gemini-3.8-flash

Fallback model:
    gemini-3.5-flash-lite

MVI is intentionally NOT part of the default text path.

MVI remains available through:
    ask_mvi()

It may be explicitly enabled through:

    REVELAAI_TEXT_PROVIDERS=gemini,mvi


HUGGING FACE
------------

Hugging Face remains available for:

    - Images
    - ASR
    - TTS

HF_TOKEN must remain server-side.

Never expose HF_TOKEN to the frontend.


IMPORTANT
---------

The old hard-coded models are NOT used:

    openai/gpt-oss-120b:cheapest
    openai/gpt-oss-20b:cheapest


Existing public APIs are preserved:

    ask_hf()
    ask_gemini()
    ask_mvi()
    generate_image()
    generate_hf_image()
    transcribe_hf_audio()
    generate_hf_speech()
"""

from __future__ import annotations

import io
import os
import time
import wave
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# GENERAL CONFIGURATION
# =========================================================

REQUEST_USER_AGENT = (
    os.getenv(
        "REVELAAI_USER_AGENT",
        "RevelaAI/3.0",
    ).strip()
    or "RevelaAI/3.0"
)


# =========================================================
# GEMINI CONFIGURATION
# =========================================================
#
# Gemini is now the PRIMARY text provider.
#
# Current strategy:
#
#     Primary:
#         gemini-3.8-flash
#
#     Fallback:
#         gemini-3.5-flash-lite
#
# The values are configurable through Render environment
# variables without changing this file.
#

GEMINI_API_KEY = (
    os.getenv(
        "GEMINI_API_KEY",
        "",
    ).strip()
)

GEMINI_API_BASE_URL = (
    os.getenv(
        "GEMINI_API_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/models",
    ).strip()
    or "https://generativelanguage.googleapis.com/v1beta/models"
)

GEMINI_MODEL = (
    os.getenv(
        "GEMINI_MODEL",
        "gemini-3.8-flash",
    ).strip()
)

GEMINI_FALLBACK_MODEL = (
    os.getenv(
        "GEMINI_FALLBACK_MODEL",
        "gemini-3.5-flash-lite",
    ).strip()
)

GEMINI_ENABLED = (
    os.getenv(
        "GEMINI_ENABLED",
        "true",
    ).strip().lower()
    not in {
        "0",
        "false",
        "no",
        "off",
    }
)

GEMINI_CONNECT_TIMEOUT = float(
    os.getenv(
        "GEMINI_CONNECT_TIMEOUT",
        "10",
    )
)

GEMINI_READ_TIMEOUT = float(
    os.getenv(
        "GEMINI_READ_TIMEOUT",
        "120",
    )
)

GEMINI_MAX_OUTPUT_TOKENS = int(
    os.getenv(
        "GEMINI_MAX_OUTPUT_TOKENS",
        "4096",
    )
)

GEMINI_TEMPERATURE = float(
    os.getenv(
        "GEMINI_TEMPERATURE",
        "0.7",
    )
)


# =========================================================
# MVI AI ENGINE
# =========================================================
#
# MVI is optional.
#
# It is kept as a separate proprietary provider and is NOT
# used unless explicitly included in the provider order.
#

MVI_API_URL = (
    os.getenv(
        "MVI_API_URL",
        "https://Musombi-mvi-ai-engine.hf.space/ask",
    ).strip()
)

MVI_API_KEY = (
    os.getenv(
        "MVI_API_KEY",
        "",
    ).strip()
)

MVI_TIMEOUT = float(
    os.getenv(
        "MVI_TIMEOUT",
        "120",
    )
)

MVI_ENABLED = (
    os.getenv(
        "MVI_ENABLED",
        "true",
    ).strip().lower()
    not in {
        "0",
        "false",
        "no",
        "off",
    }
)


# =========================================================
# HUGGING FACE CONFIGURATION
# =========================================================

HF_TOKEN = (
    os.getenv(
        "HF_TOKEN",
        "",
    ).strip()
)

HF_API_URL = (
    os.getenv(
        "HF_API_URL",
        "https://router.huggingface.co/v1/chat/completions",
    ).strip()
)


# Optional HF text model.
#
# No default is supplied because HF text generation may be
# unavailable when inference credits are exhausted.
#

HF_MODEL = (
    os.getenv(
        "HF_MODEL",
        "",
    ).strip()
)

HF_FALLBACK_MODEL = (
    os.getenv(
        "HF_FALLBACK_MODEL",
        "",
    ).strip()
)


# =========================================================
# TEXT PROVIDER ORDER
# =========================================================
#
# Default:
#
#     gemini
#
# Optional:
#
#     gemini,mvi
#
#     gemini,huggingface
#
#     gemini,mvi,huggingface
#
# Gemini itself performs model-level fallback:
#
#     Gemini 3.8 Flash
#         ->
#     Gemini 3.5 Flash-Lite
#

TEXT_PROVIDER_ORDER = [
    item.strip().lower()
    for item in os.getenv(
        "REVELAAI_TEXT_PROVIDERS",
        "gemini",
    ).split(",")
    if item.strip()
]

if not TEXT_PROVIDER_ORDER:
    TEXT_PROVIDER_ORDER = [
        "gemini",
    ]


# =========================================================
# IMAGE MODEL CONFIGURATION
# =========================================================

HF_IMAGE_MODEL = (
    os.getenv(
        "HF_IMAGE_MODEL",
        "black-forest-labs/FLUX.1-dev",
    ).strip()
)

HF_IMAGE_TEXT_MODEL = (
    os.getenv(
        "HF_IMAGE_TEXT_MODEL",
        "",
    ).strip()
)

HF_IMAGE_FALLBACK_MODEL = (
    os.getenv(
        "HF_IMAGE_FALLBACK_MODEL",
        "black-forest-labs/FLUX.1-schnell",
    ).strip()
)

HF_IMAGE_PROVIDER = (
    os.getenv(
        "HF_IMAGE_PROVIDER",
        "",
    ).strip()
)

HF_IMAGE_TEXT_PROVIDER = (
    os.getenv(
        "HF_IMAGE_TEXT_PROVIDER",
        "",
    ).strip()
)


# =========================================================
# IMAGE SIZE PRESETS
# =========================================================

IMAGE_SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "portrait": (832, 1216),
    "landscape": (1216, 832),
    "wide": (1536, 864),
    "story": (864, 1536),
    "banner": (1536, 512),
    "social_portrait": (1088, 1360),
    "social_landscape": (1360, 768),
    "presentation": (1280, 720),
    "phone": (768, 1365),
}


# =========================================================
# IMAGE DEFAULT DIMENSIONS
# =========================================================

HF_IMAGE_DEFAULT_WIDTH = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_WIDTH",
        "1024",
    )
)

HF_IMAGE_DEFAULT_HEIGHT = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_HEIGHT",
        "1024",
    )
)


# =========================================================
# IMAGE DEFAULT STEPS
# =========================================================

_steps_env = (
    os.getenv(
        "HF_IMAGE_DEFAULT_STEPS",
        "",
    ).strip()
)

HF_IMAGE_DEFAULT_STEPS = (
    int(_steps_env)
    if _steps_env
    else None
)


# =========================================================
# VOICE MODEL CONFIGURATION
# =========================================================

HF_ASR_MODEL = (
    os.getenv(
        "HF_ASR_MODEL",
        "openai/whisper-large-v3",
    ).strip()
)

HF_TTS_MODEL = (
    os.getenv(
        "HF_TTS_MODEL",
        "hexgrad/Kokoro-82M",
    ).strip()
)

HF_TTS_MIME_TYPE = (
    os.getenv(
        "HF_TTS_MIME_TYPE",
        "audio/wav",
    ).strip()
    or "audio/wav"
)


# =========================================================
# HUGGING FACE TIMEOUTS
# =========================================================

HF_CONNECT_TIMEOUT = float(
    os.getenv(
        "HF_CONNECT_TIMEOUT",
        "10",
    )
)

HF_READ_TIMEOUT = float(
    os.getenv(
        "HF_READ_TIMEOUT",
        "120",
    )
)

HF_IMAGE_TIMEOUT = float(
    os.getenv(
        "HF_IMAGE_TIMEOUT",
        "300",
    )
)


# =========================================================
# HUGGING FACE TEXT PARAMETERS
# =========================================================

HF_MAX_TOKENS = int(
    os.getenv(
        "HF_MAX_TOKENS",
        "2048",
    )
)

HF_TEMPERATURE = float(
    os.getenv(
        "HF_TEMPERATURE",
        "0.7",
    )
)


# =========================================================
# ERRORS
# =========================================================


class AIClientError(Exception):
    """
    Raised when an AI provider request fails.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)

        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code


# =========================================================
# PROVIDER STATUS
# =========================================================


def _provider_enabled(
    provider: str,
) -> bool:
    provider = (
        str(
            provider or ""
        )
        .strip()
        .lower()
    )

    if provider in {
        "gemini",
        "google",
        "google-ai",
        "googleai",
    }:
        return bool(
            GEMINI_ENABLED
            and GEMINI_API_KEY
            and GEMINI_API_BASE_URL
            and GEMINI_MODEL
        )

    if provider == "mvi":
        return bool(
            MVI_ENABLED
            and MVI_API_URL
        )

    if provider in {
        "huggingface",
        "hf",
    }:
        return bool(
            HF_TOKEN
            and HF_MODEL
        )

    return False


def get_text_provider_status() -> dict[str, Any]:
    """
    Return safe text-provider diagnostics.

    Secrets are never returned.
    """

    return {
        "provider_order": list(
            TEXT_PROVIDER_ORDER
        ),
        "providers": {
            "gemini": {
                "enabled": bool(
                    GEMINI_ENABLED
                    and GEMINI_API_KEY
                    and GEMINI_API_BASE_URL
                    and GEMINI_MODEL
                ),
                "configured": bool(
                    GEMINI_API_KEY
                    and GEMINI_API_BASE_URL
                    and GEMINI_MODEL
                ),
                "api_key_configured": bool(
                    GEMINI_API_KEY
                ),
                "primary_model": GEMINI_MODEL,
                "fallback_model": GEMINI_FALLBACK_MODEL,
            },
            "mvi": {
                "enabled": bool(
                    MVI_ENABLED
                    and MVI_API_URL
                ),
                "configured": bool(
                    MVI_API_URL
                ),
                "url_configured": bool(
                    MVI_API_URL
                ),
            },
            "huggingface": {
                "enabled": bool(
                    HF_TOKEN
                    and HF_MODEL
                ),
                "configured": bool(
                    HF_TOKEN
                    and HF_MODEL
                ),
                "token_configured": bool(
                    HF_TOKEN
                ),
                "model_configured": bool(
                    HF_MODEL
                ),
                "fallback_model_configured": bool(
                    HF_FALLBACK_MODEL
                ),
            },
        },
    }


# =========================================================
# GEMINI HEADERS
# =========================================================


def get_gemini_headers() -> dict[str, str]:
    """
    Build Gemini HTTP headers.

    Gemini API authentication is provided through the
    x-goog-api-key header.

    The secret is never logged.
    """

    if not GEMINI_API_KEY:
        raise AIClientError(
            "GEMINI_API_KEY is not configured.",
            provider="gemini",
            error_code="gemini_api_key_missing",
        )

    return {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": REQUEST_USER_AGENT,
    }


# =========================================================
# HF CONFIGURATION
# =========================================================


def hf_configured() -> bool:
    """
    Return whether Hugging Face credentials are configured.
    """

    return bool(
        HF_TOKEN
    )


def get_hf_headers() -> dict[str, str]:
    """
    Build Hugging Face authorization headers.
    """

    if not HF_TOKEN:
        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code="hf_token_missing",
        )

    return {
        "Authorization": (
            f"Bearer {HF_TOKEN}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": REQUEST_USER_AGENT,
    }


# =========================================================
# MESSAGE NORMALIZATION
# =========================================================


def _normalize_message_content(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(
        value,
        str,
    ):
        return value

    return str(
        value
    )


# =========================================================
# CHAT MESSAGE BUILDER
# =========================================================


def build_messages(
    *,
    text: str,
    system_prompt: str = "",
    context: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """
    Build OpenAI-compatible messages.

    This function is preserved because existing RevelaAI
    components may use it directly.
    """

    messages: list[
        dict[str, str]
    ] = []

    if system_prompt.strip():
        messages.append(
            {
                "role": "system",
                "content": system_prompt.strip(),
            }
        )

    if isinstance(
        context,
        list,
    ):
        for item in context:

            if not isinstance(
                item,
                dict,
            ):
                continue

            role = str(
                item.get(
                    "role",
                    "user",
                )
            ).strip().lower()

            if role not in {
                "system",
                "user",
                "assistant",
                "model",
            }:
                role = "user"

            if role == "model":
                role = "assistant"

            content = (
                item.get(
                    "content"
                )
                or item.get(
                    "text"
                )
                or ""
            )

            content = (
                _normalize_message_content(
                    content
                )
            )

            if not content:
                continue

            messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

    messages.append(
        {
            "role": "user",
            "content": (
                _normalize_message_content(
                    text
                )
            ),
        }
    )

    return messages


# =========================================================
# GEMINI CONTENT CONVERSION
# =========================================================


def _messages_to_gemini_contents(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]]]:
    """
    Convert OpenAI-style messages into Gemini generateContent
    request format.

    Gemini uses:

        role=user
        role=model

    System messages are returned separately as the Gemini
    systemInstruction.
    """

    system_parts: list[str] = []
    contents: list[
        dict[str, Any]
    ] = []

    for message in messages:

        if not isinstance(
            message,
            dict,
        ):
            continue

        role = str(
            message.get(
                "role",
                "user",
            )
        ).strip().lower()

        content = (
            _normalize_message_content(
                message.get(
                    "content",
                    "",
                )
            )
        ).strip()

        if not content:
            continue

        if role == "system":
            system_parts.append(
                content
            )
            continue

        gemini_role = (
            "model"
            if role in {
                "assistant",
                "model",
            }
            else "user"
        )

        contents.append(
            {
                "role": gemini_role,
                "parts": [
                    {
                        "text": content,
                    }
                ],
            }
        )

    system_instruction = "\n\n".join(
        system_parts
    ).strip()

    return (
        system_instruction,
        contents,
    )


# =========================================================
# GEMINI RESPONSE EXTRACTION
# =========================================================


def _extract_gemini_response(
    data: Any,
) -> str:
    """
    Extract text from Gemini generateContent response.
    """

    if not isinstance(
        data,
        dict,
    ):
        raise AIClientError(
            "Gemini returned an invalid response.",
            provider="gemini",
            error_code="gemini_invalid_response",
        )

    candidates = data.get(
        "candidates"
    )

    if not isinstance(
        candidates,
        list,
    ) or not candidates:

        prompt_feedback = data.get(
            "promptFeedback"
        )

        if prompt_feedback:
            raise AIClientError(
                (
                    "Gemini returned no candidates."
                ),
                provider="gemini",
                error_code="gemini_no_candidates",
            )

        raise AIClientError(
            "Gemini returned no candidates.",
            provider="gemini",
            error_code="gemini_empty_response",
        )

    first = candidates[0]

    if not isinstance(
        first,
        dict,
    ):
        raise AIClientError(
            "Gemini returned an invalid candidate.",
            provider="gemini",
            error_code="gemini_invalid_candidate",
        )

    content = first.get(
        "content"
    )

    if not isinstance(
        content,
        dict,
    ):
        raise AIClientError(
            "Gemini returned no response content.",
            provider="gemini",
            error_code="gemini_missing_content",
        )

    parts = content.get(
        "parts"
    )

    if not isinstance(
        parts,
        list,
    ):
        raise AIClientError(
            "Gemini returned no response parts.",
            provider="gemini",
            error_code="gemini_missing_parts",
        )

    text_parts: list[str] = []

    for part in parts:

        if not isinstance(
            part,
            dict,
        ):
            continue

        value = part.get(
            "text"
        )

        if value:
            text_parts.append(
                str(value)
            )

    result = "".join(
        text_parts
    ).strip()

    if not result:
        raise AIClientError(
            "Gemini returned an empty response.",
            provider="gemini",
            error_code="gemini_empty_text",
        )

    return result


# =========================================================
# GEMINI ERROR EXTRACTION
# =========================================================


def _extract_gemini_error(
    response: requests.Response,
) -> tuple[str, str]:

    try:
        data = response.json()

    except ValueError:
        return (
            (
                "Gemini returned "
                "an invalid error response."
            ),
            "gemini_invalid_error_response",
        )

    if isinstance(
        data,
        dict,
    ):

        error = data.get(
            "error"
        )

        if isinstance(
            error,
            dict,
        ):

            message = (
                error.get(
                    "message"
                )
                or error.get(
                    "status"
                )
                or "Gemini request failed."
            )

            code = (
                error.get(
                    "status"
                )
                or error.get(
                    "code"
                )
                or "gemini_provider_error"
            )

            return (
                str(
                    message
                ),
                str(
                    code
                ),
            )

        if error:
            return (
                str(error),
                "gemini_provider_error",
            )

        message = data.get(
            "message"
        )

        if message:
            return (
                str(message),
                "gemini_provider_error",
            )

    return (
        "Gemini request failed.",
        "gemini_provider_error",
    )


# =========================================================
# GEMINI REQUEST
# =========================================================


def _request_gemini(
    *,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Execute one Gemini generateContent request.
    """

    if not GEMINI_ENABLED:
        raise AIClientError(
            "Gemini provider is disabled.",
            provider="gemini",
            error_code="gemini_disabled",
        )

    if not GEMINI_API_KEY:
        raise AIClientError(
            "GEMINI_API_KEY is not configured.",
            provider="gemini",
            error_code="gemini_api_key_missing",
        )

    if not model:
        raise AIClientError(
            "No Gemini model is configured.",
            provider="gemini",
            error_code="gemini_model_missing",
        )

    if not GEMINI_API_BASE_URL:
        raise AIClientError(
            "GEMINI_API_BASE_URL is not configured.",
            provider="gemini",
            error_code="gemini_url_missing",
        )

    system_instruction, contents = (
        _messages_to_gemini_contents(
            messages
        )
    )

    if not contents:
        raise AIClientError(
            "Gemini request contains no user content.",
            provider="gemini",
            error_code="gemini_empty_contents",
        )

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": (
                GEMINI_MAX_OUTPUT_TOKENS
            ),
            "candidateCount": 1,
        },
    }

    if system_instruction:
        payload[
            "systemInstruction"
        ] = {
            "parts": [
                {
                    "text": system_instruction,
                }
            ]
        }

    encoded_model = quote(
        model,
        safe=""
    )

    url = (
        f"{GEMINI_API_BASE_URL.rstrip('/')}"
        f"/{encoded_model}:generateContent"
    )

    headers = get_gemini_headers()

    started = time.time()

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(
                GEMINI_CONNECT_TIMEOUT,
                GEMINI_READ_TIMEOUT,
            ),
        )

    except requests.Timeout as exc:

        raise AIClientError(
            "Gemini request timed out.",
            provider="gemini",
            error_code="gemini_timeout",
        ) from exc

    except requests.ConnectionError as exc:

        raise AIClientError(
            "Could not connect to Gemini.",
            provider="gemini",
            error_code="gemini_connection_error",
        ) from exc

    except requests.RequestException as exc:

        raise AIClientError(
            "Gemini request failed.",
            provider="gemini",
            error_code="gemini_request_error",
        ) from exc

    elapsed = (
        time.time() - started
    )

    print(
        "GEMINI response | "
        f"model={model} | "
        f"status={response.status_code} | "
        f"time={elapsed:.2f}s"
    )

    if not response.ok:

        message, error_code = (
            _extract_gemini_error(
                response
            )
        )

        raise AIClientError(
            message,
            provider="gemini",
            status_code=(
                response.status_code
            ),
            error_code=error_code,
        )

    try:

        data = response.json()

    except ValueError as exc:

        raise AIClientError(
            "Gemini returned invalid JSON.",
            provider="gemini",
            status_code=(
                response.status_code
            ),
            error_code="gemini_invalid_json",
        ) from exc

    if not isinstance(
        data,
        dict,
    ):

        raise AIClientError(
            "Gemini returned an invalid response.",
            provider="gemini",
            status_code=(
                response.status_code
            ),
            error_code="gemini_invalid_response",
        )

    return data


# =========================================================
# GEMINI TEXT PROVIDER
# =========================================================


def _ask_gemini_text(
    *,
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Main Gemini text provider.

    Primary:
        GEMINI_MODEL

    Fallback:
        GEMINI_FALLBACK_MODEL
    """

    if not GEMINI_ENABLED:
        raise AIClientError(
            "Gemini provider is disabled.",
            provider="gemini",
            error_code="gemini_disabled",
        )

    if not GEMINI_API_KEY:
        raise AIClientError(
            "GEMINI_API_KEY is not configured.",
            provider="gemini",
            error_code="gemini_api_key_missing",
        )

    if not GEMINI_MODEL:
        raise AIClientError(
            "GEMINI_MODEL is not configured.",
            provider="gemini",
            error_code="gemini_model_missing",
        )

    messages = build_messages(
        text=str(text),
        system_prompt=str(
            system_prompt or ""
        ),
        context=context,
    )

    candidates: list[str] = []

    for candidate in (
        GEMINI_MODEL,
        GEMINI_FALLBACK_MODEL,
    ):

        candidate = str(
            candidate or ""
        ).strip()

        if (
            candidate
            and candidate not in candidates
        ):
            candidates.append(
                candidate
            )

    if not candidates:
        raise AIClientError(
            "No Gemini text model is configured.",
            provider="gemini",
            error_code="gemini_models_missing",
        )

    attempted_models: list[str] = []

    last_error: AIClientError | None = (
        None
    )

    for index, model in enumerate(
        candidates
    ):

        attempted_models.append(
            model
        )

        try:

            data = _request_gemini(
                model=model,
                messages=messages,
            )

            response_text = (
                _extract_gemini_response(
                    data
                )
            )

            usage = data.get(
                "usageMetadata",
                {},
            )

            finish_reason = None

            model_candidates = (
                data.get(
                    "candidates"
                )
            )

            if (
                isinstance(
                    model_candidates,
                    list,
                )
                and model_candidates
                and isinstance(
                    model_candidates[0],
                    dict,
                )
            ):
                finish_reason = (
                    model_candidates[0].get(
                        "finishReason"
                    )
                )

            return {
                "success": True,
                "response": response_text,
                "provider": "gemini",
                "model": model,
                "fallback_used": (
                    index > 0
                ),
                "attempted_models": (
                    attempted_models
                ),
                "session_id": session_id,
                "usage": usage,
                "finish_reason": (
                    finish_reason
                ),
            }

        except AIClientError as exc:

            last_error = exc

            # -------------------------------------------------
            # Authentication/configuration/billing issues.
            #
            # Trying another model will not repair a broken
            # API key or disabled account.
            # -------------------------------------------------

            if exc.status_code in {
                401,
                403,
            }:

                print(
                    "GEMINI provider authentication "
                    "or permission failure | "
                    f"model={model} | "
                    f"status={exc.status_code} | "
                    f"error_code={exc.error_code}"
                )

                break

            # -------------------------------------------------
            # Rate limits, temporary provider problems and
            # model availability errors can use fallback.
            # -------------------------------------------------

            if exc.status_code in {
                400,
                404,
                408,
                409,
                429,
                500,
                502,
                503,
                504,
            }:

                print(
                    "GEMINI model failed; trying fallback "
                    "when available | "
                    f"model={model} | "
                    f"status={exc.status_code} | "
                    f"error_code={exc.error_code}"
                )

                continue

            print(
                "GEMINI model failed | "
                f"model={model} | "
                f"status={exc.status_code} | "
                f"error_code={exc.error_code}"
            )

            continue

    if last_error is None:

        last_error = AIClientError(
            "Gemini text generation failed.",
            provider="gemini",
            error_code="gemini_text_failed",
        )

    raise last_error


# =========================================================
# PUBLIC GEMINI CLIENT
# =========================================================


def ask_gemini(
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Direct public Gemini text client.
    """

    if not str(
        text or ""
    ).strip():

        return {
            "success": False,
            "response": "",
            "error": "message is required",
            "error_code": "empty_message",
            "provider": "gemini",
            "session_id": session_id,
        }

    try:

        return _ask_gemini_text(
            text=str(
                text
            ),
            system_prompt=str(
                system_prompt or ""
            ),
            session_id=session_id,
            context=context,
        )

    except AIClientError as exc:

        return {
            "success": False,
            "response": "",
            "error": str(
                exc
            ),
            "error_code": (
                exc.error_code
                or "gemini_error"
            ),
            "provider": "gemini",
            "status_code": (
                exc.status_code
            ),
            "session_id": session_id,
        }


# =========================================================
# MVI RESPONSE EXTRACTION
# =========================================================


def _extract_mvi_response(
    data: Any,
) -> str:

    if data is None:
        return ""

    if isinstance(
        data,
        str,
    ):
        return data.strip()

    if not isinstance(
        data,
        dict,
    ):
        return str(
            data
        ).strip()

    keys = (
        "response",
        "text",
        "answer",
        "message",
        "content",
        "output",
        "generated_text",
    )

    for key in keys:

        value = data.get(
            key
        )

        if isinstance(
            value,
            str,
        ) and value.strip():

            return value.strip()

    for key in (
        "result",
        "data",
    ):

        nested = data.get(
            key
        )

        if isinstance(
            nested,
            dict,
        ):

            result_text = (
                _extract_mvi_response(
                    nested
                )
            )

            if result_text:
                return result_text

    choices = data.get(
        "choices"
    )

    if (
        isinstance(
            choices,
            list,
        )
        and choices
    ):

        first = choices[0]

        if isinstance(
            first,
            dict,
        ):

            message = first.get(
                "message"
            )

            if isinstance(
                message,
                dict,
            ):

                content = message.get(
                    "content"
                )

                if content:
                    return str(
                        content
                    ).strip()

            generated = first.get(
                "text"
            )

            if generated:
                return str(
                    generated
                ).strip()

    return ""


# =========================================================
# MVI REQUEST
# =========================================================


def _request_mvi(
    *,
    text: str,
    system_prompt: str = "",
    context: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:

    if not MVI_ENABLED:

        raise AIClientError(
            "MVI provider is disabled.",
            provider="mvi",
            error_code="mvi_disabled",
        )

    if not MVI_API_URL:

        raise AIClientError(
            "MVI_API_URL is not configured.",
            provider="mvi",
            error_code="mvi_url_missing",
        )

    payload: dict[str, Any] = {
        "prompt": str(
            text
        ),
    }

    if system_prompt.strip():

        payload[
            "system_prompt"
        ] = system_prompt.strip()

    if context:

        payload[
            "context"
        ] = context

    if session_id:

        payload[
            "session_id"
        ] = session_id

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": REQUEST_USER_AGENT,
    }

    if MVI_API_KEY:

        headers[
            "Authorization"
        ] = (
            f"Bearer {MVI_API_KEY}"
        )

    started = time.time()

    try:

        response = requests.post(
            MVI_API_URL,
            headers=headers,
            json=payload,
            timeout=MVI_TIMEOUT,
        )

    except requests.Timeout as exc:

        raise AIClientError(
            "MVI AI Engine request timed out.",
            provider="mvi",
            error_code="mvi_timeout",
        ) from exc

    except requests.ConnectionError as exc:

        raise AIClientError(
            "Could not connect to MVI AI Engine.",
            provider="mvi",
            error_code="mvi_connection_error",
        ) from exc

    except requests.RequestException as exc:

        raise AIClientError(
            "MVI AI Engine request failed.",
            provider="mvi",
            error_code="mvi_request_error",
        ) from exc

    print(
        "MVI response | "
        f"status={response.status_code} | "
        f"time={time.time() - started:.2f}s"
    )

    if not response.ok:

        try:

            error_data = response.json()

        except ValueError:

            error_data = {}

        message = ""

        if isinstance(
            error_data,
            dict,
        ):

            message = str(
                error_data.get(
                    "detail"
                )
                or error_data.get(
                    "error"
                )
                or error_data.get(
                    "message"
                )
                or ""
            ).strip()

        if not message:

            message = (
                response.text.strip()
                or "MVI AI Engine request failed."
            )

        raise AIClientError(
            message,
            provider="mvi",
            status_code=(
                response.status_code
            ),
            error_code="mvi_provider_error",
        )

    try:

        data = response.json()

    except ValueError as exc:

        raise AIClientError(
            "MVI AI Engine returned invalid JSON.",
            provider="mvi",
            status_code=(
                response.status_code
            ),
            error_code="mvi_invalid_json",
        ) from exc

    response_text = (
        _extract_mvi_response(
            data
        )
    )

    if not response_text:

        raise AIClientError(
            "MVI AI Engine returned an empty response.",
            provider="mvi",
            status_code=(
                response.status_code
            ),
            error_code="mvi_empty_response",
        )

    return {
        "success": True,
        "response": response_text,
        "provider": "mvi",
        "model": "mvi-ai-engine",
        "fallback_used": False,
        "session_id": session_id,
        "raw": data,
    }


# =========================================================
# HUGGING FACE INFERENCE CLIENT
# =========================================================


def _get_inference_client(
    provider: str | None = None,
    timeout: float | None = None,
):
    """
    Create a Hugging Face InferenceClient.

    Used for:

        - image generation
        - ASR
        - TTS
    """

    if not HF_TOKEN:

        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code="hf_token_missing",
        )

    try:

        from huggingface_hub import (
            InferenceClient,
        )

    except ImportError as exc:

        raise AIClientError(
            "huggingface_hub is not installed.",
            provider="huggingface",
            error_code="huggingface_hub_missing",
        ) from exc

    options: dict[str, Any] = {
        "api_key": HF_TOKEN,
    }

    if provider:
        options[
            "provider"
        ] = provider

    if timeout:
        options[
            "timeout"
        ] = timeout

    return InferenceClient(
        **options
    )


# =========================================================
# IMAGE MODEL DEFAULTS
# =========================================================


def _model_defaults(
    model: str,
) -> dict[str, Any]:

    name = model.lower()

    if "schnell" in name:

        return {
            "steps": 4,
            "guidance": None,
            "supports_negative": False,
        }

    if "flux" in name:

        return {
            "steps": 28,
            "guidance": 3.5,
            "supports_negative": False,
        }

    if "qwen-image" in name:

        return {
            "steps": 30,
            "guidance": 4.0,
            "supports_negative": True,
        }

    return {
        "steps": 30,
        "guidance": 5.0,
        "supports_negative": True,
    }


# =========================================================
# IMAGE PROVIDER ROUTING
# =========================================================


def _provider_for(
    model: str,
    *,
    has_text: bool = False,
) -> str:

    if (
        HF_IMAGE_TEXT_MODEL
        and model == HF_IMAGE_TEXT_MODEL
    ):
        return HF_IMAGE_TEXT_PROVIDER

    return HF_IMAGE_PROVIDER


# =========================================================
# EXCEPTION HELPERS
# =========================================================


def _status_code(
    exc: Exception,
) -> int | None:

    response = getattr(
        exc,
        "response",
        None,
    )

    return getattr(
        response,
        "status_code",
        None,
    )


def _is_parameter_error(
    exc: Exception,
) -> bool:

    return (
        isinstance(
            exc,
            (
                TypeError,
                ValueError,
            ),
        )
        or _status_code(
            exc
        ) in {
            400,
            422,
        }
    )


# =========================================================
# IMAGE DIMENSIONS
# =========================================================


def resolve_image_dimensions(
    *,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
) -> tuple[int, int]:

    if (
        width is not None
        or height is not None
    ):

        if width is None:
            width = (
                HF_IMAGE_DEFAULT_WIDTH
            )

        if height is None:
            height = (
                HF_IMAGE_DEFAULT_HEIGHT
            )

    elif aspect_ratio:

        key = str(
            aspect_ratio
        ).strip().lower()

        dimensions = (
            IMAGE_SIZE_PRESETS.get(
                key
            )
        )

        if dimensions is None:

            raise AIClientError(
                (
                    "Unsupported image aspect "
                    f"ratio preset: {aspect_ratio}"
                ),
                provider="huggingface",
                error_code=(
                    "invalid_image_aspect_ratio"
                ),
            )

        width, height = dimensions

    else:

        width = (
            HF_IMAGE_DEFAULT_WIDTH
        )

        height = (
            HF_IMAGE_DEFAULT_HEIGHT
        )

    try:

        width = int(
            width
        )

        height = int(
            height
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise AIClientError(
            (
                "Image width and height "
                "must be integers."
            ),
            provider="huggingface",
            error_code=(
                "invalid_image_dimensions"
            ),
        ) from exc

    if width < 256 or width > 2048:

        raise AIClientError(
            (
                "Image width must be "
                "between 256 and 2048 pixels."
            ),
            provider="huggingface",
            error_code="invalid_image_width",
        )

    if height < 256 or height > 2048:

        raise AIClientError(
            (
                "Image height must be "
                "between 256 and 2048 pixels."
            ),
            provider="huggingface",
            error_code="invalid_image_height",
        )

    return (
        width,
        height,
    )


# =========================================================
# ONE IMAGE ATTEMPT
# =========================================================


def _text_to_image_once(
    model: str,
    prompt: str,
    *,
    has_text: bool,
    negative_prompt: str | None,
    width: int,
    height: int,
    steps: int | None,
    guidance: float | None,
    seed: int | None,
):

    defaults = _model_defaults(
        model
    )

    provider = _provider_for(
        model,
        has_text=has_text,
    )

    client = _get_inference_client(
        provider=(
            provider or None
        ),
        timeout=HF_IMAGE_TIMEOUT,
    )

    final_steps = (
        steps
        if steps is not None
        else defaults["steps"]
    )

    final_guidance = (
        guidance
        if guidance is not None
        else defaults["guidance"]
    )

    params: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "width": width,
        "height": height,
    }

    if final_steps is not None:

        params[
            "num_inference_steps"
        ] = int(
            final_steps
        )

    if final_guidance is not None:

        params[
            "guidance_scale"
        ] = float(
            final_guidance
        )

    if seed is not None:

        params[
            "seed"
        ] = int(
            seed
        )

    negative = str(
        negative_prompt or ""
    ).strip()

    if (
        negative
        and defaults[
            "supports_negative"
        ]
    ):

        params[
            "negative_prompt"
        ] = negative

    try:

        return client.text_to_image(
            **params
        )

    except Exception as exc:

        if not _is_parameter_error(
            exc
        ):
            raise

        print(
            "HF image retry with basic parameters | "
            f"model={model} | "
            f"provider={provider or 'auto'} | "
            f"status={_status_code(exc)}"
        )

        return client.text_to_image(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
        )


# =========================================================
# PUBLIC IMAGE GENERATION
# =========================================================


def generate_hf_image(
    prompt: str,
    *,
    model: str | None = None,
    has_text: bool = False,
    negative_prompt: str | None = None,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
    num_inference_steps: int | None = HF_IMAGE_DEFAULT_STEPS,
    guidance_scale: float | None = None,
    seed: int | None = None,
):

    prompt = str(
        prompt or ""
    ).strip()

    if not prompt:

        raise AIClientError(
            "Image prompt is required.",
            provider="huggingface",
            error_code="empty_image_prompt",
        )

    explicit_model = str(
        model or ""
    ).strip()

    if explicit_model:

        primary = explicit_model

    elif (
        has_text
        and HF_IMAGE_TEXT_MODEL
    ):

        primary = (
            HF_IMAGE_TEXT_MODEL
        )

    else:

        primary = (
            HF_IMAGE_MODEL
        )

    if not primary:

        raise AIClientError(
            "No Hugging Face image model is configured.",
            provider="huggingface",
            error_code="image_model_missing",
        )

    width, height = (
        resolve_image_dimensions(
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
        )
    )

    candidates: list[str] = []

    for candidate in (
        primary,
        HF_IMAGE_FALLBACK_MODEL,
        HF_IMAGE_MODEL,
    ):

        candidate = str(
            candidate or ""
        ).strip()

        if (
            candidate
            and candidate not in candidates
        ):

            candidates.append(
                candidate
            )

    last_error: Exception | None = None

    for candidate in candidates:

        started = time.time()

        provider = _provider_for(
            candidate,
            has_text=has_text,
        )

        try:

            image = (
                _text_to_image_once(
                    candidate,
                    prompt,
                    has_text=has_text,
                    negative_prompt=(
                        negative_prompt
                    ),
                    width=width,
                    height=height,
                    steps=(
                        num_inference_steps
                    ),
                    guidance=(
                        guidance_scale
                    ),
                    seed=seed,
                )
            )

        except Exception as exc:

            last_error = exc

            print(
                "HF image generation failed | "
                f"model={candidate} | "
                f"provider={provider or 'auto'} | "
                f"error={type(exc).__name__} | "
                f"status={_status_code(exc)} | "
                f"time={time.time() - started:.2f}s"
            )

            continue

        if image is None:

            print(
                "HF image generation returned nothing | "
                f"model={candidate} | "
                f"provider={provider or 'auto'}"
            )

            continue

        print(
            "HF image generation succeeded | "
            f"model={candidate} | "
            f"provider={provider or 'auto'} | "
            f"has_text={has_text} | "
            f"size={width}x{height} | "
            f"time={time.time() - started:.2f}s"
        )

        return image

    raise AIClientError(
        "Hugging Face image generation failed.",
        provider="huggingface",
        error_code="image_generation_failed",
    ) from last_error


# =========================================================
# GENERIC IMAGE ALIAS
# =========================================================


def generate_image(
    prompt: str,
    **kwargs: Any,
):
    return generate_hf_image(
        prompt=prompt,
        **kwargs,
    )


# =========================================================
# WAV VALIDATION
# =========================================================


def _inspect_wav_audio(
    audio: bytes,
) -> dict[str, Any]:

    if not audio:

        raise AIClientError(
            "Audio data is required.",
            provider="huggingface",
            error_code="empty_audio",
        )

    if len(audio) < 44:

        raise AIClientError(
            (
                "Audio is too small to be "
                "a valid WAV file."
            ),
            provider="huggingface",
            error_code="invalid_wav",
        )

    if (
        audio[:4] != b"RIFF"
        or audio[8:12] != b"WAVE"
    ):

        raise AIClientError(
            "Voice input must be a valid WAV file.",
            provider="huggingface",
            error_code="invalid_wav",
        )

    try:

        with wave.open(
            io.BytesIO(audio),
            "rb",
        ) as wav:

            channels = (
                wav.getnchannels()
            )

            sample_width = (
                wav.getsampwidth()
            )

            sample_rate = (
                wav.getframerate()
            )

            frame_count = (
                wav.getnframes()
            )

            compression = (
                wav.getcomptype()
            )

            duration = (
                frame_count / sample_rate
                if sample_rate
                else 0.0
            )

    except (
        EOFError,
        wave.Error,
        ValueError,
    ) as exc:

        raise AIClientError(
            (
                "The uploaded WAV file "
                "could not be decoded."
            ),
            provider="huggingface",
            error_code="invalid_wav",
        ) from exc

    if compression != "NONE":

        raise AIClientError(
            (
                "Compressed WAV audio is not supported. "
                "Please send PCM WAV audio."
            ),
            provider="huggingface",
            error_code=(
                "unsupported_wav_compression"
            ),
        )

    if channels < 1:

        raise AIClientError(
            "WAV contains no audio channels.",
            provider="huggingface",
            error_code=(
                "invalid_wav_channels"
            ),
        )

    if sample_width != 2:

        raise AIClientError(
            (
                "Voice input must use "
                "16-bit PCM WAV audio."
            ),
            provider="huggingface",
            error_code=(
                "unsupported_wav_bit_depth"
            ),
        )

    if sample_rate < 8000:

        raise AIClientError(
            "Voice sample rate is too low.",
            provider="huggingface",
            error_code="unsupported_sample_rate",
        )

    if duration < 0.25:

        raise AIClientError(
            "Voice recording is too short.",
            provider="huggingface",
            error_code="audio_too_short",
        )

    return {
        "format": "wav",
        "codec": "pcm_s16le",
        "channels": channels,
        "sample_width": sample_width,
        "sample_rate": sample_rate,
        "frames": frame_count,
        "duration_seconds": round(
            duration,
            3,
        ),
        "bytes": len(audio),
    }


# =========================================================
# SPEECH TO TEXT
# =========================================================


def transcribe_hf_audio(
    audio: bytes,
    model: str | None = None,
) -> dict[str, Any]:

    if not audio:

        raise AIClientError(
            "Audio data is required.",
            provider="huggingface",
            error_code="empty_audio",
        )

    if not HF_TOKEN:

        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code="hf_token_missing",
        )

    selected_model = (
        str(
            model
        ).strip()
        if model
        else HF_ASR_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Hugging Face ASR model is configured.",
            provider="huggingface",
            error_code="asr_model_missing",
        )

    audio_info = (
        _inspect_wav_audio(
            audio
        )
    )

    try:

        from huggingface_hub import (
            InferenceClient,
        )

    except ImportError as exc:

        raise AIClientError(
            "huggingface_hub is not installed.",
            provider="huggingface",
            error_code="huggingface_hub_missing",
        ) from exc

    client = InferenceClient(
        api_key=HF_TOKEN,
        provider="fal-ai",
        timeout=HF_IMAGE_TIMEOUT,
    )

    started = time.time()

    try:

        result = (
            client.automatic_speech_recognition(
                audio=audio,
                model=selected_model,
            )
        )

    except Exception as exc:

        print(
            "HF ASR failed | "
            f"model={selected_model} | "
            "provider=fal-ai | "
            f"bytes={audio_info['bytes']} | "
            f"duration={audio_info['duration_seconds']}s | "
            f"sample_rate={audio_info['sample_rate']} | "
            f"channels={audio_info['channels']} | "
            f"time={time.time() - started:.2f}s"
        )

        raise AIClientError(
            "Hugging Face speech recognition failed.",
            provider="huggingface",
            error_code="asr_failed",
        ) from exc

    transcript = getattr(
        result,
        "text",
        None,
    )

    if (
        transcript is None
        and isinstance(
            result,
            dict,
        )
    ):

        transcript = (
            result.get(
                "text"
            )
        )

    transcript = str(
        transcript or ""
    ).strip()

    print(
        "HF ASR result | "
        f"model={selected_model} | "
        "provider=fal-ai | "
        f"duration={audio_info['duration_seconds']}s | "
        f"time={time.time() - started:.2f}s | "
        f"text_length={len(transcript)}"
    )

    if not transcript:

        raise AIClientError(
            (
                "No recognizable speech "
                "was detected in the recording."
            ),
            provider="huggingface",
            error_code="empty_transcription",
        )

    return {
        "success": True,
        "text": transcript,
        "provider": "huggingface",
        "model": selected_model,
        "audio": audio_info,
    }


# =========================================================
# TEXT TO SPEECH
# =========================================================


def generate_hf_speech(
    text: str,
    model: str | None = None,
    voice: str | None = None,
    **generation_kwargs: Any,
) -> bytes:

    text = str(
        text or ""
    ).strip()

    if not text:

        raise AIClientError(
            "Speech text is required.",
            provider="huggingface",
            error_code="empty_speech_text",
        )

    if not HF_TOKEN:

        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code="hf_token_missing",
        )

    selected_model = (
        str(
            model
        ).strip()
        if model
        else HF_TTS_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Hugging Face TTS model is configured.",
            provider="huggingface",
            error_code="tts_model_missing",
        )

    client = _get_inference_client(
        timeout=HF_READ_TIMEOUT,
    )

    started = time.time()

    extra_body: dict[str, Any] = {}

    if voice:

        voice_value = str(
            voice
        ).strip()

        if voice_value:

            extra_body[
                "voice"
            ] = voice_value

    try:

        if extra_body:

            audio = (
                client.text_to_speech(
                    text=text,
                    model=selected_model,
                    extra_body=extra_body,
                    **generation_kwargs,
                )
            )

        else:

            audio = (
                client.text_to_speech(
                    text=text,
                    model=selected_model,
                    **generation_kwargs,
                )
            )

    except Exception as exc:

        print(
            "HF TTS failed | "
            f"model={selected_model} | "
            f"time={time.time() - started:.2f}s"
        )

        raise AIClientError(
            "Hugging Face text-to-speech failed.",
            provider="huggingface",
            error_code="tts_failed",
        ) from exc

    if not audio:

        raise AIClientError(
            "Hugging Face returned empty audio.",
            provider="huggingface",
            error_code="empty_audio_response",
        )

    if not isinstance(
        audio,
        bytes,
    ):

        try:

            audio = bytes(
                audio
            )

        except Exception as exc:

            raise AIClientError(
                "Hugging Face returned invalid audio data.",
                provider="huggingface",
                error_code="invalid_audio_response",
            ) from exc

    print(
        "HF TTS succeeded | "
        f"model={selected_model} | "
        f"time={time.time() - started:.2f}s | "
        f"bytes={len(audio)}"
    )

    return audio


# =========================================================
# MAIN REVELAAI TEXT CLIENT
# =========================================================


def ask_hf(
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Backward-compatible main text-generation entry point.

    IMPORTANT:

        The function is still called ask_hf() because the
        existing RevelaAI application may import it.

        It no longer means "Hugging Face only".

    Default provider:

        Gemini

    Default model:

        gemini-3.8-flash

    Fallback:

        gemini-3.5-flash-lite
    """

    if not str(
        text or ""
    ).strip():

        return {
            "success": False,
            "response": "",
            "error": "message is required",
            "error_code": "empty_message",
            "provider": "revelaai",
            "session_id": session_id,
        }

    provider_errors: list[
        dict[str, Any]
    ] = []

    for provider in TEXT_PROVIDER_ORDER:

        provider = (
            str(
                provider or ""
            )
            .strip()
            .lower()
        )

        # =====================================================
        # GEMINI
        # =====================================================

        if provider in {
            "gemini",
            "google",
            "google-ai",
            "googleai",
        }:

            if not _provider_enabled(
                "gemini"
            ):

                provider_errors.append(
                    {
                        "provider": "gemini",
                        "error": (
                            "Gemini text provider "
                            "is not configured."
                        ),
                        "error_code": (
                            "gemini_not_configured"
                        ),
                    }
                )

                continue

            started = time.time()

            try:

                result = _ask_gemini_text(
                    text=str(
                        text
                    ),
                    system_prompt=str(
                        system_prompt
                        or ""
                    ),
                    session_id=(
                        session_id
                    ),
                    context=context,
                )

                print(
                    "TEXT PROVIDER SUCCESS | "
                    "provider=gemini | "
                    f"model={result.get('model')} | "
                    f"fallback={result.get('fallback_used')} | "
                    f"time={time.time() - started:.2f}s"
                )

                return result

            except AIClientError as exc:

                print(
                    "TEXT PROVIDER FAILED | "
                    "provider=gemini | "
                    f"status={exc.status_code} | "
                    f"error_code={exc.error_code} | "
                    f"time={time.time() - started:.2f}s"
                )

                provider_errors.append(
                    {
                        "provider": "gemini",
                        "error": str(
                            exc
                        ),
                        "error_code": (
                            exc.error_code
                            or "gemini_error"
                        ),
                        "status_code": (
                            exc.status_code
                        ),
                    }
                )

                continue

        # =====================================================
        # MVI
        # =====================================================

        if provider in {
            "mvi",
            "mvi-ai",
            "mvi_ai",
        }:

            if not _provider_enabled(
                "mvi"
            ):

                provider_errors.append(
                    {
                        "provider": "mvi",
                        "error": (
                            "MVI provider "
                            "is not configured."
                        ),
                        "error_code": (
                            "mvi_not_configured"
                        ),
                    }
                )

                continue

            started = time.time()

            try:

                result = _request_mvi(
                    text=str(
                        text
                    ),
                    system_prompt=str(
                        system_prompt
                        or ""
                    ),
                    context=context,
                    session_id=(
                        session_id
                    ),
                )

                print(
                    "TEXT PROVIDER SUCCESS | "
                    "provider=mvi | "
                    f"time={time.time() - started:.2f}s"
                )

                return result

            except AIClientError as exc:

                print(
                    "TEXT PROVIDER FAILED | "
                    "provider=mvi | "
                    f"status={exc.status_code} | "
                    f"error_code={exc.error_code} | "
                    f"time={time.time() - started:.2f}s"
                )

                provider_errors.append(
                    {
                        "provider": "mvi",
                        "error": str(
                            exc
                        ),
                        "error_code": (
                            exc.error_code
                            or "mvi_error"
                        ),
                        "status_code": (
                            exc.status_code
                        ),
                    }
                )

                continue

        # =====================================================
        # HUGGING FACE
        # =====================================================

        if provider in {
            "huggingface",
            "hf",
        }:

            if not _provider_enabled(
                "huggingface"
            ):

                provider_errors.append(
                    {
                        "provider": "huggingface",
                        "error": (
                            "Hugging Face text "
                            "provider is not configured."
                        ),
                        "error_code": (
                            "hf_not_configured"
                        ),
                    }
                )

                continue

            started = time.time()

            try:

                result = _ask_hf_text(
                    text=str(
                        text
                    ),
                    system_prompt=str(
                        system_prompt
                        or ""
                    ),
                    session_id=(
                        session_id
                    ),
                    context=context,
                )

                print(
                    "TEXT PROVIDER SUCCESS | "
                    "provider=huggingface | "
                    f"time={time.time() - started:.2f}s"
                )

                return result

            except AIClientError as exc:

                print(
                    "TEXT PROVIDER FAILED | "
                    "provider=huggingface | "
                    f"status={exc.status_code} | "
                    f"error_code={exc.error_code} | "
                    f"time={time.time() - started:.2f}s"
                )

                provider_errors.append(
                    {
                        "provider": "huggingface",
                        "error": str(
                            exc
                        ),
                        "error_code": (
                            exc.error_code
                            or "hf_error"
                        ),
                        "status_code": (
                            exc.status_code
                        ),
                    }
                )

                continue

        # =====================================================
        # UNKNOWN PROVIDER
        # =====================================================

        print(
            "TEXT PROVIDER UNKNOWN | "
            f"provider={provider}"
        )

        provider_errors.append(
            {
                "provider": provider,
                "error": (
                    "Unknown text provider."
                ),
                "error_code": (
                    "unknown_text_provider"
                ),
            }
        )

    # =========================================================
    # TOTAL FAILURE
    # =========================================================

    if provider_errors:

        last = provider_errors[-1]

        return {
            "success": False,
            "response": "",
            "error": (
                last.get(
                    "error"
                )
                or "No text provider is available."
            ),
            "error_code": (
                last.get(
                    "error_code"
                )
                or "text_generation_failed"
            ),
            "provider": (
                last.get(
                    "provider"
                )
                or "revelaai"
            ),
            "providers_attempted": [
                item.get(
                    "provider"
                )
                for item in provider_errors
            ],
            "provider_errors": (
                provider_errors
            ),
            "session_id": session_id,
        }

    return {
        "success": False,
        "response": "",
        "error": (
            "No text provider is available."
        ),
        "error_code": (
            "no_text_provider"
        ),
        "provider": "revelaai",
        "session_id": session_id,
    }


# =========================================================
# HF TEXT PROVIDER
# =========================================================


def _extract_hf_response(
    data: dict,
) -> str:

    choices = data.get(
        "choices"
    )

    if (
        not isinstance(
            choices,
            list,
        )
        or not choices
    ):

        raise AIClientError(
            "Hugging Face returned no choices.",
            provider="huggingface",
            error_code="empty_model_response",
        )

    first_choice = choices[0]

    if not isinstance(
        first_choice,
        dict,
    ):

        raise AIClientError(
            "Hugging Face returned an invalid choice.",
            provider="huggingface",
            error_code="invalid_model_response",
        )

    message = first_choice.get(
        "message"
    )

    if not isinstance(
        message,
        dict,
    ):

        raise AIClientError(
            "Hugging Face returned no assistant message.",
            provider="huggingface",
            error_code="missing_assistant_message",
        )

    content = message.get(
        "content"
    )

    if content is None:
        content = ""

    if isinstance(
        content,
        list,
    ):

        parts: list[str] = []

        for item in content:

            if isinstance(
                item,
                dict,
            ):

                part_text = item.get(
                    "text"
                )

                if part_text:
                    parts.append(
                        str(
                            part_text
                        )
                    )

            elif item:

                parts.append(
                    str(item)
                )

        content = "".join(
            parts
        )

    content = str(
        content
    ).strip()

    if not content:

        raise AIClientError(
            "Hugging Face returned an empty response.",
            provider="huggingface",
            error_code="empty_response",
        )

    return content


def _extract_provider_error(
    response: requests.Response,
) -> tuple[str, str]:

    try:

        data = response.json()

    except ValueError:

        return (
            (
                "Hugging Face returned "
                "an invalid error response."
            ),
            "invalid_error_response",
        )

    if isinstance(
        data,
        dict,
    ):

        error = data.get(
            "error"
        )

        if isinstance(
            error,
            dict,
        ):

            message = (
                error.get(
                    "message"
                )
                or error.get(
                    "type"
                )
                or "Hugging Face request failed."
            )

            code = (
                error.get(
                    "code"
                )
                or error.get(
                    "type"
                )
                or "provider_error"
            )

            return (
                str(
                    message
                ),
                str(
                    code
                ),
            )

        if error:

            return (
                str(
                    error
                ),
                "provider_error",
            )

        message = data.get(
            "message"
        )

        if message:

            return (
                str(
                    message
                ),
                "provider_error",
            )

    return (
        "Hugging Face request failed.",
        "provider_error",
    )


def _request_hf(
    *,
    model: str,
    messages: list[dict[str, str]],
) -> dict:

    if not model:

        raise AIClientError(
            "No Hugging Face text model is configured.",
            provider="huggingface",
            error_code="hf_text_model_missing",
        )

    headers = (
        get_hf_headers()
    )

    payload = {
        "model": model,
        "messages": messages,
        "temperature": HF_TEMPERATURE,
        "max_tokens": HF_MAX_TOKENS,
    }

    started = time.time()

    try:

        response = requests.post(
            HF_API_URL,
            headers=headers,
            json=payload,
            timeout=(
                HF_CONNECT_TIMEOUT,
                HF_READ_TIMEOUT,
            ),
        )

    except requests.Timeout as exc:

        raise AIClientError(
            "Hugging Face request timed out.",
            provider="huggingface",
            error_code="hf_timeout",
        ) from exc

    except requests.ConnectionError as exc:

        raise AIClientError(
            "Could not connect to Hugging Face.",
            provider="huggingface",
            error_code="hf_connection_error",
        ) from exc

    except requests.RequestException as exc:

        raise AIClientError(
            "Hugging Face request failed.",
            provider="huggingface",
            error_code="hf_request_error",
        ) from exc

    print(
        "HF response | "
        f"model={model} | "
        f"status={response.status_code} | "
        f"time={time.time() - started:.2f}s"
    )

    if not response.ok:

        message, error_code = (
            _extract_provider_error(
                response
            )
        )

        raise AIClientError(
            message,
            provider="huggingface",
            status_code=(
                response.status_code
            ),
            error_code=error_code,
        )

    try:

        data = response.json()

    except ValueError as exc:

        raise AIClientError(
            "Hugging Face returned invalid JSON.",
            provider="huggingface",
            status_code=(
                response.status_code
            ),
            error_code="invalid_json",
        ) from exc

    if not isinstance(
        data,
        dict,
    ):

        raise AIClientError(
            (
                "Hugging Face returned "
                "an invalid response."
            ),
            provider="huggingface",
            error_code="invalid_response",
        )

    return data


def _ask_hf_text(
    *,
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:

    if not HF_TOKEN:

        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code="hf_token_missing",
        )

    if not HF_MODEL:

        raise AIClientError(
            "HF_MODEL is not configured.",
            provider="huggingface",
            error_code="hf_text_model_missing",
        )

    messages = build_messages(
        text=str(text),
        system_prompt=str(
            system_prompt or ""
        ),
        context=context,
    )

    candidates: list[str] = []

    for candidate in (
        HF_MODEL,
        HF_FALLBACK_MODEL,
    ):

        candidate = str(
            candidate or ""
        ).strip()

        if (
            candidate
            and candidate not in candidates
        ):

            candidates.append(
                candidate
            )

    last_error: AIClientError | None = (
        None
    )

    for index, model in enumerate(
        candidates
    ):

        try:

            data = _request_hf(
                model=model,
                messages=messages,
            )

            response_text = (
                _extract_hf_response(
                    data
                )
            )

            return {
                "success": True,
                "response": response_text,
                "provider": "huggingface",
                "model": model,
                "fallback_used": (
                    index > 0
                ),
                "session_id": session_id,
                "usage": data.get(
                    "usage",
                    {},
                ),
            }

        except AIClientError as exc:

            last_error = exc

            if exc.status_code in {
                401,
                402,
                403,
            }:

                break

            continue

    if last_error is None:

        last_error = AIClientError(
            "Hugging Face text generation failed.",
            provider="huggingface",
            error_code="hf_text_failed",
        )

    raise last_error


# =========================================================
# DIRECT MVI CLIENT
# =========================================================


def ask_mvi(
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:

    if not str(
        text or ""
    ).strip():

        return {
            "success": False,
            "response": "",
            "error": "message is required",
            "error_code": "empty_message",
            "provider": "mvi",
        }

    try:

        return _request_mvi(
            text=str(
                text
            ),
            system_prompt=str(
                system_prompt or ""
            ),
            context=context,
            session_id=session_id,
        )

    except AIClientError as exc:

        return {
            "success": False,
            "response": "",
            "error": str(
                exc
            ),
            "error_code": (
                exc.error_code
                or "mvi_error"
            ),
            "provider": "mvi",
            "status_code": (
                exc.status_code
            ),
            "session_id": session_id,
        }


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "AIClientError",

    # Gemini
    "GEMINI_API_KEY",
    "GEMINI_API_BASE_URL",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "GEMINI_ENABLED",

    # Hugging Face
    "HF_TOKEN",
    "HF_API_URL",
    "HF_MODEL",
    "HF_FALLBACK_MODEL",

    # MVI
    "MVI_API_URL",
    "MVI_ENABLED",

    # Provider routing
    "TEXT_PROVIDER_ORDER",

    # Diagnostics
    "hf_configured",
    "get_text_provider_status",

    # Headers
    "get_gemini_headers",
    "get_hf_headers",

    # Messages
    "build_messages",

    # Text
    "ask_gemini",
    "ask_hf",
    "ask_mvi",

    # Images
    "IMAGE_SIZE_PRESETS",
    "resolve_image_dimensions",
    "generate_hf_image",
    "generate_image",

    # Voice
    "transcribe_hf_audio",
    "generate_hf_speech",
]

