# ai/ai_client.py

"""
RevelaAI AI Client

Text generation:
    Hugging Face Inference Providers

Image generation:
    Replicate

Architecture:

    RevelaAI
        |
        +---- Hugging Face
        |        |
        |        └── openai/gpt-oss-120b
        |
        └---- Replicate
                 |
                 └── image/video models

IMPORTANT:
    HF_TOKEN and REPLICATE_API_TOKEN must remain server-side.
    They must NEVER be exposed to the frontend.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# HUGGING FACE CONFIGURATION
# =========================================================

HF_TOKEN = (
    os.getenv(
        "HF_TOKEN",
        "",
    )
    .strip()
)

HF_MODEL = (
    os.getenv(
        "HF_MODEL",
        "openai/gpt-oss-120b:cheapest",
    )
    .strip()
)

HF_API_URL = (
    os.getenv(
        "HF_API_URL",
        "https://router.huggingface.co/v1/chat/completions",
    )
    .strip()
)

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
# OPTIONAL FALLBACK MODEL
# =========================================================

HF_FALLBACK_MODEL = (
    os.getenv(
        "HF_FALLBACK_MODEL",
        "openai/gpt-oss-20b:cheapest",
    )
    .strip()
)


# =========================================================
# REPLICATE CONFIGURATION
# =========================================================

REPLICATE_API_URL = (
    "https://api.replicate.com/v1/predictions"
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
    ):
        super().__init__(
            message
        )

        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code


# =========================================================
# HF CONFIGURATION
# =========================================================

def hf_configured() -> bool:
    """
    Return whether the Hugging Face token is configured.
    """

    return bool(
        HF_TOKEN
    )


# =========================================================
# HF HEADERS
# =========================================================

def get_hf_headers() -> dict[str, str]:
    """
    Build Hugging Face authorization headers.

    The token is intentionally never logged.
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
        "User-Agent": "RevelaAI/1.0",
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


def build_messages(
    *,
    text: str,
    system_prompt: str = "",
    context: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """
    Build OpenAI-compatible chat messages.

    `context` is optional and intended for conversation
    history supplied by RevelaAI.
    """

    messages = []

    if system_prompt.strip():

        messages.append({
            "role": "system",
            "content": system_prompt.strip(),
        })

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
            }:
                role = "user"

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

            messages.append({
                "role": role,
                "content": content,
            })

    messages.append({
        "role": "user",
        "content": (
            _normalize_message_content(
                text
            )
        ),
    })

    return messages

# =========================================================
# HUGGING FACE IMAGE GENERATION
# =========================================================

HF_IMAGE_MODEL = (
    os.getenv(
        "HF_IMAGE_MODEL",
        "black-forest-labs/FLUX.1-schnell",
    )
    .strip()
)


def generate_hf_image(
    prompt: str,
    *,
    model: str | None = None,
    width: int = 1024,
    height: int = 1024,
    num_inference_steps: int | None = None,
):
    """
    Generate an image through Hugging Face Inference Providers.

    Uses automatic provider selection so Hugging Face can route
    the request to an available provider.

    Returns:
        PIL.Image.Image

    Raises:
        AIClientError
    """

    prompt = str(
        prompt or ""
    ).strip()

    if not prompt:

        raise AIClientError(
            "Image prompt is required.",
            provider="huggingface",
            error_code="empty_image_prompt",
        )

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

    selected_model = (
        model
        or HF_IMAGE_MODEL
    )

    client = InferenceClient(
        api_key=HF_TOKEN,
        provider="auto",
    )

    start = time.time()

    try:

        image = client.text_to_image(
            prompt=prompt,
            model=selected_model,
            width=int(width),
            height=int(height),
            num_inference_steps=(
                int(num_inference_steps)
                if num_inference_steps is not None
                else None
            ),
        )

    except Exception as exc:

        elapsed = (
            time.time() - start
        )

        print(
            "HF image generation failed | "
            f"model={selected_model} | "
            f"time={elapsed:.2f}s"
        )

        raise AIClientError(
            "Hugging Face image generation failed.",
            provider="huggingface",
            error_code="image_generation_failed",
        ) from exc

    elapsed = (
        time.time() - start
    )

    print(
        "HF image generation | "
        f"model={selected_model} | "
        f"time={elapsed:.2f}s"
    )

    if image is None:

        raise AIClientError(
            "Hugging Face returned no image.",
            provider="huggingface",
            error_code="empty_image_response",
        )

    return image

# =========================================================
# RESPONSE EXTRACTION
# =========================================================

def _extract_hf_response(
    data: dict,
) -> str:
    """
    Extract assistant text from a Hugging Face
    OpenAI-compatible response.
    """

    choices = data.get(
        "choices"
    )

    if not isinstance(
        choices,
        list,
    ) or not choices:

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

    # Some compatible providers may return a list of content
    # blocks instead of a plain string.
    if isinstance(
        content,
        list,
    ):

        parts = []

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
                        str(part_text)
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
# HF ERROR EXTRACTION
# =========================================================

def _extract_provider_error(
    response: requests.Response,
) -> tuple[str, str]:
    """
    Extract a safe human-readable provider error.
    """

    try:

        data = response.json()

    except ValueError:

        return (
            "Hugging Face returned an invalid error response.",
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
# HF REQUEST
# =========================================================

def _request_hf(
    *,
    model: str,
    messages: list[dict[str, str]],
) -> dict:
    """
    Send a chat completion request to Hugging Face.
    """

    headers = get_hf_headers()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": HF_TEMPERATURE,
        "max_tokens": HF_MAX_TOKENS,
    }

    start = time.time()

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

    elapsed = time.time() - start

    print(
        "HF response | "
        f"model={model} | "
        f"status={response.status_code} | "
        f"time={elapsed:.2f}s"
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
            status_code=response.status_code,
            error_code=error_code,
        )

    try:

        data = response.json()

    except ValueError as exc:

        raise AIClientError(
            "Hugging Face returned invalid JSON.",
            provider="huggingface",
            status_code=response.status_code,
            error_code="invalid_json",
        ) from exc

    if not isinstance(
        data,
        dict,
    ):

        raise AIClientError(
            "Hugging Face returned an invalid response.",
            provider="huggingface",
            error_code="invalid_response",
        )

    return data


# =========================================================
# MAIN HUGGING FACE CHAT CLIENT
# =========================================================

def ask_hf(
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Generate an answer using Hugging Face Inference Providers.

    `session_id` is preserved for compatibility with the
    existing RevelaAI pipeline. Session persistence itself
    remains the responsibility of RevelaAI.
    """

    if not str(
        text or ""
    ).strip():

        return {
            "success": False,
            "response": "",
            "error": "message is required",
            "error_code": "empty_message",
            "provider": "huggingface",
        }

    messages = build_messages(
        text=str(
            text
        ),
        system_prompt=str(
            system_prompt or ""
        ),
        context=context,
    )

    attempted_models = []

    primary_model = (
        HF_MODEL
        or "openai/gpt-oss-120b:cheapest"
    )

    attempted_models.append(
        primary_model
    )

    try:

        data = _request_hf(
            model=primary_model,
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
            "model": primary_model,
            "session_id": session_id,
            "usage": data.get(
                "usage",
                {},
            ),
        }

    except AIClientError as primary_error:

        # -------------------------------------------------
        # Fallback model
        # -------------------------------------------------

        fallback_model = (
            HF_FALLBACK_MODEL
        )

        if (
            not fallback_model
            or fallback_model
            == primary_model
        ):

            return {
                "success": False,
                "response": "",
                "error": str(
                    primary_error
                ),
                "error_code": (
                    primary_error.error_code
                    or "hf_error"
                ),
                "provider": "huggingface",
                "model": primary_model,
            }

        attempted_models.append(
            fallback_model
        )

        try:

            data = _request_hf(
                model=fallback_model,
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
                "model": fallback_model,
                "fallback_used": True,
                "session_id": session_id,
                "usage": data.get(
                    "usage",
                    {},
                ),
            }

        except AIClientError as fallback_error:

            return {
                "success": False,
                "response": "",
                "error": (
                    str(
                        fallback_error
                    )
                    or str(
                        primary_error
                    )
                ),
                "error_code": (
                    fallback_error.error_code
                    or primary_error.error_code
                    or "hf_error"
                ),
                "provider": "huggingface",
                "models_attempted": (
                    attempted_models
                ),
            }


# =========================================================
# BACKWARD COMPATIBILITY
# =========================================================

def ask_mvi(
    text,
    system_prompt="",
    session_id=None,
):
    """
    Backward-compatible alias.

    Existing imports can continue working temporarily:

        from ai.ai_client import ask_mvi

    Internally, requests now go to Hugging Face instead of
    the MVI Space.

    This lets us migrate services.ai_service.py separately.
    """

    return ask_hf(
        text=text,
        system_prompt=system_prompt,
        session_id=session_id,
    )


# =========================================================
# REPLICATE CLIENT
# =========================================================

def get_replicate_headers():
    """
    Return headers required by Replicate.
    """

    api_token = (
        os.environ.get(
            "REPLICATE_API_TOKEN"
        )
        or ""
    ).strip()

    if not api_token:

        raise RuntimeError(
            "REPLICATE_API_TOKEN is not set"
        )

    return {
        "Authorization": (
            f"Token {api_token}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_replicate_prediction(
    version: str,
    input_data: dict,
):
    """
    Create a Replicate prediction.

    Kept separate from the Hugging Face text-generation
    pipeline so image/video functionality is not affected.
    """

    headers = get_replicate_headers()

    response = requests.post(
        REPLICATE_API_URL,
        headers=headers,
        json={
            "version": version,
            "input": input_data,
        },
        timeout=(
            10,
            600,
        ),
    )

    response.raise_for_status()

    return response.json()