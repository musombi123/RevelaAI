from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core_billing.licensing import create_license_token
from revela_platform import database
import revela_platform.fastapi_app as platform


@pytest.fixture
def api_env(monkeypatch, tmp_path):
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setenv("REVELA_LICENSE_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("REVELA_LICENSE_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("JWT_SECRET", "unit-test-jwt-secret-not-for-production")
    monkeypatch.setenv("REVELA_MARKETPLACE_REVIEWER_IDS", "reviewer-1")
    monkeypatch.setattr(platform, "initialize_database", lambda: None)
    monkeypatch.setattr(platform, "AuditLedger", lambda: __import__(
        "core_auditor.ledger", fromlist=["AuditLedger"]
    ).AuditLedger(tmp_path / "audit.jsonl"))

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr(platform, "SessionLocal", test_session_factory)

    def fake_rvx_call(route, packet, *, timeout=8.0):
        return {"adapter_route": route, "received_input": packet.get("input"), "executed": True}

    monkeypatch.setattr(platform, "rvx_call", fake_rvx_call)

    def issue_license(user_id: str, plan: str = "pro", country: str = "KE"):
        token, claims = create_license_token(user_id=user_id, plan_id=plan, country=country)
        plan_info = platform.get_plan(plan)
        with test_session_factory() as session:
            session.add(database.LicenseRecord(
                id=claims["jti"], user_id=user_id, plan=plan, country=country,
                tool_limit=plan_info.tool_limit if plan_info.tool_limit is not None else -1,
                status="active",
                expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc),
                checkout_intent_id="checkout-" + claims["jti"],
            ))
            session.commit()
        return token, claims

    def bearer(user_id: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {"sub": user_id, "iat": now, "exp": now + 3600},
            "unit-test-jwt-secret-not-for-production",
            algorithm="HS256",
        )

    def add_tool(*, tool_id: str, creator: str, price: int = 1000, build_id: str | None = None):
        with test_session_factory() as session:
            session.add(database.ToolRecord(
                id=tool_id, creator_user_id=creator, name=f"Tool {tool_id}",
                description="A documented tool for isolated revenue acceptance tests.",
                industry="automation", country_origin="KE", endpoint=f"/v1/{tool_id}",
                factory_build_id=build_id, price_usd_cents=price, status="published",
                bom_by_country={"KE": {"currency": "KES", "items": []}, "US": {"currency": "USD", "items": []}},
                guides_by_language={"en": "English guide", "sw": "Mwongozo wa Kiswahili"},
            ))
            session.commit()

    # app.on_startup calls the monkeypatched no-op, while every database access
    # in the route/middleware uses the in-memory session factory above.
    client = TestClient(platform.app)
    with client:
        yield {
            "client": client,
            "session_factory": test_session_factory,
            "issue_license": issue_license,
            "bearer": bearer,
            "add_tool": add_tool,
            "private": private,
        }
    engine.dispose()


def test_registered_tool_requires_valid_license_and_meter_counts_denials(api_env):
    client = api_env["client"]
    api_env["add_tool"](tool_id="demo-tool", creator="owner-1")
    license_key, claims = api_env["issue_license"]("owner-1")
    headers = {
        "Authorization": "Bearer " + api_env["bearer"]("owner-1"),
        "X-Revela-License": license_key,
        "X-Country": "KE",
    }

    success = client.post("/v1/demo-tool", headers=headers, json={"job": "inspect"})
    assert success.status_code == 200
    assert success.json()["result"]["executed"] is True
    assert success.json()["result"]["received_input"] == {"job": "inspect"}
    assert success.json()["runtime"] == "rvx_mesh"

    missing = client.post("/v1/demo-tool", headers={
        "Authorization": headers["Authorization"], "X-Country": "KE"
    }, json={"job": "inspect"})
    assert missing.status_code == 402

    expired_claims = dict(claims)
    expired_claims["offline_until"] = int(time.time()) - 10
    expired = jwt.encode(expired_claims, api_env["private"], algorithm="EdDSA")
    expired_response = client.post("/v1/demo-tool", headers={
        "Authorization": headers["Authorization"], "X-Revela-License": expired, "X-Country": "KE"
    }, json={"job": "inspect"})
    assert expired_response.status_code == 402

    summary = client.get("/v1/meter/usage?country=KE", headers={
        "Authorization": headers["Authorization"]
    })
    assert summary.status_code == 200
    data = summary.json()
    assert data["total_calls"] == 3
    assert data["successful_calls"] == 1
    assert data["cost_saved_usd"] == 0.0
    assert data["cost_saved_per_country"]["KE"]["calls"] == 3


def test_marketplace_split_is_exact_and_checkout_is_not_payment_confirmation(api_env, monkeypatch):
    client = api_env["client"]
    api_env["add_tool"](tool_id="kenyan-tool", creator="seller-1", price=9999)
    buyer_license, _claims = api_env["issue_license"]("buyer-1", country="US")

    async def fake_checkout(**kwargs):
        assert kwargs["amount_cents"] == 9999
        assert kwargs["subscription"] is False
        return {
            "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_only",
            "session_id": "cs_test_marketplace_1",
        }

    monkeypatch.setattr(platform, "create_stripe_checkout", fake_checkout)
    response = client.post(
        "/v1/marketplace/buy",
        headers={"Authorization": "Bearer " + api_env["bearer"]("buyer-1")},
        json={"tool_id": "kenyan-tool", "license_key": buyer_license, "buyer_country": "US"},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["creator_share_usd"] == 69.99
    assert payload["platform_share_usd"] == 30.0
    assert payload["status"] == "pending_payment"

    with api_env["session_factory"]() as session:
        intent = session.get(database.CheckoutIntent, payload["purchase_id"])
        assert intent is not None
        assert intent.status == "checkout_pending"
        assert intent.creator_share_cents == 6999
        assert intent.platform_share_cents == 3000
        assert session.execute(select(database.CreatorEarning)).scalars().all() == []


def test_foundry_and_tool_routes_are_visible_in_fastapi_schema(api_env):
    schema = api_env["client"].get("/v1/platform/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/v1/foundry/build" in paths
    assert "/v1/seed/{build_id}" in paths
    assert "/v1/auditor/verify" in paths
    assert "/v1/{tool_id}" in paths
