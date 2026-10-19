"""Framework-neutral audio MIME utilities."""
from __future__ import annotations

_AUDIO_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/webm": ".webm",
}


def audio_extension_for_mime(mime_type: str | None) -> str:
    """Return a conservative extension for a configured TTS output MIME type."""
    return _AUDIO_EXTENSIONS.get(str(mime_type or "").lower(), ".audio")
