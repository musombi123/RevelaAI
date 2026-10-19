from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mesh.receiver import RVX_CONTENT_TYPE, create_rvx_receiver_router
from rvx.crypto import StalePacketError, open_packet, seal_packet


def test_python_receiver_handles_encrypted_call_and_rejects_replay():
    secret = b"separate-mesh-secret-material-for-test"
    app = FastAPI()
    app.include_router(create_rvx_receiver_router(
        {"one.genesis": lambda packet: {"accepted": packet["demand"]}},
        secret=secret,
    ))
    client = TestClient(app)
    packet = seal_packet({"demand": "bounded-test"}, route="one.genesis", secret=secret)

    response = client.post(
        "/internal/rvx/one.genesis",
        content=json.dumps(packet),
        headers={"Content-Type": RVX_CONTENT_TYPE},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == RVX_CONTENT_TYPE
    assert open_packet(response.json(), route="one.genesis", secret=secret) == {
        "accepted": "bounded-test"
    }

    replay = client.post(
        "/internal/rvx/one.genesis",
        content=json.dumps(packet),
        headers={"Content-Type": RVX_CONTENT_TYPE},
    )
    assert replay.status_code == 401
    assert "authentication or freshness" in replay.json()["detail"]


def test_python_receiver_requires_correct_content_type_and_allowlisted_route():
    secret = b"separate-mesh-secret-material-for-test"
    app = FastAPI()
    app.include_router(create_rvx_receiver_router(
        {"one.genesis": lambda packet: {"ok": True}},
        secret=secret,
    ))
    client = TestClient(app)
    packet = seal_packet({"demand": "x"}, route="one.genesis", secret=secret)
    bad_type = client.post("/internal/rvx/one.genesis", json=packet)
    assert bad_type.status_code == 415
    unknown = client.post(
        "/internal/rvx/zero.heal",
        content=json.dumps(packet),
        headers={"Content-Type": RVX_CONTENT_TYPE},
    )
    assert unknown.status_code == 404
