"""
RevelaAI AI Client

Server-side provider client for:
- Text generation via Hugging Face Inference Providers
- Image generation via Hugging Face Inference Providers
- Speech recognition via Hugging Face Inference Providers
- Text-to-speech via Hugging Face Inference Providers

Canva-style image-generation foundation:
- Stable model/provider routing
- Text-aware image routing
- Aspect-ratio presets
- Safe dimension validation
- Model fallback
- Seed support
- Backward compatibility

IMPORTANT:
HF_TOKEN must remain server-side.
It must NEVER be exposed to the frontend.
"""

from __future__ import annotations

import io
import os
import time
import wave
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

HF_TOKEN = os.getenv(
    "HF_TOKEN",
    "",
).strip()

HF_API_URL = os.getenv(
    "HF_API_URL",
    "https://router.huggingface.co/v1/chat/completions",
).strip()


# =========================================================
# TEXT MODEL CONFIGURATION
# =========================================================

HF_MODEL = os.getenv(
    "HF_MODEL",
    "openai/gpt-oss-120b:cheapest",
).strip()

HF_FALLBACK_MODEL = os.getenv(
    "HF_FALLBACK_MODEL",
    "openai/gpt-oss-20b:cheapest",
).strip()


# =========================================================
# IMAGE MODEL CONFIGURATION
# =========================================================

# Primary image model.
HF_IMAGE_MODEL = os.getenv(
    "HF_IMAGE_MODEL",
    "black-forest-labs/FLUX.1-dev",
).strip()


# Optional dedicated model for images where text matters.
#
# Examples:
# - posters
# - banners
# - labels
# - flyers
# - branded graphics
# - social media cards
#
# Leave empty if you want the normal image model.
HF_IMAGE_TEXT_MODEL = os.getenv(
    "HF_IMAGE_TEXT_MODEL",
    "",
).strip()


# Image fallback model.
HF_IMAGE_FALLBACK_MODEL = os.getenv(
    "HF_IMAGE_FALLBACK_MODEL",
    "black-forest-labs/FLUX.1-schnell",
).strip()


# Provider routing.
#
# Empty:
#     Hugging Face automatically selects the provider.
#
# Example:
#     fal-ai
HF_IMAGE_PROVIDER = os.getenv(
    "HF_IMAGE_PROVIDER",
    "",
).strip()

HF_IMAGE_TEXT_PROVIDER = os.getenv(
    "HF_IMAGE_TEXT_PROVIDER",
    "",
).strip()


# =========================================================
# IMAGE SIZE PRESETS
# =========================================================
#
# These are deliberately human-friendly.
# The future Canva-style API can say:
#
#     aspect_ratio="square"
#     aspect_ratio="story"
#     aspect_ratio="banner"
#
# instead of passing pixels everywhere.
#

IMAGE_SIZE_PRESETS: dict[str, tuple[int, int]] = {

    # 1:1
    "square": (
        1024,
        1024,
    ),

    # ~2:3
    "portrait": (
        832,
        1216,
    ),

    # ~3:2
    "landscape": (
        1216,
        832,
    ),

    # 16:9
    "wide": (
        1536,
        864,
    ),

    # 9:16
    "story": (
        864,
        1536,
    ),

    # 3:1
    "banner": (
        1536,
        512,
    ),

    # 4:5
    "social_portrait": (
        1088,
        1360,
    ),

    # ~16:9 social landscape
    "social_landscape": (
        1360,
        768,
    ),

    # presentation
    "presentation": (
        1280,
        720,
    ),

    # mobile canvas
    "phone": (
        768,
        1365,
    ),
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
# IMPORTANT:
# Leave this empty by default.
#
# That allows _model_defaults() to choose:
#
# FLUX schnell -> 4
# FLUX dev    -> 28
#
# instead of accidentally forcing every FLUX model
# to run at 4 steps.
#

_steps_env = os.getenv(
    "HF_IMAGE_DEFAULT_STEPS",
    "",
).strip()

HF_IMAGE_DEFAULT_STEPS = (
    int(_steps_env)
    if _steps_env
    else None
)


# =========================================================
# VOICE MODEL CONFIGURATION
# =========================================================

HF_ASR_MODEL = os.getenv(
    "HF_ASR_MODEL",
    "openai/whisper-large-v3",
).strip()


HF_TTS_MODEL = os.getenv(
    "HF_TTS_MODEL",
    "hexgrad/Kokoro-82M",
).strip()


HF_TTS_MIME_TYPE = (
    os.getenv(
        "HF_TTS_MIME_TYPE",
        "audio/wav",
    ).strip()
    or "audio/wav"
)


# =========================================================
# TIMEOUTS
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
# TEXT GENERATION PARAMETERS
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
# HUGGING FACE CONFIGURATION CHECK
# =========================================================


def hf_configured() -> bool:
    """
    Return whether Hugging Face credentials are configured.
    """

    return bool(HF_TOKEN)


# =========================================================
# HUGGING FACE HEADERS
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
        "Authorization": f"Bearer {HF_TOKEN}",
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

    return str(value)


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
    Build OpenAI-compatible chat messages.
    """

    messages: list[dict[str, str]] = []

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
        options["provider"] = provider

    if timeout:
        options["timeout"] = timeout

    return InferenceClient(
        **options
    )


# =========================================================
# IMAGE MODEL DEFAULTS
# =========================================================


def _model_defaults(
    model: str,
) -> dict[str, Any]:
    """
    Best-known starting settings per model family.
    """

    name = model.lower()

    # FLUX schnell:
    # designed for very few inference steps.
    if "schnell" in name:

        return {
            "steps": 4,
            "guidance": None,
            "supports_negative": False,
        }

    # FLUX dev:
    if "flux" in name:

        return {
            "steps": 28,
            "guidance": 3.5,
            "supports_negative": False,
        }

    # Qwen image family:
    if "qwen-image" in name:

        return {
            "steps": 30,
            "guidance": 4.0,
            "supports_negative": True,
        }

    # Generic diffusion fallback.
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
    """
    Resolve provider routing for the requested image model.

    Text-heavy generation:
        HF_IMAGE_TEXT_MODEL
        +
        HF_IMAGE_TEXT_PROVIDER

    Normal image generation:
        HF_IMAGE_MODEL
        +
        HF_IMAGE_PROVIDER
    """

    if (
        has_text
        and HF_IMAGE_TEXT_MODEL
        and model == HF_IMAGE_TEXT_MODEL
    ):

        return HF_IMAGE_TEXT_PROVIDER

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
    """
    True when the provider rejected request parameters.
    """

    return (
        isinstance(
            exc,
            (
                TypeError,
                ValueError,
            ),
        )
        or _status_code(exc)
        in (
            400,
            422,
        )
    )


# =========================================================
# IMAGE DIMENSION RESOLUTION
# =========================================================


def resolve_image_dimensions(
    *,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
) -> tuple[int, int]:
    """
    Resolve final image dimensions.

    Explicit width/height take precedence.

    Otherwise:
        aspect_ratio preset
        ->
        configured default
    """

    # -----------------------------------------------------
    # Explicit dimensions
    # -----------------------------------------------------

    if (
        width is not None
        or height is not None
    ):

        if width is None:
            width = HF_IMAGE_DEFAULT_WIDTH

        if height is None:
            height = HF_IMAGE_DEFAULT_HEIGHT

    # -----------------------------------------------------
    # Preset
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Default
    # -----------------------------------------------------

    else:

        width = HF_IMAGE_DEFAULT_WIDTH
        height = HF_IMAGE_DEFAULT_HEIGHT

    # -----------------------------------------------------
    # Integer validation
    # -----------------------------------------------------

    try:

        width = int(width)
        height = int(height)

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

    # -----------------------------------------------------
    # Width limits
    # -----------------------------------------------------

    if width < 256 or width > 2048:

        raise AIClientError(
            (
                "Image width must be "
                "between 256 and 2048 pixels."
            ),
            provider="huggingface",
            error_code="invalid_image_width",
        )

    # -----------------------------------------------------
    # Height limits
    # -----------------------------------------------------

    if height < 256 or height > 2048:

        raise AIClientError(
            (
                "Image height must be "
                "between 256 and 2048 pixels."
            ),
            provider="huggingface",
            error_code="invalid_image_height",
        )

    return width, height


# =========================================================
# ONE IMAGE GENERATION ATTEMPT
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
    """
    Generate one image on one model.

    If optional parameters are rejected,
    retry once with only the basic parameters.
    """

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
        ] = int(seed)

    negative = str(
        negative_prompt or ""
    ).strip()

    # FLUX models generally do not need
    # negative_prompt and providers may reject it.
    if (
        negative
        and defaults[
            "supports_negative"
        ]
    ):

        params[
            "negative_prompt"
        ] = negative

    # -----------------------------------------------------
    # Primary attempt
    # -----------------------------------------------------

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

        # -------------------------------------------------
        # Minimal compatibility retry
        # -------------------------------------------------

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
    """
    Generate an image through Hugging Face
    Inference Providers.

    Model selection:

        1. Explicit model
        2. HF_IMAGE_TEXT_MODEL when has_text=True
        3. HF_IMAGE_MODEL

    Failure order:

        selected model
        ->
        HF_IMAGE_FALLBACK_MODEL
        ->
        HF_IMAGE_MODEL

    Returns:
        PIL.Image.Image
    """

    # =====================================================
    # PROMPT
    # =====================================================

    prompt = str(
        prompt or ""
    ).strip()

    if not prompt:

        raise AIClientError(
            "Image prompt is required.",
            provider="huggingface",
            error_code=(
                "empty_image_prompt"
            ),
        )

    # =====================================================
    # PRIMARY MODEL
    # =====================================================

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
            error_code=(
                "image_model_missing"
            ),
        )

    # =====================================================
    # DIMENSIONS
    # =====================================================

    width, height = (
        resolve_image_dimensions(
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
        )
    )

    # =====================================================
    # CANDIDATE MODELS
    # =====================================================

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
            and candidate
            not in candidates
        ):

            candidates.append(
                candidate
            )

    # =====================================================
    # GENERATION
    # =====================================================

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

        # -------------------------------------------------
        # Empty response
        # -------------------------------------------------

        if image is None:

            print(
                "HF image generation returned nothing | "
                f"model={candidate} | "
                f"provider={provider or 'auto'}"
            )

            continue

        # -------------------------------------------------
        # Success
        # -------------------------------------------------

        print(
            "HF image generation succeeded | "
            f"model={candidate} | "
            f"provider={provider or 'auto'} | "
            f"has_text={has_text} | "
            f"size={width}x{height} | "
            f"time={time.time() - started:.2f}s"
        )

        return image

    # =====================================================
    # TOTAL FAILURE
    # =====================================================

    raise AIClientError(
        "Hugging Face image generation failed.",
        provider="huggingface",
        error_code=(
            "image_generation_failed"
        ),
    ) from last_error


# =========================================================
# GENERIC IMAGE ALIAS
# =========================================================


def generate_image(
    prompt: str,
    **kwargs: Any,
):
    """
    Canonical RevelaAI image-generation entry point.
    """

    return generate_hf_image(
        prompt=prompt,
        **kwargs,
    )


# =========================================================
# VOICE — WAV VALIDATION
# =========================================================


def _inspect_wav_audio(
    audio: bytes,
) -> dict[str, Any]:
    """
    Validate browser-generated PCM WAV audio.

    Expected:
        PCM WAV
        16-bit samples

    Mono is preferred, but stereo is accepted.
    """

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

            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            compression = wav.getcomptype()

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
            error_code=(
                "unsupported_sample_rate"
            ),
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
# VOICE — SPEECH TO TEXT
# =========================================================


def transcribe_hf_audio(
    audio: bytes,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Transcribe browser-generated WAV audio.

    The frontend does NOT perform transcription.
    """

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
            error_code=(
                "hf_token_missing"
            ),
        )

    selected_model = (
        str(model).strip()
        if model
        else HF_ASR_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Hugging Face ASR model is configured.",
            provider="huggingface",
            error_code=(
                "asr_model_missing"
            ),
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
            error_code=(
                "huggingface_hub_missing"
            ),
        ) from exc

    # Whisper remains explicitly routed through fal-ai.
    #
    # Do NOT modify the shared image/TTS client
    # to force fal-ai globally.
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
            (
                "Hugging Face speech "
                "recognition failed."
            ),
            provider="huggingface",
            error_code="asr_failed",
        ) from exc

    # -----------------------------------------------------
    # Extract transcript
    # -----------------------------------------------------

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

        transcript = result.get(
            "text"
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
            error_code=(
                "empty_transcription"
            ),
        )

    return {
        "success": True,
        "text": transcript,
        "provider": "huggingface",
        "model": selected_model,
        "audio": audio_info,
    }


# =========================================================
# VOICE — TEXT TO SPEECH
# =========================================================


def generate_hf_speech(
    text: str,
    model: str | None = None,
    voice: str | None = None,
    **generation_kwargs: Any,
) -> bytes:
    """
    Generate speech using Hugging Face TTS.

    Returns raw audio bytes.
    """

    text = str(
        text or ""
    ).strip()

    if not text:

        raise AIClientError(
            "Speech text is required.",
            provider="huggingface",
            error_code=(
                "empty_speech_text"
            ),
        )

    if not HF_TOKEN:

        raise AIClientError(
            "HF_TOKEN is not configured.",
            provider="huggingface",
            error_code=(
                "hf_token_missing"
            ),
        )

    selected_model = (
        str(model).strip()
        if model
        else HF_TTS_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Hugging Face TTS model is configured.",
            provider="huggingface",
            error_code=(
                "tts_model_missing"
            ),
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
            (
                "Hugging Face text-to-speech "
                "failed."
            ),
            provider="huggingface",
            error_code="tts_failed",
        ) from exc

    if not audio:

        raise AIClientError(
            "Hugging Face returned empty audio.",
            provider="huggingface",
            error_code=(
                "empty_audio_response"
            ),
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
                (
                    "Hugging Face returned "
                    "invalid audio data."
                ),
                provider="huggingface",
                error_code=(
                    "invalid_audio_response"
                ),
            ) from exc

    print(
        "HF TTS succeeded | "
        f"model={selected_model} | "
        f"time={time.time() - started:.2f}s | "
        f"bytes={len(audio)}"
    )

    return audio


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
            error_code=(
                "empty_model_response"
            ),
        )

    first_choice = choices[0]

    if not isinstance(
        first_choice,
        dict,
    ):

        raise AIClientError(
            (
                "Hugging Face returned "
                "an invalid choice."
            ),
            provider="huggingface",
            error_code=(
                "invalid_model_response"
            ),
        )

    message = first_choice.get(
        "message"
    )

    if not isinstance(
        message,
        dict,
    ):

        raise AIClientError(
            (
                "Hugging Face returned "
                "no assistant message."
            ),
            provider="huggingface",
            error_code=(
                "missing_assistant_message"
            ),
        )

    content = message.get(
        "content"
    )

    if content is None:
        content = ""

    # Some providers may return content parts.
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
            (
                "Hugging Face returned "
                "an empty response."
            ),
            provider="huggingface",
            error_code=(
                "empty_response"
            ),
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
# HF CHAT REQUEST
# =========================================================


def _request_hf(
    *,
    model: str,
    messages: list[dict[str, str]],
) -> dict:
    """
    Send a chat completion request
    to Hugging Face.
    """

    headers = get_hf_headers()

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
            error_code=(
                "hf_connection_error"
            ),
        ) from exc

    except requests.RequestException as exc:

        raise AIClientError(
            "Hugging Face request failed.",
            provider="huggingface",
            error_code=(
                "hf_request_error"
            ),
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
            error_code=(
                "invalid_response"
            ),
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
    Generate an answer using Hugging Face
    Inference Providers.
    """

    if not str(
        text or ""
    ).strip():

        return {
            "success": False,
            "response": "",
            "error": "message is required",
            "error_code": (
                "empty_message"
            ),
            "provider": "huggingface",
        }

    messages = build_messages(
        text=str(text),
        system_prompt=str(
            system_prompt or ""
        ),
        context=context,
    )

    attempted_models: list[str] = []

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
    text: str,
    system_prompt: str = "",
    session_id: str | None = None,
):
    """
    Temporary compatibility alias.

    Existing imports can continue using ask_mvi()
    while they migrate to ask_hf().
    """

    return ask_hf(
        text=text,
        system_prompt=system_prompt,
        session_id=session_id,
    )


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "AIClientError",
    "hf_configured",
    "get_hf_headers",
    "build_messages",

    # Image
    "IMAGE_SIZE_PRESETS",
    "resolve_image_dimensions",
    "generate_hf_image",
    "generate_image",

    # Voice
    "transcribe_hf_audio",
    "generate_hf_speech",

    # Text
    "ask_hf",
    "ask_mvi",
]
