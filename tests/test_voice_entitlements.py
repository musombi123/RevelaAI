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


def test_voice_forwards_authorization_to_guarded_operator_dispatch(monkeypatch):
    """Voice-triggered tool requests must retain the caller's bearer identity."""
    authorization = "Bearer signed-test-token"
    captured = {}

    monkeypatch.setattr(voice_routes, "check_entitlement", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(voice_routes, "cleanup_generated_files", lambda: None)
    monkeypatch.setattr(
        voice_routes,
        "transcribe_hf_audio",
        lambda *_args, **_kwargs: {"text": "Meta Engineer: scan architecture", "model": "test-asr"},
    )
    monkeypatch.setattr(voice_routes, "detect_capability", lambda *_args, **_kwargs: "text")
    monkeypatch.setattr(voice_routes, "get_session", lambda _session_id: {"messages": []})
    monkeypatch.setattr(voice_routes, "build_server_context", lambda _session: [])
    monkeypatch.setattr(voice_routes, "save_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_routes, "REVELAAI_ENABLE_HF_TTS", False)

    def fake_process_message(**kwargs):
        captured.update(kwargs)
        return {
            "response": "Read-only architecture scan request received.",
            "intent": "meta_engineer_scan",
            "provider": "test",
            "model": "test",
        }

    monkeypatch.setattr(voice_routes, "process_message", fake_process_message)

    result = voice_routes._voice_sync(
        b"fake audio",
        "audio/wav",
        "verified-user",
        "verified-user:session",
        "https://revelaai.example",
        authorization,
    )

    assert captured["authorization"] == authorization
    assert captured["user_id"] == "verified-user"
    assert result["status"] == "success"
    assert result["response"] == "Read-only architecture scan request received."

