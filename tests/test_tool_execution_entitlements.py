"""Premium engineering tools must be denied before the USECT-ZERO dispatcher runs."""
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import ai as ai_routes
from fastapi_routes import chat as chat_routes
from fastapi_routes import stream as stream_routes


def _denied():
    return JSONResponse(
        {
            "status": "error",
            "code": "premium_entitlement_required",
            "message": "Start a Smart AI trial or subscription to use engineering tools.",
        },
        status_code=402,
    )


def test_ai_endpoint_gates_matched_usect_tool_before_process_message(monkeypatch):
    monkeypatch.setattr(ai_routes, "_subject_from_bearer", lambda _token: "user-1")
    monkeypatch.setattr(
        ai_routes,
        "authenticate_identity",
        lambda *args, **kwargs: (None, "user-1", None),
    )
    monkeypatch.setattr(
        ai_routes,
        "build_global_context",
        lambda **kwargs: ([], {
            "hub": "general",
            "hubRequested": "auto",
            "hubDetected": "general",
            "interactionTone": "neutral",
            "capabilities": [],
        }),
    )
    monkeypatch.setattr(ai_routes, "classify_intent", lambda _message: "engineering")
    monkeypatch.setattr(ai_routes, "select_tool_for_message", lambda *args, **kwargs: ("scan", {}))
    monkeypatch.setattr(
        ai_routes,
        "check_entitlement",
        lambda _token, *, feature, **kwargs: (None, _denied()) if feature == "automation" else ({"allowed": True}, None),
    )
    monkeypatch.setattr(
        ai_routes,
        "process_message",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("process_message must not dispatch a USECT tool after denial")
        ),
    )

    result = ai_routes._ai_sync(
        {"message": "scan my configured repository"},
        None,
        None,
        None,
        {"authorization": "Bearer signed-test-token"},
        {},
        "request-1",
        "https://revelaai.example/",
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 402
    assert result.body and b"premium_entitlement_required" in result.body


def test_chat_endpoint_gates_matched_usect_tool_before_process_message(monkeypatch):
    monkeypatch.setattr(
        chat_routes,
        "authenticate_identity",
        lambda *args, **kwargs: (None, "user-1", None),
    )
    monkeypatch.setattr(chat_routes, "classify_intent", lambda _message: "engineering")
    monkeypatch.setattr(chat_routes, "select_tool_for_message", lambda *args, **kwargs: ("scan", {}))
    monkeypatch.setattr(
        chat_routes,
        "check_entitlement",
        lambda _token, *, feature, **kwargs: (None, _denied()) if feature == "automation" else ({"allowed": True}, None),
    )
    monkeypatch.setattr(
        chat_routes,
        "process_message",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("chat must not dispatch a USECT tool after denial")
        ),
    )

    result = chat_routes._chat_sync(
        {"message": "scan my configured repository"},
        {"authorization": "Bearer signed-test-token"},
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 402
    assert result.body and b"premium_entitlement_required" in result.body


def test_stream_endpoint_gates_matched_usect_tool_before_process_message(monkeypatch):
    monkeypatch.setattr(stream_routes, "classify_intent", lambda _message: "engineering")
    monkeypatch.setattr(stream_routes, "select_tool_for_message", lambda *args, **kwargs: ("scan", {}))
    monkeypatch.setattr(
        stream_routes,
        "check_entitlement",
        lambda _token, *, feature, **kwargs: (None, _denied()) if feature == "automation" else ({"allowed": True}, None),
    )
    monkeypatch.setattr(
        stream_routes,
        "process_message",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("stream must not dispatch a USECT tool after denial")
        ),
    )

    response = TestClient(app).post(
        "/ai/stream",
        headers={"Authorization": "Bearer signed-test-token"},
        json={"message": "scan my configured repository"},
    )

    assert response.status_code == 402
    assert response.json()["code"] == "premium_entitlement_required"


def test_direct_core_mesh_tool_execution_requires_smart_ai_automation(monkeypatch):
    from fastapi_routes import core_mesh as core_mesh_routes
    from starlette.requests import Request

    denied = _denied()
    monkeypatch.setattr(
        core_mesh_routes,
        "check_entitlement",
        lambda *args, **kwargs: (None, denied),
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/core-mesh/tools/execute",
        "headers": [(b"authorization", b"Bearer signed-test-token")],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
        "scheme": "http",
    }
    request = Request(scope)
    result = core_mesh_routes._smart_ai_automation_entitlement_error(request)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 402
