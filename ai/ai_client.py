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
        Text AI      Optional          Voice
          |
          +--> Primary:
          |      Configured Gemini model
          |
          +--> Fallback:
                 Configured Gemini fallback


IMAGE
-----

Primary image provider:

    Pollinations

Primary image model:

    flux

    Pollinations alias for Flux Schnell.

Pollinations generation endpoint:

    https://gen.pollinations.ai/image/{prompt}?model=flux

POLLINATIONS_API_KEY must remain server-side.

Never expose the Pollinations API key to the frontend.


VOICE
-----

Hugging Face remains available for:

    - ASR
    - TTS

HF_TOKEN must remain server-side.

Never expose HF_TOKEN to the frontend.


IMPORTANT
---------

The old hard-coded text models are NOT used:

    openai/gpt-oss-120b:cheapest
    openai/gpt-oss-20b:cheapest

The old Hugging Face image models are NOT used for image generation.

Backward-compatible image functions remain:

    generate_hf_image()
    generate_image()

Both now route to Pollinations.


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
        "30",
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
#
# HF remains available for:
#
#     - optional text fallback
#     - ASR
#     - TTS
#
# It is intentionally NOT used for image generation.
#

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
# POLLINATIONS IMAGE CONFIGURATION
# =========================================================
#
# Primary image engine:
#
#     Pollinations
#
# Primary model:
#
#     flux
#
# The production Pollinations API currently uses:
#
#     https://gen.pollinations.ai/image/{prompt}
#
# with:
#
#     ?model=flux
#
# Authentication:
#
#     Authorization: Bearer <POLLINATIONS_API_KEY>
#
# Keep the key server-side.
#

POLLINATIONS_API_KEY = (
    os.getenv(
        "POLLINATIONS_API_KEY",
        "",
    ).strip()
)

POLLINATIONS_API_BASE_URL = (
    os.getenv(
        "POLLINATIONS_API_BASE_URL",
        "https://gen.pollinations.ai",
    ).strip()
    or "https://gen.pollinations.ai"
)

POLLINATIONS_IMAGE_MODEL = (
    os.getenv(
        "POLLINATIONS_IMAGE_MODEL",
        "flux",
    ).strip()
    or "flux"
)

# Empty by default.
#
# This deliberately prevents unexpected additional
# Pollen consumption from automatic fallback generation.
#
# Enable explicitly in Render when desired, for example:
#
#     POLLINATIONS_IMAGE_FALLBACK_MODEL=zimage
#

POLLINATIONS_IMAGE_FALLBACK_MODEL = (
    os.getenv(
        "POLLINATIONS_IMAGE_FALLBACK_MODEL",
        "",
    ).strip()
)

POLLINATIONS_IMAGE_TIMEOUT = float(
    os.getenv(
        "POLLINATIONS_IMAGE_TIMEOUT",
        "120",
    )
)

POLLINATIONS_MAX_IMAGE_BYTES = int(
    os.getenv(
        "POLLINATIONS_MAX_IMAGE_BYTES",
        str(15 * 1024 * 1024),
    )
)


# =========================================================
# LEGACY IMAGE VARIABLES
# =========================================================
#
# These names are preserved because older RevelaAI
# application code may import them.
#
# They no longer control an actual Hugging Face image
# generation request.
#

HF_IMAGE_MODEL = POLLINATIONS_IMAGE_MODEL
HF_IMAGE_TEXT_MODEL = ""
HF_IMAGE_FALLBACK_MODEL = POLLINATIONS_IMAGE_FALLBACK_MODEL
HF_IMAGE_PROVIDER = "pollinations"
HF_IMAGE_TEXT_PROVIDER = "pollinations"


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
#
# Preserved for backward compatibility.
#
# Pollinations' hosted image endpoint controls model
# inference internally, so these values are not sent.
#

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

    if provider in {
        "mvi",
        "mvi-ai",
        "mvi_ai",
    }:

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

    if provider in {
        "pollinations",
        "pollinations-ai",
        "polli",
    }:

        return bool(
            POLLINATIONS_API_KEY
            and POLLINATIONS_API_BASE_URL
            and POLLINATIONS_IMAGE_MODEL
        )

    return False


def pollinations_configured() -> bool:
    """
    Return whether Pollinations image generation is
    configured with a server-side API key.
    """

    return bool(
        POLLINATIONS_API_KEY
        and POLLINATIONS_API_BASE_URL
        and POLLINATIONS_IMAGE_MODEL
    )


def get_image_provider_status() -> dict[str, Any]:
    """
    Return safe image-provider diagnostics.

    Secrets are never returned.
    """

    return {
        "provider": "pollinations",
        "enabled": bool(
            POLLINATIONS_API_KEY
            and POLLINATIONS_API_BASE_URL
            and POLLINATIONS_IMAGE_MODEL
        ),
        "configured": bool(
            POLLINATIONS_API_KEY
            and POLLINATIONS_API_BASE_URL
            and POLLINATIONS_IMAGE_MODEL
        ),
        "api_key_configured": bool(
            POLLINATIONS_API_KEY
        ),
        "base_url_configured": bool(
            POLLINATIONS_API_BASE_URL
        ),
        "model": POLLINATIONS_IMAGE_MODEL,
        "fallback_model": (
            POLLINATIONS_IMAGE_FALLBACK_MODEL
            or None
        ),
    }


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
        "image": get_image_provider_status(),
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
# HUGGING FACE CONFIGURATION
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
# POLLINATIONS HEADERS
# =========================================================


def get_pollinations_headers() -> dict[str, str]:
    """
    Build Pollinations authorization headers.

    The secret is never logged.
    """

    if not POLLINATIONS_API_KEY:

        raise AIClientError(
            "POLLINATIONS_API_KEY is not configured.",
            provider="pollinations",
            error_code="pollinations_api_key_missing",
        )

    return {
        "Authorization": (
            f"Bearer {POLLINATIONS_API_KEY}"
        ),
        "Accept": "image/*,application/json",
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

    system_instruction = (
        "\n\n".join(
            system_parts
        ).strip()
    )

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

    if (
        not isinstance(
            candidates,
            list,
        )
        or not candidates
    ):

        prompt_feedback = data.get(
            "promptFeedback"
        )

        if prompt_feedback:

            raise AIClientError(
                "Gemini returned no candidates.",
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
                str(message),
                str(code),
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
        safe="",
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

    last_error: AIClientError | None = None

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
                "finish_reason": finish_reason,
            }

        except AIClientError as exc:

            last_error = exc

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
            } or exc.error_code in {
                "gemini_timeout",
                "gemini_connection_error",
            }:

                print(
                    "GEMINI model failed; "
                    "trying fallback when available | "
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

        if (
            isinstance(
                value,
                str,
            )
            and value.strip()
        ):

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

        - ASR
        - TTS

    NOT used for image generation.
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
# POLLINATIONS IMAGE MODEL NORMALIZATION
# =========================================================


def _normalize_pollinations_image_model(
    model: str | None,
) -> str:

    requested = str(
        model or ""
    ).strip().lower()

    if not requested:
        return POLLINATIONS_IMAGE_MODEL

    # -----------------------------------------------------
    # Modern Pollinations aliases.
    # -----------------------------------------------------

    if requested in {
        "flux",
        "black-forest-labs/flux.1-schnell",
        "black-forest-labs/flux.1-schnell",
        "black-forest-labs/flux",
    }:

        return "flux"

    if requested in {
        "zimage",
        "z-image",
        "z-image-turbo",
        "z-image/z-image-turbo",
    }:

        return "zimage"

    # -----------------------------------------------------
    # Legacy Hugging Face FLUX names.
    #
    # This prevents old frontend/backend values from
    # accidentally causing an HF inference request.
    # -----------------------------------------------------

    if requested in {
        "black-forest-labs/flux.1-dev",
        "black-forest-labs/flux.1-schnell",
        "black-forest-labs/flux1-dev",
        "black-forest-labs/flux1-schnell",
        "flux.1-dev",
        "flux.1-schnell",
    }:

        return "flux"

    # -----------------------------------------------------
    # Otherwise allow a valid Pollinations model ID or
    # alias to pass through.
    # -----------------------------------------------------

    return str(
        model
    ).strip()


# =========================================================
# IMAGE MODEL DEFAULTS
# =========================================================


def _model_defaults(
    model: str,
) -> dict[str, Any]:

    name = (
        str(
            model or ""
        )
        .lower()
    )

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
        "supports_negative": False,
    }


# =========================================================
# IMAGE PROVIDER ROUTING
# =========================================================


def _provider_for(
    model: str,
    *,
    has_text: bool = False,
) -> str:

    return "pollinations"


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
                provider="pollinations",
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
            provider="pollinations",
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
            provider="pollinations",
            error_code="invalid_image_width",
        )

    if height < 256 or height > 2048:

        raise AIClientError(
            (
                "Image height must be "
                "between 256 and 2048 pixels."
            ),
            provider="pollinations",
            error_code="invalid_image_height",
        )

    return (
        width,
        height,
    )


# =========================================================
# POLLINATIONS ERROR EXTRACTION
# =========================================================


def _extract_pollinations_error(
    response: requests.Response,
) -> tuple[str, str]:

    try:

        data = response.json()

    except ValueError:

        message = (
            response.text.strip()
        )

        if response.status_code == 401:

            return (
                (
                    "Pollinations authentication failed. "
                    "Check POLLINATIONS_API_KEY."
                ),
                "pollinations_unauthorized",
            )

        if response.status_code == 402:

            return (
                (
                    "Pollinations has no available "
                    "Pollen balance for this request."
                ),
                "pollinations_insufficient_balance",
            )

        if response.status_code == 403:

            return (
                (
                    "Pollinations denied access to "
                    "the requested generation."
                ),
                "pollinations_forbidden",
            )

        return (
            message
            or "Pollinations image generation failed.",
            "pollinations_provider_error",
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
                    "detail"
                )
                or error.get(
                    "error"
                )
                or "Pollinations image generation failed."
            )

            code = (
                error.get(
                    "code"
                )
                or error.get(
                    "type"
                )
                or "pollinations_provider_error"
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
                "pollinations_provider_error",
            )

        message = (
            data.get(
                "message"
            )
            or data.get(
                "detail"
            )
        )

        if message:

            return (
                str(
                    message
                ),
                "pollinations_provider_error",
            )

    if response.status_code == 401:

        return (
            (
                "Pollinations authentication failed. "
                "Check POLLINATIONS_API_KEY."
            ),
            "pollinations_unauthorized",
        )

    if response.status_code == 402:

        return (
            (
                "Pollinations has no available "
                "Pollen balance for this request."
            ),
            "pollinations_insufficient_balance",
        )

    if response.status_code == 403:

        return (
            (
                "Pollinations denied access to "
                "the requested generation."
            ),
            "pollinations_forbidden",
        )

    return (
        "Pollinations image generation failed.",
        "pollinations_provider_error",
    )


# =========================================================
# POLLINATIONS IMAGE BYTES
# =========================================================


def _request_pollinations_image(
    *,
    model: str,
    prompt: str,
    width: int,
    height: int,
    seed: int | None = None,
    negative_prompt: str | None = None,
) -> bytes:

    if not POLLINATIONS_API_KEY:

        raise AIClientError(
            (
                "POLLINATIONS_API_KEY is not configured."
            ),
            provider="pollinations",
            error_code=(
                "pollinations_api_key_missing"
            ),
        )

    if not POLLINATIONS_API_BASE_URL:

        raise AIClientError(
            (
                "POLLINATIONS_API_BASE_URL "
                "is not configured."
            ),
            provider="pollinations",
            error_code=(
                "pollinations_url_missing"
            ),
        )

    if not model:

        raise AIClientError(
            (
                "No Pollinations image model "
                "is configured."
            ),
            provider="pollinations",
            error_code=(
                "pollinations_image_model_missing"
            ),
        )

    clean_prompt = str(
        prompt or ""
    ).strip()

    if not clean_prompt:

        raise AIClientError(
            "Image prompt is required.",
            provider="pollinations",
            error_code="empty_image_prompt",
        )

    # -----------------------------------------------------
    # Pollinations GET image endpoint.
    #
    # The prompt is part of the URL path.
    # Other supported controls are query parameters.
    # -----------------------------------------------------

    encoded_prompt = quote(
        clean_prompt,
        safe="",
    )

    url = (
        f"{POLLINATIONS_API_BASE_URL.rstrip('/')}"
        f"/image/{encoded_prompt}"
    )

    params: dict[str, Any] = {
        "model": model,
        "width": int(width),
        "height": int(height),
    }

    if seed is not None:

        params[
            "seed"
        ] = int(seed)

    # -----------------------------------------------------
    # Pollinations' current simple image endpoint does not
    # expose the Hugging Face negative_prompt parameter in
    # the same way.
    #
    # Preserve the user's intent by turning it into an
    # explicit generation constraint.
    # -----------------------------------------------------

    negative = str(
        negative_prompt or ""
    ).strip()

    if negative:

        params[
            "enhance"
        ] = "false"

        effective_prompt = (
            f"{clean_prompt}. "
            f"Avoid: {negative}"
        )

        encoded_prompt = quote(
            effective_prompt,
            safe="",
        )

        url = (
            f"{POLLINATIONS_API_BASE_URL.rstrip('/')}"
            f"/image/{encoded_prompt}"
        )

    headers = (
        get_pollinations_headers()
    )

    started = time.time()

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=POLLINATIONS_IMAGE_TIMEOUT,
        )

    except requests.Timeout as exc:

        raise AIClientError(
            "Pollinations image request timed out.",
            provider="pollinations",
            error_code="pollinations_timeout",
        ) from exc

    except requests.ConnectionError as exc:

        raise AIClientError(
            "Could not connect to Pollinations.",
            provider="pollinations",
            error_code="pollinations_connection_error",
        ) from exc

    except requests.RequestException as exc:

        raise AIClientError(
            "Pollinations image request failed.",
            provider="pollinations",
            error_code="pollinations_request_error",
        ) from exc

    elapsed = (
        time.time() - started
    )

    content_type = (
        response.headers.get(
            "Content-Type",
            "",
        )
        .split(";")[0]
        .strip()
        .lower()
    )

    print(
        "POLLINATIONS IMAGE RESPONSE | "
        f"model={model} | "
        f"status={response.status_code} | "
        f"content_type={content_type or 'unknown'} | "
        f"bytes={len(response.content)} | "
        f"size={width}x{height} | "
        f"time={elapsed:.2f}s"
    )

    if not response.ok:

        message, error_code = (
            _extract_pollinations_error(
                response
            )
        )

        raise AIClientError(
            message,
            provider="pollinations",
            status_code=(
                response.status_code
            ),
            error_code=error_code,
        )

    if not response.content:

        raise AIClientError(
            "Pollinations returned an empty image.",
            provider="pollinations",
            status_code=(
                response.status_code
            ),
            error_code="pollinations_empty_image",
        )

    if (
        POLLINATIONS_MAX_IMAGE_BYTES > 0
        and len(response.content)
        > POLLINATIONS_MAX_IMAGE_BYTES
    ):

        raise AIClientError(
            (
                "Pollinations returned an image "
                "larger than the configured limit."
            ),
            provider="pollinations",
            status_code=(
                response.status_code
            ),
            error_code=(
                "pollinations_image_too_large"
            ),
        )

    # -----------------------------------------------------
    # The simple endpoint returns raster image bytes for
    # the flux model. Validate that the bytes really form
    # an image before handing them to the application.
    # -----------------------------------------------------

    try:

        from PIL import Image

    except ImportError as exc:

        raise AIClientError(
            "Pillow is not installed.",
            provider="pollinations",
            error_code="pillow_missing",
        ) from exc

    try:

        with Image.open(
            io.BytesIO(
                response.content
            )
        ) as image:

            image.verify()

    except Exception as exc:

        # Sometimes providers can return an error document
        # despite a successful HTTP status.
        #
        # Keep the raw provider body out of logs because
        # it may contain unexpected request information.

        raise AIClientError(
            (
                "Pollinations returned data that "
                "could not be decoded as an image."
            ),
            provider="pollinations",
            status_code=(
                response.status_code
            ),
            error_code=(
                "pollinations_invalid_image"
            ),
        ) from exc

    return response.content


# =========================================================
# POLLINATIONS ONE IMAGE ATTEMPT
# =========================================================


def _pollinations_image_once(
    *,
    model: str,
    prompt: str,
    negative_prompt: str | None,
    width: int,
    height: int,
    seed: int | None,
) -> Any:

    image_bytes = (
        _request_pollinations_image(
            model=model,
            prompt=prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
        )
    )

    try:

        from PIL import Image

    except ImportError as exc:

        raise AIClientError(
            "Pillow is not installed.",
            provider="pollinations",
            error_code="pillow_missing",
        ) from exc

    try:

        image = Image.open(
            io.BytesIO(
                image_bytes
            )
        )

        # -------------------------------------------------
        # Detach the image from the response BytesIO so
        # the returned object remains usable by callers.
        # -------------------------------------------------

        image.load()

        return image.copy()

    except Exception as exc:

        raise AIClientError(
            (
                "Could not decode the "
                "Pollinations image."
            ),
            provider="pollinations",
            error_code="pollinations_image_decode_failed",
        ) from exc


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
    """
    Backward-compatible image-generation entry point.

    IMPORTANT:

        This function name is retained because the existing
        RevelaAI application imports generate_hf_image().

        It NO LONGER calls Hugging Face.

        It routes to Pollinations.
    """

    del has_text
    del num_inference_steps
    del guidance_scale

    prompt = str(
        prompt or ""
    ).strip()

    if not prompt:

        raise AIClientError(
            "Image prompt is required.",
            provider="pollinations",
            error_code="empty_image_prompt",
        )

    selected_model = (
        _normalize_pollinations_image_model(
            model
        )
        if model
        else POLLINATIONS_IMAGE_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Pollinations image model is configured.",
            provider="pollinations",
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

    # -----------------------------------------------------
    # Primary model.
    # -----------------------------------------------------

    if selected_model:

        candidates.append(
            selected_model
        )

    # -----------------------------------------------------
    # Explicitly configured fallback only.
    #
    # No default fallback is provided so free/budget
    # usage cannot silently become additional paid usage.
    # -----------------------------------------------------

    fallback_model = (
        _normalize_pollinations_image_model(
            POLLINATIONS_IMAGE_FALLBACK_MODEL
        )
        if POLLINATIONS_IMAGE_FALLBACK_MODEL
        else ""
    )

    if (
        fallback_model
        and fallback_model not in candidates
    ):

        candidates.append(
            fallback_model
        )

    last_error: Exception | None = None

    for candidate in candidates:

        started = time.time()

        provider = _provider_for(
            candidate,
            has_text=False,
        )

        try:

            image = (
                _pollinations_image_once(
                    model=candidate,
                    prompt=prompt,
                    negative_prompt=(
                        negative_prompt
                    ),
                    width=width,
                    height=height,
                    seed=seed,
                )
            )

        except AIClientError as exc:

            last_error = exc

            print(
                "POLLINATIONS IMAGE FAILED | "
                f"model={candidate} | "
                f"provider={provider} | "
                f"status={exc.status_code} | "
                f"error_code={exc.error_code} | "
                f"time={time.time() - started:.2f}s"
            )

            # -------------------------------------------------
            # Do not blindly repeat a request for auth/billing
            # failures. Those conditions will not be repaired
            # by retrying another model.
            # -------------------------------------------------

            if exc.status_code in {
                401,
                402,
                403,
            }:

                break

            continue

        except Exception as exc:

            last_error = exc

            print(
                "POLLINATIONS IMAGE FAILED | "
                f"model={candidate} | "
                f"provider={provider} | "
                f"error={type(exc).__name__} | "
                f"time={time.time() - started:.2f}s"
            )

            continue

        if image is None:

            last_error = AIClientError(
                "Pollinations returned no image.",
                provider="pollinations",
                error_code="pollinations_empty_image",
            )

            continue

        print(
            "POLLINATIONS IMAGE SUCCESS | "
            f"model={candidate} | "
            f"provider={provider} | "
            f"size={width}x{height} | "
            f"time={time.time() - started:.2f}s"
        )

        return image

    if isinstance(
        last_error,
        AIClientError,
    ):

        raise last_error

    raise AIClientError(
        "Pollinations image generation failed.",
        provider="pollinations",
        error_code="image_generation_failed",
    ) from last_error


# =========================================================
# GENERIC IMAGE ALIAS
# =========================================================


def generate_image(
    prompt: str,
    **kwargs: Any,
):
    """
    Generic image-generation alias.

    Routes to Pollinations.
    """

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
# HF TEXT RESPONSE EXTRACTION
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


# =========================================================
# HF PROVIDER ERROR EXTRACTION
# =========================================================


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
                str(message),
                str(code),
            )

        if error:

            return (
                str(error),
                "provider_error",
            )

        message = data.get(
            "message"
        )

        if message:

            return (
                str(message),
                "provider_error",
            )

    return (
        "Hugging Face request failed.",
        "provider_error",
    )


# =========================================================
# HF TEXT REQUEST
# =========================================================


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


# =========================================================
# HF TEXT PROVIDER
# =========================================================


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

    last_error: AIClientError | None = None

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

    The function name is preserved because existing
    RevelaAI modules may still import ask_hf().

    Actual provider order is controlled through:

        REVELAAI_TEXT_PROVIDERS

    Recommended production configuration:

        REVELAAI_TEXT_PROVIDERS=gemini
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
                    session_id=session_id,
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
                    session_id=session_id,
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
                    session_id=session_id,
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
                "error": "Unknown text provider.",
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
        "error_code": "no_text_provider",
        "provider": "revelaai",
        "session_id": session_id,
    }


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

    # Pollinations
    "POLLINATIONS_API_KEY",
    "POLLINATIONS_API_BASE_URL",
    "POLLINATIONS_IMAGE_MODEL",
    "POLLINATIONS_IMAGE_FALLBACK_MODEL",

    # Legacy image names
    "HF_IMAGE_MODEL",
    "HF_IMAGE_TEXT_MODEL",
    "HF_IMAGE_FALLBACK_MODEL",
    "HF_IMAGE_PROVIDER",

    # Provider routing
    "TEXT_PROVIDER_ORDER",

    # Diagnostics
    "hf_configured",
    "pollinations_configured",
    "get_text_provider_status",
    "get_image_provider_status",

    # Headers
    "get_gemini_headers",
    "get_hf_headers",
    "get_pollinations_headers",

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
