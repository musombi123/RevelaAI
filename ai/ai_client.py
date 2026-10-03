# ai/ai_client.py

"""
RevelaAI AI Client

Text generation:
    Hugging Face Inference Providers

Image generation:
    Hugging Face Inference Providers

Speech recognition:
    Hugging Face Inference Providers

Text-to-speech:
    Hugging Face Inference Providers

Architecture:

    RevelaAI
        |
        └---- Hugging Face
                 |
                 ├── Text: GPT-OSS
                 ├── Image: FLUX
                 ├── ASR: Whisper
                 └── TTS: Kokoro

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

HF_TOKEN = (
    os.getenv(
        "HF_TOKEN",
        "",
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


# =========================================================
# TEXT MODEL CONFIGURATION
# =========================================================

HF_MODEL = (
    os.getenv(
        "HF_MODEL",
        "openai/gpt-oss-120b:cheapest",
    )
    .strip()
)

HF_FALLBACK_MODEL = (
    os.getenv(
        "HF_FALLBACK_MODEL",
        "openai/gpt-oss-20b:cheapest",
    )
    .strip()
)


# =========================================================
# IMAGE MODEL CONFIGURATION
# =========================================================

HF_IMAGE_MODEL = (
    os.getenv(
        "HF_IMAGE_MODEL",
        "black-forest-labs/FLUX.1-schnell",
    )
    .strip()
)

HF_IMAGE_FALLBACK_MODEL = (
    os.getenv(
        "HF_IMAGE_FALLBACK_MODEL",
        "",
    )
    .strip()
)


# =========================================================
# VOICE MODEL CONFIGURATION
# =========================================================

HF_ASR_MODEL = (
    os.getenv(
        "HF_ASR_MODEL",
        "openai/whisper-large-v3",
    )
    .strip()
)

HF_TTS_MODEL = (
    os.getenv(
        "HF_TTS_MODEL",
        "hexgrad/Kokoro-82M",
    )
    .strip()
)

HF_TTS_MIME_TYPE = (
    os.getenv(
        "HF_TTS_MIME_TYPE",
        "audio/wav",
    )
    .strip()
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
# IMAGE GENERATION PARAMETERS
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

HF_IMAGE_DEFAULT_STEPS = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_STEPS",
        "4",
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
    ):
        super().__init__(message)

        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code


# =========================================================
# HUGGING FACE CONFIGURATION CHECK
# =========================================================

def hf_configured() -> bool:
    """
    Return whether Hugging Face is configured.
    """

    return bool(
        HF_TOKEN
    )


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
    Build OpenAI-compatible chat messages.
    """

    messages: list[dict[str, str]] = []

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
# HUGGING FACE INFERENCE CLIENT
# =========================================================

def _get_inference_client():
    """
    Create a Hugging Face InferenceClient.

    Used for image generation, ASR, and TTS.
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

    return InferenceClient(
        api_key=HF_TOKEN,
    )


# =========================================================
# HUGGING FACE IMAGE GENERATION
# =========================================================

def generate_hf_image(
    prompt: str,
    *,
    model: str | None = None,
    negative_prompt: str | None = None,
    width: int = HF_IMAGE_DEFAULT_WIDTH,
    height: int = HF_IMAGE_DEFAULT_HEIGHT,
    num_inference_steps: int | None = HF_IMAGE_DEFAULT_STEPS,
    guidance_scale: float | None = None,
    seed: int | None = None,
):
    """
    Generate an image through Hugging Face Inference Providers.

    Returns:
        PIL.Image.Image
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

    selected_model = (
        str(
            model
        ).strip()
        if model
        else HF_IMAGE_MODEL
    )

    if not selected_model:

        raise AIClientError(
            "No Hugging Face image model is configured.",
            provider="huggingface",
            error_code="image_model_missing",
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
            "Image width and height must be integers.",
            provider="huggingface",
            error_code="invalid_image_dimensions",
        ) from exc

    if width < 256 or width > 2048:

        raise AIClientError(
            "Image width must be between 256 and 2048 pixels.",
            provider="huggingface",
            error_code="invalid_image_width",
        )

    if height < 256 or height > 2048:

        raise AIClientError(
            "Image height must be between 256 and 2048 pixels.",
            provider="huggingface",
            error_code="invalid_image_height",
        )

    client = _get_inference_client()

    start = time.time()

    try:

        image = client.text_to_image(
            prompt=prompt,
            model=selected_model,
            negative_prompt=(
                str(
                    negative_prompt
                ).strip()
                if negative_prompt
                else None
            ),
            width=width,
            height=height,
            num_inference_steps=(
                int(
                    num_inference_steps
                )
                if num_inference_steps is not None
                else None
            ),
            guidance_scale=(
                float(
                    guidance_scale
                )
                if guidance_scale is not None
                else None
            ),
            seed=(
                int(seed)
                if seed is not None
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

        fallback_model = (
            HF_IMAGE_FALLBACK_MODEL
        )

        if (
            fallback_model
            and fallback_model != selected_model
        ):

            print(
                "HF image fallback | "
                f"model={fallback_model}"
            )

            try:

                image = client.text_to_image(
                    prompt=prompt,
                    model=fallback_model,
                    negative_prompt=(
                        str(
                            negative_prompt
                        ).strip()
                        if negative_prompt
                        else None
                    ),
                    width=width,
                    height=height,
                    num_inference_steps=(
                        int(
                            num_inference_steps
                        )
                        if num_inference_steps is not None
                        else None
                    ),
                    guidance_scale=(
                        float(
                            guidance_scale
                        )
                        if guidance_scale is not None
                        else None
                    ),
                    seed=(
                        int(seed)
                        if seed is not None
                        else None
                    ),
                )

            except Exception as fallback_exc:

                raise AIClientError(
                    "Hugging Face image generation failed.",
                    provider="huggingface",
                    error_code="image_generation_failed",
                ) from fallback_exc

        else:

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
# GENERIC IMAGE ALIAS
# =========================================================

def generate_image(
    prompt: str,
    **kwargs,
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
    Validate a browser-generated WAV file.

    Expected:
        PCM WAV
        16-bit samples
        mono preferred

    The sample rate may be 44100 or 48000 Hz depending
    on the browser/device.
    """

    if not audio:

        raise AIClientError(
            "Audio data is required.",
            provider="huggingface",
            error_code="empty_audio",
        )

    if len(audio) < 44:

        raise AIClientError(
            "Audio is too small to be a valid WAV file.",
            provider="huggingface",
            error_code="invalid_wav",
        )

    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":

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
            "The uploaded WAV file could not be decoded.",
            provider="huggingface",
            error_code="invalid_wav",
        ) from exc

    if compression != "NONE":

        raise AIClientError(
            "Compressed WAV audio is not supported. "
            "Please send PCM WAV audio.",
            provider="huggingface",
            error_code="unsupported_wav_compression",
        )

    if channels < 1:

        raise AIClientError(
            "WAV contains no audio channels.",
            provider="huggingface",
            error_code="invalid_wav_channels",
        )

    if sample_width != 2:

        raise AIClientError(
            "Voice input must use 16-bit PCM WAV audio.",
            provider="huggingface",
            error_code="unsupported_wav_bit_depth",
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
# VOICE — SPEECH TO TEXT
# =========================================================

def transcribe_hf_audio(
    audio: bytes,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Transcribe browser-generated WAV audio through
    Hugging Face Inference Providers.

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
            error_code="hf_token_missing",
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
            error_code="asr_model_missing",
        )

    audio_info = _inspect_wav_audio(
        audio
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

    # Whisper is explicitly routed through fal-ai.
    # Do NOT change the global _get_inference_client()
    # to fal-ai because image/TTS use that shared client.
    client = InferenceClient(
        api_key=HF_TOKEN,
        provider="fal-ai",
    )

    start = time.time()

    try:

        result = client.automatic_speech_recognition(
            audio=audio,
            model=selected_model,
        )

    except Exception as exc:

        elapsed = (
            time.time() - start
        )

        print(
            "HF ASR failed | "
            f"model={selected_model} | "
            "provider=fal-ai | "
            f"bytes={audio_info['bytes']} | "
            f"duration={audio_info['duration_seconds']}s | "
            f"sample_rate={audio_info['sample_rate']} | "
            f"channels={audio_info['channels']} | "
            f"time={elapsed:.2f}s"
        )

        raise AIClientError(
            "Hugging Face speech recognition failed.",
            provider="huggingface",
            error_code="asr_failed",
        ) from exc

    elapsed = (
        time.time() - start
    )

    transcript = getattr(
        result,
        "text",
        None,
    )

    if transcript is None and isinstance(
        result,
        dict,
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
        f"time={elapsed:.2f}s | "
        f"text_length={len(transcript)}"
    )

    if not transcript:

        raise AIClientError(
            "No recognizable speech was detected "
            "in the recording.",
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

    Returns:
        Raw audio bytes.

    The provider/model determines the actual audio encoding.
    """

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

    client = _get_inference_client()

    start = time.time()

    extra_body: dict[str, Any] = {}

    if voice:

        voice_value = str(
            voice
        ).strip()

        if voice_value:

            extra_body["voice"] = (
                voice_value
            )

    try:

        audio = client.text_to_speech(
            text=text,
            model=selected_model,
            extra_body=(
                extra_body
                if extra_body
                else None
            ),
            **generation_kwargs,
        )

    except Exception as exc:

        elapsed = (
            time.time() - start
        )

        print(
            "HF TTS failed | "
            f"model={selected_model} | "
            f"time={elapsed:.2f}s"
        )

        raise AIClientError(
            "Hugging Face text-to-speech failed.",
            provider="huggingface",
            error_code="tts_failed",
        ) from exc

    elapsed = (
        time.time() - start
    )

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
        f"time={elapsed:.2f}s | "
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
# HF CHAT REQUEST
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

    elapsed = (
        time.time() - start
    )

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
        text=str(text),
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

        fallback_model = (
            HF_FALLBACK_MODEL
        )

        if (
            not fallback_model
            or fallback_model == primary_model
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
    "generate_hf_image",
    "generate_image",
    "transcribe_hf_audio",
    "generate_hf_speech",
    "ask_hf",
    "ask_mvi",
]