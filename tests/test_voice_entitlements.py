"""Voice endpoint entitlement tests; they must not call a provider when access is denied."""
from fastapi.responses import JSONResponse

from fastapi_routes import voice as voice_routes


def test_voice_rejects_without_entitlement_before_transcription(monkeypatch):
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(
        voice_routes,
        "check_entitlement",
        lambda *args, **kwargs: (None, denied),
    )
    transcribe = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("transcription must not run after entitlement denial")
    )
    monkeypatch.setattr(voice_routes, "transcribe_hf_audio", transcribe)

    result = voice_routes._voice_sync(
        b"fake audio",
        "audio/wav",
        "verified-user",
        "verified-user:session",
        "https://revelaai.example",
        "Bearer signed-test-token",
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 402
