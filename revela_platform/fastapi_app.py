"""Native FastAPI revenue gateway for licenses, usage, marketplace and platform tools.

Published tools are license-gated before dispatch. RevelaAI's API is mounted as
a FastAPI ASGI subapplication; no Flask or WSGI runtime is used.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

from core_billing.licensing import LicenseError, create_license_token, verify_license_token
from core_billing.payments import (
    PaymentConfigurationError,
    PaymentProviderError,
    create_stripe_checkout,
    verify_stripe_signature,
)
from core_billing.plans import get_plan
from core_billing.service import enforce_tool_creation_quota, require_active_license
from core_meter.meter import record_usage, usage_summary
from core_foundry.factory.foundry_builder import FactoryBuildError, FoundryBuilder
from core_foundry.attestation import AttestationError, sign_approved_manifest
from core_seed.seed_runner import SeedError, SeedRunner
from core_uncopyable.dna_vault_guard import DnaVaultError, sign_tool_watermark, verify_tool_watermark
from core_uncopyable.license_lock import require_enterprise_claims
from core_auditor.ledger import AuditLedger, AuditLedgerError
from core_auditor.compliance_reports import (
    DRAFT_WARNING,
    SUPPORTED_REPORT_KINDS,
    build_compliance_readiness_pdf,
    canonical_sha256,
)
from core_inspector.inspector import inspect_capabilities
from core_evolve.engine import EvolutionEngine, EvolutionError
from core_evolve.models import EvolutionRequest, MetricTarget
from ai.core_mesh import CoreMeshError, queue_genesis_demand, propose_mind_evolution
from ai.usect_zero_tools import execute_tool as execute_usect_zero_tool
from marketplace.service import country_bundle, creator_earnings, safety_screen
from revela_platform.database import (
    AuditRecord,
    ComplianceReportRecord,
    EvolutionTwinScanRecord,
    FactoryRecord,
    SeedRecord,
    CheckoutIntent,
    CreatorEarning,
    LicenseRecord,
    ProcessedWebhook,
    SessionLocal,
    ToolRating,
    ToolRecord,
    initialize_database,
    utcnow,
)

logger = logging.getLogger("revela_platform.fastapi_app")

app = FastAPI(
    title="RevelaCode Revenue and RVX API",
    version="0.1.0",
    description="Python-native billing, signed licensing, usage metering, marketplace and encrypted RVX integrations.",
    docs_url="/v1/platform/docs",
    openapi_url="/v1/platform/openapi.json",
)

# Keep browser clients on the trusted RevelaCode production domains working
# regardless of whether requests reach this native billing gateway or asgi:app.
# Explicit origins are used with credentials; never use "*" here.
_DEFAULT_CORS_ORIGINS = (
    "https://revelacode.co.ke",
    "https://www.revelacode.co.ke",
    "https://revelacode-frontend.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
_configured_cors_origins = os.getenv("CORS_ORIGINS", "").split(",")
_CORS_ORIGINS = list(dict.fromkeys(
    origin.strip().rstrip("/")
    for origin in (*_DEFAULT_CORS_ORIGINS, *_configured_cors_origins)
    if origin.strip()
))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "userId", "X-User-ID",
        "X-Session-ID", "X-Request-ID", "Accept", "Origin",
        "X-Revela-License", "X-Country", "X-API-Key", "X-Device-Token",
        "X-Admin-Token", "X-Organ-Admin-Token",
    ],
)


def _country(value: str | None) -> str:
    normalized = (value or "KE").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", normalized):
        raise HTTPException(status_code=422, detail="country must be a two-letter ISO country code")
    return normalized


def _claims_from_bearer(authorization: str | None) -> dict[str, Any]:
    token = (authorization or "").strip()
    if not token.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="A RevelaCode Bearer token is required")
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="JWT verification is not configured on this service")
    try:
        claims = jwt.decode(
            token[7:].strip(),
            secret,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Authentication token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid RevelaCode authentication token") from exc
    user_id = claims.get("sub") or claims.get("user_id") or claims.get("id")
    if user_id is None or not str(user_id).strip():
        raise HTTPException(status_code=401, detail="Token has no user identity")
    claims["sub"] = str(user_id).strip()
    return claims


def authenticated_user(authorization: str | None = Header(default=None, alias="Authorization")) -> str:
    return str(_claims_from_bearer(authorization)["sub"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _license_http_error(exc: LicenseError) -> HTTPException:
    reason = str(exc)
    lowered = reason.lower()
    status = 503 if ("not configured" in lowered or "verification is unavailable" in lowered) else 402
    if status == 402 and "expired" in lowered:
        reason = "License expired. Renew your RevelaCode plan."
    return HTTPException(status_code=status, detail=reason)


def _active_license(session: Session, token: str, user_id: str, country: str | None = None,
                    tool_id: str | None = None) -> tuple[dict[str, Any], LicenseRecord]:
    try:
        return require_active_license(session, token, user_id, country=country, tool_id=tool_id)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc


def _audit(session: Session, actor: str, action: str, object_id: str = "",
           detail: dict[str, Any] | None = None) -> None:
    session.add(AuditRecord(actor_user_id=actor, action=action, object_id=object_id, detail=detail or {}))


def _reviewer(user_id: str) -> bool:
    allowed = {
        value.strip()
        for value in (
            os.getenv("REVELA_MARKETPLACE_REVIEWER_IDS", "")
            + ","
            + os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
            + ","
            + os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
        ).split(",")
        if value.strip()
    }
    return user_id in allowed


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@app.on_event("startup")
def _startup() -> None:
    initialize_database()


@app.get("/v1/platform/health", tags=["platform"])
def platform_health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "revelacode-revenue",
        "runtime": "python",
        "api_framework": "fastapi",
        "payment_provider_configured": bool(os.getenv("STRIPE_SECRET_KEY")),
        "license_issuer_configured": bool(os.getenv("REVELA_LICENSE_PRIVATE_KEY") or os.getenv("REVELA_LICENSE_PRIVATE_KEY_PATH")),
    }


@app.get("/v1/billing/plans", tags=["billing"])
def billing_plans() -> dict[str, Any]:
    return {
        "currency": "USD",
        "billing_interval": "monthly",
        "plans": [
            {
                "id": plan.id,
                "price_usd": plan.monthly_usd_cents / 100,
                "tool_limit": plan.tool_limit,
                "worldwide": plan.worldwide,
                "description": plan.description,
            }
            for plan in (get_plan("local"), get_plan("pro"), get_plan("enterprise"))
        ],
        "note": "Local uses the purchase country. Pro and Enterprise are worldwide. Prices are list prices, not FX quotes.",
    }


class BuyPlanInput(BaseModel):
    plan: str = Field(pattern="^(local|pro|enterprise)$")
    country: str = Field(default="KE", min_length=2, max_length=2)


@app.post("/v1/billing/buy", status_code=202, tags=["billing"])
async def buy_plan(body: BuyPlanInput, user_id: str = Depends(authenticated_user),
                   session: Session = Depends(get_db)) -> dict[str, Any]:
    country = _country(body.country)
    plan = get_plan(body.plan)
    intent_id = str(uuid4())
    intent = CheckoutIntent(
        id=intent_id, user_id=user_id, purpose="billing", plan=plan.id,
        country=country, amount_usd_cents=plan.monthly_usd_cents, status="checkout_pending",
    )
    session.add(intent)
    session.commit()
    try:
        checkout = await create_stripe_checkout(
            intent_id=intent_id, user_id=user_id, purpose="billing",
            amount_cents=plan.monthly_usd_cents, name=f"RevelaCode {plan.id.title()} monthly plan",
            country=country, metadata={"plan": plan.id}, subscription=True,
        )
    except (PaymentConfigurationError, PaymentProviderError, ValueError) as exc:
        intent.status = "checkout_failed"
        session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    intent.stripe_session_id = checkout["session_id"]
    session.commit()
    return {
        "intent_id": intent.id,
        "checkout_url": checkout["checkout_url"],
        "session_id": checkout["session_id"],
        "plan": plan.id,
        "country": country,
        "amount_usd": plan.monthly_usd_cents / 100,
        "status": "pending_payment",
        "license": "A license is issued only after the signed payment webhook confirms settlement.",
    }


def _license_for_paid_intent(session: Session, intent: CheckoutIntent, user_id: str) -> dict[str, Any]:
    if intent.user_id != user_id:
        raise HTTPException(status_code=403, detail="Checkout belongs to another user")
    if intent.purpose != "billing" or intent.status != "paid":
        raise HTTPException(status_code=409, detail="Payment is not confirmed; no license can be issued")
    plan = get_plan(intent.plan or "")
    # Rotate the previous token linked to this checkout, allowing safe retries without
    # persisting plaintext bearer tokens. Only the most recently issued key remains active.
    existing = session.execute(
        select(LicenseRecord).where(LicenseRecord.checkout_intent_id == intent.id)
    ).scalars().all()
    for record in existing:
        record.status = "revoked"
    expiry = utcnow() + timedelta(days=30)
    token, claims = create_license_token(
        user_id=user_id, plan_id=plan.id, country=intent.country, expires_at=expiry
    )
    record = LicenseRecord(
        id=claims["jti"], user_id=user_id, plan=plan.id, country=intent.country,
        tool_limit=plan.tool_limit if plan.tool_limit is not None else -1,
        status="active", expires_at=expiry,
        stripe_subscription_id=intent.stripe_subscription_id,
        checkout_intent_id=intent.id,
    )
    session.add(record)
    _audit(session, user_id, "billing.license.issued", record.id,
           {"plan": plan.id, "country": intent.country, "offline_days": 30})
    session.commit()
    return {
        "license_key": token,
        "license_id": record.id,
        "plan": plan.id,
        "country": intent.country,
        "expires_at": _to_iso(expiry),
        "offline_until": datetime.fromtimestamp(claims["offline_until"], timezone.utc).isoformat(),
        "message": "Store this key securely. A later request rotates and revokes the preceding key for this checkout.",
    }


@app.get("/v1/billing/license/{intent_id}", tags=["billing"])
def get_paid_license(intent_id: str, user_id: str = Depends(authenticated_user),
                     session: Session = Depends(get_db)) -> dict[str, Any]:
    intent = session.get(CheckoutIntent, intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Checkout intent not found")
    try:
        return _license_for_paid_intent(session, intent, user_id)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc


@app.get("/v1/billing/verify", tags=["billing"], deprecated=True)
def verify_license_get(license_key: str = Query(min_length=20),
                       user_id: str = Depends(authenticated_user),
                       session: Session = Depends(get_db)) -> dict[str, Any]:
    """Compatibility endpoint; POST is preferred because URLs may be logged."""
    return _verify_license_response(session, license_key, user_id)


class VerifyLicenseInput(BaseModel):
    license_key: str = Field(min_length=20, max_length=12000)


@app.post("/v1/billing/verify", tags=["billing"])
def verify_license_post(body: VerifyLicenseInput, user_id: str = Depends(authenticated_user),
                        session: Session = Depends(get_db)) -> dict[str, Any]:
    return _verify_license_response(session, body.license_key, user_id)


def _verify_license_response(session: Session, license_key: str, user_id: str) -> dict[str, Any]:
    try:
        claims, record = _active_license(session, license_key, user_id)
        return {
            "valid": True, "license_id": record.id, "plan": record.plan, "country": record.country,
            "expires_at": _to_iso(record.expires_at), "worldwide": bool(claims.get("worldwide")),
            "max_tools": claims.get("max_tools"),
        }
    except HTTPException as exc:
        return {"valid": False, "status": exc.status_code, "reason": str(exc.detail)}


@app.post("/v1/billing/webhooks/stripe", tags=["billing"], include_in_schema=True)
async def stripe_webhook(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
    body = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    if not verify_stripe_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
    try:
        event = json.loads(body)
        event_id = str(event["id"])
        event_type = str(event["type"])
        obj = event["data"]["object"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed Stripe event") from exc
    if session.get(ProcessedWebhook, event_id):
        return {"received": True, "duplicate": True}
    now = utcnow()

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if obj.get("payment_status") != "paid":
            return {"received": True, "paid": False}
        metadata = obj.get("metadata") or {}
        intent_id = str(metadata.get("intent_id") or "")
        intent = session.get(CheckoutIntent, intent_id) if intent_id else None
        if intent is None or intent.stripe_session_id != obj.get("id"):
            raise HTTPException(status_code=404, detail="Checkout intent/session mismatch")
        # Bind the signed provider event to the amount, currency and account that
        # the server-side intent expected; never issue entitlements for a mismatch.
        try:
            amount_total = int(obj.get("amount_total"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Checkout event is missing a valid amount_total") from exc
        if amount_total != intent.amount_usd_cents or str(obj.get("currency", "")).lower() != "usd":
            raise HTTPException(status_code=400, detail="Checkout amount/currency does not match the recorded intent")
        if str(obj.get("client_reference_id") or "") != intent.user_id:
            raise HTTPException(status_code=400, detail="Checkout user does not match the recorded intent")
        if intent.status not in {"paid", "cancelled"}:
            intent.status = "paid"
            intent.paid_at = now
            subscription_id = obj.get("subscription")
            if subscription_id:
                intent.stripe_subscription_id = str(subscription_id)
            if intent.purpose == "marketplace":
                earning = session.execute(
                    select(CreatorEarning).where(CreatorEarning.checkout_intent_id == intent.id)
                ).scalar_one_or_none()
                if earning is None:
                    session.add(CreatorEarning(
                        checkout_intent_id=intent.id,
                        creator_user_id=intent.creator_user_id or "",
                        amount_usd_cents=intent.creator_share_cents,
                        platform_fee_usd_cents=intent.platform_share_cents,
                        status="pending_payout",
                    ))
                _audit(session, "stripe-webhook", "marketplace.sale.paid", intent.id,
                       {"creator_share_cents": intent.creator_share_cents,
                        "platform_share_cents": intent.platform_share_cents})
        session.add(ProcessedWebhook(event_id=event_id, event_type=event_type))
    elif event_type == "invoice.paid":
        parent = obj.get("parent") or {}
        subscription_details = parent.get("subscription_details") or {}
        subscription_id = obj.get("subscription") or subscription_details.get("subscription")
        metadata = subscription_details.get("metadata") or {}
        intent_id = metadata.get("intent_id")
        intents = []
        if intent_id:
            row = session.get(CheckoutIntent, str(intent_id))
            if row:
                intents = [row]
        if not intents and subscription_id:
            intents = session.execute(
                select(CheckoutIntent).where(CheckoutIntent.stripe_subscription_id == str(subscription_id))
            ).scalars().all()
        for intent in intents:
            intent.status = "paid"
            intent.paid_at = now
            # Restore entitlements after a successful renewal. A fresh signed license
            # token can be retrieved using /v1/billing/license/{intent_id}; previous
            # tokens still retain their originally signed expiry.
            period_end = None
            lines = (obj.get("lines") or {}).get("data") or []
            if lines:
                end_ts = (lines[0].get("period") or {}).get("end")
                if isinstance(end_ts, (int, float)):
                    period_end = datetime.fromtimestamp(end_ts, timezone.utc)
            expiry = period_end or (now + timedelta(days=30))
            for license_record in session.execute(
                select(LicenseRecord).where(LicenseRecord.checkout_intent_id == intent.id)
            ).scalars().all():
                license_record.status = "active"
                license_record.expires_at = expiry
        session.add(ProcessedWebhook(event_id=event_id, event_type=event_type))
    elif event_type == "customer.subscription.deleted":
        subscription_id = str(obj.get("id", ""))
        intents = session.execute(
            select(CheckoutIntent).where(CheckoutIntent.stripe_subscription_id == subscription_id)
        ).scalars().all()
        for intent in intents:
            intent.status = "cancelled"
            for license_record in session.execute(
                select(LicenseRecord).where(LicenseRecord.checkout_intent_id == intent.id)
            ).scalars().all():
                license_record.status = "revoked"
        session.add(ProcessedWebhook(event_id=event_id, event_type=event_type))
    elif event_type == "invoice.payment_failed":
        parent = obj.get("parent") or {}
        subscription_details = parent.get("subscription_details") or {}
        subscription_id = obj.get("subscription") or subscription_details.get("subscription")
        if subscription_id:
            intents = session.execute(
                select(CheckoutIntent).where(CheckoutIntent.stripe_subscription_id == str(subscription_id))
            ).scalars().all()
            for intent in intents:
                if intent.status != "cancelled":
                    intent.status = "past_due"
                for license_record in session.execute(
                    select(LicenseRecord).where(LicenseRecord.checkout_intent_id == intent.id)
                ).scalars().all():
                    license_record.status = "suspended"
        session.add(ProcessedWebhook(event_id=event_id, event_type=event_type))
    else:
        # Record authenticated, non-payment events so Stripe does not retry them forever.
        session.add(ProcessedWebhook(event_id=event_id, event_type=event_type))
    session.commit()
    return {"received": True, "event_type": event_type}


class PublishToolInput(BaseModel):
    tool_id: str = Field(pattern="^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=2, max_length=140)
    description: str = Field(min_length=10, max_length=3000)
    industry: str = Field(default="general", min_length=2, max_length=80)
    country_origin: str = Field(default="KE", min_length=2, max_length=2)
    endpoint: str = Field(pattern="^/v1/[a-z0-9][a-z0-9_-]{0,63}$", max_length=120)
    factory_build_id: str | None = Field(default=None, pattern="^fab_[a-f0-9]{24}$")
    price_usd_cents: int = Field(ge=100, le=100000000)
    bom_by_country: dict[str, Any] = Field(default_factory=dict)
    guides_by_language: dict[str, Any] = Field(default_factory=dict)


@app.post("/v1/marketplace/publish", status_code=202, tags=["marketplace"])
def publish_tool(body: PublishToolInput,
                 license_key: str | None = Header(default=None, alias="X-Revela-License"),
                 user_id: str = Depends(authenticated_user),
                 session: Session = Depends(get_db)) -> dict[str, Any]:
    country = _country(body.country_origin)
    claims, license_record = _active_license(session, license_key or "", user_id, country=country)
    try:
        enforce_tool_creation_quota(session, license_record)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    if session.get(ToolRecord, body.tool_id):
        raise HTTPException(status_code=409, detail="tool_id already exists")
    factory_build = None
    if body.factory_build_id:
        factory_build = session.get(FactoryRecord, body.factory_build_id)
        if factory_build is None or factory_build.owner_user_id != user_id:
            raise HTTPException(status_code=404, detail="Owned factory build not found")
        if factory_build.status != "approved":
            raise HTTPException(status_code=409, detail="Factory build must be approved before marketplace listing")
    allowed, note = safety_screen(body.name, body.description, body.endpoint)
    status = "pending_review" if allowed else "rejected"
    tool = ToolRecord(
        id=body.tool_id, creator_user_id=user_id, name=body.name.strip(),
        description=body.description.strip(), industry=body.industry.strip().lower(),
        country_origin=country, endpoint=body.endpoint, price_usd_cents=body.price_usd_cents,
        factory_build_id=body.factory_build_id,
        status=status, bom_by_country={str(k).upper(): v for k, v in body.bom_by_country.items()},
        guides_by_language={str(k).lower(): v for k, v in body.guides_by_language.items()},
        # Publisher-supplied savings are not trusted; reviewer may set a verified estimate later.
        verified_cost_saved_usd=0.0,
    )
    watermark = None
    if allowed:
        artifact_payload = {
            "tool_id": body.tool_id,
            "name": body.name.strip(),
            "description": body.description.strip(),
            "endpoint": body.endpoint,
            "factory_build_id": body.factory_build_id,
            "price_usd_cents": body.price_usd_cents,
        }
        artifact_digest = hashlib.sha256(
            json.dumps(artifact_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            watermark = sign_tool_watermark(
                tool_id=body.tool_id,
                creator_user_id=user_id,
                factory_id=body.factory_build_id or body.tool_id,
                artifact_sha256=artifact_digest,
            )
        except DnaVaultError as exc:
            raise HTTPException(status_code=503, detail="Founder watermark signing is unavailable; listing was not saved.") from exc
    session.add(tool)
    _audit(session, user_id, "marketplace.tool.submitted", tool.id,
           {"status": status, "safety_note": note, "license_id": claims["jti"],
            "watermark_valid": bool(watermark)})
    session.commit()
    if not allowed:
        raise HTTPException(status_code=403, detail=note)
    return {"tool_id": tool.id, "status": status, "safety_note": note,
            "provenance_watermark": watermark,
            "next_step": "A configured reviewer must approve this listing before it becomes searchable or callable."}


class ReviewToolInput(BaseModel):
    approved: bool
    review_note: str = Field(min_length=3, max_length=1200)
    verified_cost_saved_usd: float | None = Field(default=None, ge=0, le=10000000)


@app.post("/v1/marketplace/{tool_id}/review", tags=["marketplace"])
def review_tool(tool_id: str, body: ReviewToolInput,
                user_id: str = Depends(authenticated_user),
                session: Session = Depends(get_db)) -> dict[str, Any]:
    if not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Marketplace reviewer permission required")
    provenance = verify_tool_watermark(tool_id)
    if not provenance.get("valid"):
        raise HTTPException(status_code=409, detail="Tool has no valid founder-signed RevelaCode provenance watermark")
    tool = session.get(ToolRecord, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool listing not found")
    allowed, note = safety_screen(tool.name, tool.description, tool.endpoint)
    if body.approved and not allowed:
        tool.status = "rejected"
        _audit(session, user_id, "marketplace.tool.review_blocked", tool_id, {"reason": note})
        session.commit()
        raise HTTPException(status_code=403, detail=note)
    tool.status = "published" if body.approved else "rejected"
    if body.approved and body.verified_cost_saved_usd is not None:
        tool.verified_cost_saved_usd = body.verified_cost_saved_usd
    _audit(session, user_id, "marketplace.tool.reviewed", tool_id,
           {"approved": body.approved, "review_note": body.review_note,
            "verified_cost_saved_usd": tool.verified_cost_saved_usd})
    session.commit()
    return {"tool_id": tool.id, "status": tool.status, "reviewer": user_id}


@app.get("/v1/marketplace/search", tags=["marketplace"])
def search_marketplace(country: str = "KE", industry: str | None = None,
                       q: str | None = None, lang: str | None = None,
                       user_id: str = Depends(authenticated_user),
                       session: Session = Depends(get_db)) -> dict[str, Any]:
    target_country = _country(country)
    query = select(ToolRecord).where(ToolRecord.status == "published")
    if industry and industry.strip() and industry.lower() != "all":
        query = query.where(ToolRecord.industry == industry.strip().lower())
    tools = session.execute(query.order_by(ToolRecord.created_at.desc()).limit(250)).scalars().all()
    if q:
        needle = q.casefold().strip()
        tools = [tool for tool in tools if needle in tool.name.casefold()
                 or needle in tool.description.casefold() or needle in tool.industry.casefold()]
    return {"country": target_country, "count": len(tools),
            "tools": [country_bundle(tool, target_country, lang) for tool in tools]}


class BuyToolInput(BaseModel):
    tool_id: str = Field(pattern="^[a-z0-9][a-z0-9_-]{0,63}$")
    license_key: str = Field(min_length=20, max_length=12000)
    buyer_country: str = Field(default="KE", min_length=2, max_length=2)


@app.post("/v1/marketplace/buy", status_code=202, tags=["marketplace"])
async def buy_tool(body: BuyToolInput, user_id: str = Depends(authenticated_user),
                   session: Session = Depends(get_db)) -> dict[str, Any]:
    country = _country(body.buyer_country)
    _active_license(session, body.license_key, user_id, country=country, tool_id=body.tool_id)
    tool = session.get(ToolRecord, body.tool_id)
    if tool is None or tool.status != "published":
        raise HTTPException(status_code=404, detail="Published marketplace tool not found")
    if tool.creator_user_id == user_id:
        raise HTTPException(status_code=409, detail="Creators cannot buy their own listing")
    intent_id = str(uuid4())
    creator_share = (tool.price_usd_cents * 70) // 100
    platform_share = tool.price_usd_cents - creator_share
    intent = CheckoutIntent(
        id=intent_id, user_id=user_id, purpose="marketplace", country=country,
        tool_id=tool.id, creator_user_id=tool.creator_user_id,
        amount_usd_cents=tool.price_usd_cents, creator_share_cents=creator_share,
        platform_share_cents=platform_share, status="checkout_pending",
    )
    session.add(intent)
    session.commit()
    try:
        checkout = await create_stripe_checkout(
            intent_id=intent_id, user_id=user_id, purpose="marketplace",
            amount_cents=tool.price_usd_cents, name=f"RevelaCode Tool: {tool.name}",
            country=country, metadata={"tool_id": tool.id, "creator_user_id": tool.creator_user_id},
            subscription=False,
        )
    except (PaymentConfigurationError, PaymentProviderError, ValueError) as exc:
        intent.status = "checkout_failed"
        session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    intent.stripe_session_id = checkout["session_id"]
    session.commit()
    return {
        "purchase_id": intent.id, "checkout_url": checkout["checkout_url"],
        "status": "pending_payment", "tool_id": tool.id, "buyer_country": country,
        "creator_share_usd": creator_share / 100, "platform_share_usd": platform_share / 100,
        "delivery": "Endpoint, country BOM and hardware guide become available after the signed payment webhook confirms payment.",
    }


@app.get("/v1/marketplace/purchases/{purchase_id}", tags=["marketplace"])
def marketplace_purchase(purchase_id: str, user_id: str = Depends(authenticated_user),
                         session: Session = Depends(get_db)) -> dict[str, Any]:
    intent = session.get(CheckoutIntent, purchase_id)
    if intent is None or intent.purpose != "marketplace":
        raise HTTPException(status_code=404, detail="Marketplace purchase not found")
    if intent.user_id != user_id:
        raise HTTPException(status_code=403, detail="Purchase belongs to another user")
    if intent.status != "paid":
        raise HTTPException(status_code=409, detail="Payment is not confirmed")
    tool = session.get(ToolRecord, intent.tool_id or "")
    if tool is None or tool.status != "published":
        raise HTTPException(status_code=404, detail="Published tool is no longer available")
    return {"purchase_id": intent.id, "status": intent.status,
            "delivery": country_bundle(tool, intent.country),
            "creator_share_usd": intent.creator_share_cents / 100,
            "platform_share_usd": intent.platform_share_cents / 100}


class RatingInput(BaseModel):
    rating: int = Field(ge=1, le=5)


@app.post("/v1/marketplace/{tool_id}/rating", tags=["marketplace"])
def rate_tool(tool_id: str, body: RatingInput, user_id: str = Depends(authenticated_user),
              session: Session = Depends(get_db)) -> dict[str, Any]:
    tool = session.get(ToolRecord, tool_id)
    if tool is None or tool.status != "published":
        raise HTTPException(status_code=404, detail="Published tool not found")
    if tool.creator_user_id == user_id:
        raise HTTPException(status_code=403, detail="Creators cannot rate their own tool")
    rating = session.execute(
        select(ToolRating).where(ToolRating.tool_id == tool_id, ToolRating.user_id == user_id)
    ).scalar_one_or_none()
    is_new_rating = rating is None
    if rating is None:
        rating = ToolRating(tool_id=tool_id, user_id=user_id, rating=body.rating)
        session.add(rating)
    else:
        tool.rating_total -= rating.rating
        rating.rating = body.rating
    tool.rating_total += body.rating
    if is_new_rating:
        tool.rating_count += 1
    _audit(session, user_id, "marketplace.tool.rated", tool_id, {"rating": body.rating})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Rating already submitted concurrently; retry") from exc
    return {"tool_id": tool_id, "rating": body.rating,
            "average_rating": round(tool.rating_total / tool.rating_count, 2) if tool.rating_count else None,
            "rating_count": tool.rating_count}


@app.get("/v1/marketplace/earnings/me", tags=["marketplace"])
def my_earnings(user_id: str = Depends(authenticated_user),
                session: Session = Depends(get_db)) -> dict[str, Any]:
    return creator_earnings(session, user_id)


@app.get("/v1/meter/usage", tags=["meter"])
def meter_usage(user_id: str | None = None, country: str | None = None,
                authenticated_id: str = Depends(authenticated_user),
                session: Session = Depends(get_db)) -> dict[str, Any]:
    requested = user_id or authenticated_id
    if requested != authenticated_id and not _reviewer(authenticated_id):
        raise HTTPException(status_code=403, detail="You may only view your own usage")
    summary = usage_summary(session, requested)
    if country:
        target = _country(country)
        summary["selected_country"] = target
        summary["selected_country_usage"] = summary["cost_saved_per_country"].get(
            target, {"calls": 0, "cost_saved_usd": 0.0}
        )
    return summary


@app.get("/v1/meter/health", tags=["meter"])
def meter_health() -> dict[str, Any]:
    return {"ok": True, "storage": "sqlalchemy", "privacy": "no request bodies or client IPs are stored"}



# =========================================================
# FACTORY FOUNDRY, OFFLINE SEED, AND AUDITOR
# =========================================================

class FactoryBuildInput(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    description: str = Field(min_length=10, max_length=3000)
    requirements: list[str] = Field(min_length=1, max_length=50)
    country: str = Field(default="KE", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=5)
    industry: str = Field(default="general", min_length=2, max_length=80)
    adapters: list[str] = Field(default_factory=list, max_length=25)


@app.post("/v1/foundry/build", status_code=202, tags=["foundry"])
def build_factory(body: FactoryBuildInput,
                  license_key: str | None = Header(default=None, alias="X-Revela-License"),
                  user_id: str = Depends(authenticated_user),
                  session: Session = Depends(get_db)) -> dict[str, Any]:
    country = _country(body.country)
    claims, license_record = _active_license(session, license_key or "", user_id, country=country)
    try:
        require_enterprise_claims(claims, "factory_build")
        enforce_tool_creation_quota(session, license_record)
        proposal = FoundryBuilder().build_plan(
            owner_user_id=user_id, name=body.name, description=body.description,
            requirements=body.requirements, country=country, language=body.language,
            industry=body.industry, adapters=body.adapters,
        )
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except FactoryBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        watermark = sign_tool_watermark(
            tool_id=proposal["build_id"],
            creator_user_id=user_id,
            factory_id=proposal["build_id"],
            artifact_sha256=proposal["manifest_sha256"],
        )
    except DnaVaultError as exc:
        raise HTTPException(status_code=503, detail="Founder watermark signing is unavailable; factory build was not committed.") from exc
    record = FactoryRecord(
        id=proposal["build_id"], owner_user_id=user_id, name=body.name.strip(),
        status="await_merge", country=country, manifest_sha256=proposal["manifest_sha256"],
        manifest_json=proposal["manifest"],
    )
    session.add(record)
    _audit(session, user_id, "foundry.factory.built", record.id,
           {"manifest_sha256": proposal["manifest_sha256"], "license_id": claims["jti"]})
    session.commit()
    chain_logged = True
    try:
        AuditLedger().append(
            actor_user_id=user_id, action="foundry.factory.built", object_id=record.id,
            detail={"manifest_sha256": proposal["manifest_sha256"], "license_id": claims["jti"]},
        )
    except AuditLedgerError:
        chain_logged = False
    return {
        "build_id": proposal["build_id"],
        "status": proposal["status"],
        "manifest_sha256": proposal["manifest_sha256"],
        "provenance_watermark": watermark,
        "manifest": proposal["manifest"],
        "audit_chain_recorded": chain_logged,
        "execution": "disabled_until_review",
    }


@app.get("/v1/foundry/builds/{build_id}", tags=["foundry"])
def get_factory_build(build_id: str, user_id: str = Depends(authenticated_user),
                      session: Session = Depends(get_db)) -> dict[str, Any]:
    record = session.get(FactoryRecord, build_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Factory build not found")
    if record.owner_user_id != user_id and not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Factory belongs to another user")
    try:
        manifest = FoundryBuilder.validate_manifest(record.manifest_json)
        if manifest["manifest_sha256"] != record.manifest_sha256:
            raise FactoryBuildError("Database manifest digest does not match factory record.")
    except FactoryBuildError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"build_id": build_id, "database_status": record.status, "manifest": manifest}


class FactoryReviewInput(BaseModel):
    approved: bool
    review_note: str = Field(min_length=3, max_length=1200)


@app.post("/v1/foundry/builds/{build_id}/review", tags=["foundry"])
def review_factory_build(build_id: str, body: FactoryReviewInput,
                         user_id: str = Depends(authenticated_user),
                         session: Session = Depends(get_db)) -> dict[str, Any]:
    if not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Foundry reviewer permission required")
    record = session.get(FactoryRecord, build_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Factory build not found")
    target_status = "approved" if body.approved else "rejected"
    try:
        manifest = FoundryBuilder.transition_manifest(record.manifest_json, target_status)
        if body.approved:
            try:
                manifest = sign_approved_manifest(manifest, reviewer_id=user_id)
            except AttestationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Factory review signing is not configured; approval was not recorded.",
                ) from exc
        # SQL is the hosted source of truth. A local manifest cache is best-effort.
        try:
            FoundryBuilder().store_manifest(manifest)
        except (OSError, FactoryBuildError):
            pass
    except FactoryBuildError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record.status = target_status
    record.manifest_sha256 = manifest["manifest_sha256"]
    record.manifest_json = manifest
    _audit(session, user_id, "foundry.factory.reviewed", build_id,
           {"approved": body.approved, "review_note": body.review_note,
            "manifest_sha256": record.manifest_sha256})
    session.commit()
    chain_logged = True
    try:
        AuditLedger().append(
            actor_user_id=user_id, action="foundry.factory.reviewed", object_id=build_id,
            detail={"approved": body.approved, "manifest_sha256": record.manifest_sha256},
        )
    except AuditLedgerError:
        chain_logged = False
    return {"build_id": build_id, "status": target_status,
            "manifest_sha256": record.manifest_sha256, "audit_chain_recorded": chain_logged}


class SeedFactoryInput(BaseModel):
    child_name: str = Field(min_length=2, max_length=100)
    buyer_country: str = Field(default="KE", min_length=2, max_length=2)
    purchase_id: str | None = Field(default=None, max_length=64)


@app.post("/v1/seed/{build_id}", status_code=201, tags=["seed"])
def seed_factory(build_id: str, body: SeedFactoryInput,
                 license_key: str | None = Header(default=None, alias="X-Revela-License"),
                 user_id: str = Depends(authenticated_user),
                 session: Session = Depends(get_db)) -> dict[str, Any]:
    country = _country(body.buyer_country)
    claims, license_record = _active_license(
        session, license_key or "", user_id, country=country
    )
    try:
        require_enterprise_claims(claims, "seed_create")
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    record = session.get(FactoryRecord, build_id)
    if record is None or record.status != "approved":
        raise HTTPException(status_code=409, detail="Factory must be approved by a human reviewer before seeding")
    purchased = False
    if record.owner_user_id != user_id:
        if not body.purchase_id:
            raise HTTPException(status_code=403, detail="Factory owner or paid marketplace purchase required")
        intent = session.get(CheckoutIntent, body.purchase_id)
        if (intent is None or intent.user_id != user_id or intent.purpose != "marketplace"
                or intent.status != "paid"):
            raise HTTPException(status_code=403, detail="Marketplace purchase is not verified")
        purchased_tool = session.get(ToolRecord, intent.tool_id or "")
        if (purchased_tool is None or purchased_tool.status != "published"
                or purchased_tool.factory_build_id != build_id):
            raise HTTPException(status_code=403, detail="Purchase is not linked to this factory build")
        purchased = True
    try:
        enforce_tool_creation_quota(session, license_record)
        result = SeedRunner().seed_child(
            build_id=build_id, license_key=license_key or "", user_id=user_id,
            child_name=body.child_name, purchase_verified=purchased,
            source_manifest=record.manifest_json,
        )
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except SeedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Return the actual signed, offline-verifiable child bundle to its owner.
    # Do not make a server-local file path the only copy of the deliverable.
    bundle_path = Path(result.pop("path"))
    try:
        child_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Seed bundle could not be serialized for delivery") from exc
    finally:
        try:
            bundle_path.unlink(missing_ok=True)
            bundle_path.parent.rmdir()
        except OSError:
            pass
    result["child_bundle"] = child_bundle

    seed_row = SeedRecord(
        id=result["seed_id"], parent_build_id=build_id, owner_user_id=user_id,
        license_id=str(claims["jti"]), status=result["status"],
        offline_until=int(result["offline_until"]),
    )
    session.add(seed_row)
    _audit(session, user_id, "seed.child.created", result["seed_id"],
           {"parent_build_id": build_id, "license_id": claims["jti"],
            "offline_until": result["offline_until"], "marketplace_purchase_verified": purchased})
    session.commit()
    try:
        AuditLedger().append(
            actor_user_id=user_id, action="seed.child.created", object_id=result["seed_id"],
            detail={"parent_build_id": build_id, "license_id": claims["jti"],
                    "marketplace_purchase_verified": purchased},
        )
        result["audit_chain_recorded"] = True
    except AuditLedgerError:
        result["audit_chain_recorded"] = False
    return result


@app.get("/v1/seed/{seed_id}/verify", tags=["seed"])
def verify_seed(seed_id: str, user_id: str = Depends(authenticated_user),
                session: Session = Depends(get_db)) -> dict[str, Any]:
    record = session.get(SeedRecord, seed_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Seeded child not found")
    if record.owner_user_id != user_id and not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Seeded child belongs to another user")
    license_record = session.get(LicenseRecord, record.license_id)
    now = int(datetime.now(timezone.utc).timestamp())
    registry_active = bool(
        license_record is not None
        and license_record.user_id == record.owner_user_id
        and license_record.status == "active"
        and (license_record.expires_at.replace(tzinfo=timezone.utc)
             if license_record.expires_at.tzinfo is None else license_record.expires_at)
             > datetime.now(timezone.utc)
    )
    offline_in_window = now <= record.offline_until
    return {
        "seed_id": record.id, "status": record.status, "license_id": record.license_id,
        "offline_until": record.offline_until,
        "offline_window_open": offline_in_window,
        "server_license_active": registry_active,
        "offline_authorized": offline_in_window and record.status == "seeded_review_required",
        "note": "This endpoint checks server-side lease and revocation state. The delivered child bundle must be saved locally and verified offline with python -m core_seed.cli --seed-id <seed_id>.",
    }


@app.get("/v1/auditor/verify", tags=["auditor"])
def verify_audit_ledger(user_id: str = Depends(authenticated_user)) -> dict[str, Any]:
    if not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Auditor verification requires reviewer permission")
    try:
        return AuditLedger().verify()
    except AuditLedgerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/auditor/events", tags=["auditor"])
def list_audit_events(limit: int = Query(default=50, ge=1, le=250),
                      offset: int = Query(default=0, ge=0, le=100000),
                      actor_user_id: str | None = None,
                      user_id: str = Depends(authenticated_user),
                      session: Session = Depends(get_db)) -> dict[str, Any]:
    requested_actor = actor_user_id or user_id
    if requested_actor != user_id and not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="You may only read your own audit events")
    query = select(AuditRecord).where(AuditRecord.actor_user_id == requested_actor)
    total = session.scalar(select(func.count()).select_from(AuditRecord).where(
        AuditRecord.actor_user_id == requested_actor
    )) or 0
    rows = session.execute(
        query.order_by(AuditRecord.id.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return {
        "actor_user_id": requested_actor,
        "total": int(total),
        "events": [{
            "id": item.id, "action": item.action, "object_id": item.object_id,
            "detail": item.detail, "created_at": _to_iso(item.created_at),
        } for item in rows],
    }


# Tool licensing guard for registered tool routes and unknown single-segment /v1 paths.
# Only explicitly registered static FastAPI endpoints bypass the marketplace-tool gate.
def _legacy_static_route_exists(path: str, method: str) -> bool:
    for route in app.router.routes:
        route_path = getattr(route, "path", "")
        if route_path != path or "{" in route_path or "}" in route_path:
            continue
        methods = set(getattr(route, "methods", set()) or set())
        if method.upper() in methods:
            return True
    return False


def _record_usage_safely(*, user_id: str, tool_id: str, country: str,
                         latency_ms: float, success: bool, cost_saved_usd: float = 0.0) -> None:
    import logging
    try:
        with SessionLocal() as meter_session:
            record_usage(
                meter_session, user_id=user_id, tool_id=tool_id, country=country,
                latency_ms=latency_ms, success=success,
                cost_saved_usd=cost_saved_usd,
            )
    except Exception:
        logging.getLogger(__name__).exception("usage event could not be persisted")


@app.middleware("http")
async def licensed_tool_guard(request: Request, call_next):
    path = request.url.path
    parts = path.strip("/").split("/")
    tool_id = parts[1] if len(parts) == 2 and parts[0] == "v1" else None
    method = request.method.upper()
    if not tool_id or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return await call_next(request)

    try:
        with SessionLocal() as lookup:
            candidate = lookup.get(ToolRecord, tool_id)
            if candidate is not None and candidate.status != "published":
                return JSONResponse(
                    status_code=404,
                    content={"error": "Tool is not published or available."},
                )
            tracked_tool = candidate if candidate is not None else None
    except Exception:
        # Registry uncertainty is not permission to execute tool-like endpoints.
        return JSONResponse(status_code=503, content={"error": "License registry unavailable; tool calls fail closed."})

    if tracked_tool is None:
        if _legacy_static_route_exists(path, method):
            return await call_next(request)
        return JSONResponse(
            status_code=404,
            content={"error": "Tool route is not registered or published in RevelaCode."},
        )

    try:
        identity = str(_claims_from_bearer(request.headers.get("Authorization"))["sub"])
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    try:
        country = _country(request.headers.get("X-Country") or request.query_params.get("country", "KE"))
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    started = time.perf_counter()
    denial: JSONResponse | None = None
    try:
        with SessionLocal() as guard_session:
            try:
                _active_license(
                    guard_session, request.headers.get("X-Revela-License", ""),
                    identity, country=country, tool_id=tool_id,
                )
            except HTTPException as exc:
                denial = JSONResponse(
                    status_code=exc.status_code, content={"error": str(exc.detail)}
                )
            if denial is None and tracked_tool.creator_user_id != identity:
                paid = guard_session.execute(
                    select(CheckoutIntent.id).where(
                        CheckoutIntent.user_id == identity,
                        CheckoutIntent.purpose == "marketplace",
                        CheckoutIntent.tool_id == tool_id,
                        CheckoutIntent.status == "paid",
                    ).limit(1)
                ).first()
                if not paid:
                    denial = JSONResponse(
                        status_code=402,
                        content={
                            "error": "A paid marketplace purchase is required for this tool.",
                            "endpoint": "/v1/marketplace/buy",
                        },
                    )
    except Exception:
        return JSONResponse(status_code=503, content={"error": "License registry unavailable; tool calls fail closed."})

    if denial is not None:
        _record_usage_safely(
            user_id=identity, tool_id=tool_id, country=country,
            latency_ms=(time.perf_counter() - started) * 1000, success=False,
        )
        return denial

    response = await call_next(request)
    _record_usage_safely(
        user_id=identity, tool_id=tool_id, country=country,
        latency_ms=(time.perf_counter() - started) * 1000,
        success=response.status_code < 400,
        cost_saved_usd=tracked_tool.verified_cost_saved_usd,
    )
    return response




# =========================================================
# CANONICAL USECT CORE SURFACE
# =========================================================
# These endpoints route through the existing signed licensing, billing,
# audit and core-service boundaries. They return proposals, not auto-deployments.

class ZeroHealInput(BaseModel):
    tool_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    error: str = Field(min_length=1, max_length=3000)


class GenesisDemandInput(BaseModel):
    demand: str = Field(min_length=1, max_length=3999)
    country: str = Field(default="KE", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=5)


class ImproveToolInput(BaseModel):
    objective: str = Field(min_length=8, max_length=500)


class OrchestratorRunInput(BaseModel):
    demand: str = Field(min_length=8, max_length=3999)
    tool_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    error: str = Field(min_length=1, max_length=3000)
    objective: str = Field(
        default="Assess a safe, evidence-backed improvement while preserving existing safeguards.",
        min_length=8, max_length=500,
    )
    country: str = Field(default="KE", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=5)


class TwinScanInput(BaseModel):
    min_similarity: float = Field(default=0.80, ge=0.50, le=1.0)
    max_candidates: int = Field(default=50, ge=1, le=100)


class EvolutionStartInput(BaseModel):
    factory_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    objective: str = Field(min_length=8, max_length=2000)
    metrics: list[MetricTarget] = Field(min_length=1, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    requested_depth: int = Field(default=1, ge=1, le=3)
    twin_baseline: dict[str, float] = Field(default_factory=dict, max_length=20)


class InspectorProduceInput(BaseModel):
    demand: str = Field(min_length=8, max_length=3000)
    country: str = Field(default="KE", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=5)
    requirements: list[str] = Field(default_factory=list, max_length=50)
    resources_available: dict[str, int | float | str | bool] = Field(default_factory=dict, max_length=50)
    simulate_human_usage: bool = True


class ComplianceReportInput(BaseModel):
    report_kind: str = Field(pattern=r"^(CE|UL|ISO9001|ROHS|FCC)$")
    country: str = Field(default="KE", min_length=2, max_length=2)
    scope: str = Field(min_length=8, max_length=3000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=25)
    checks: list[str] = Field(default_factory=list, max_length=40)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=40)


def _persist_usect_event(actor: str, action: str, object_id: str,
                          detail: dict[str, Any] | None = None) -> bool:
    """Write a minimal operation record; never accept raw prompts, tokens or errors."""
    safe_detail = detail or {}
    try:
        with SessionLocal() as session:
            _audit(session, actor, action, object_id, safe_detail)
            session.commit()
    except Exception:
        # If SQL audit is unavailable the caller still receives its operation result;
        # the hash-chain result is separately reported where required.
        pass
    try:
        AuditLedger().append(
            actor_user_id=actor, action=action, object_id=object_id,
            detail=safe_detail,
        )
        return True
    except AuditLedgerError:
        return False


def _require_owned_factory_or_tool(resource_id: str, user_id: str) -> tuple[str, str]:
    with SessionLocal() as session:
        factory = session.get(FactoryRecord, resource_id)
        tool = session.get(ToolRecord, resource_id)
        record = factory or tool
        if record is None:
            raise HTTPException(status_code=404, detail="The target factory/tool was not found in the RevelaCode registry.")
        owner = record.owner_user_id if factory else record.creator_user_id
        if owner != user_id and not _reviewer(user_id):
            raise HTTPException(status_code=403, detail="Only the target owner or an approved reviewer may request this improvement.")
        label = record.name
        return owner, label


@app.post("/v1/zero/heal", status_code=202, tags=["usect-zero"])
def usect_zero_heal(
    body: ZeroHealInput,
    request: Request,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    """Ask Core Zero to propose repository recovery for a reported tool failure.

    The current Go core produces a repository-level recovery proposal. It cannot
    prove or claim that the supplied tool_id was repaired by this request.
    """
    claims, _license_record = _active_license(session, license_key or "", user_id)
    try:
        _target_owner, target_name = _require_owned_factory_or_tool(body.tool_id, user_id)
    except HTTPException:
        raise
    error_digest = hashlib.sha256(body.error.encode("utf-8")).hexdigest()
    proposal = execute_usect_zero_tool("heal", {})
    status = str(proposal.get("status") or "unknown")
    audit_recorded = _persist_usect_event(
        user_id, "usect.zero.heal_proposed", body.tool_id,
        {"error_sha256": error_digest, "error_length": len(body.error),
         "target_name": target_name[:120],
         "license_id": str(claims.get("jti") or ""), "proposal_status": status},
    )
    return {
        "status": "proposal_created" if status == "success" else "unavailable",
        "core": "USECT-ZERO",
        "tool_id": body.tool_id,
        "reported_error_sha256": error_digest,
        "recovery_proposal": proposal,
        "tool_repaired": False,
        "automatic_repair": False,
        "human_approval_required": True,
        "audit_chain_recorded": audit_recorded,
        "note": "The current Core Zero integration creates a bounded repository recovery proposal; the supplied tool_id is audit context, not proof that this individual tool was fixed.",
    }


@app.post("/v1/one/genesis", status_code=202, tags=["usect-one"])
def usect_one_genesis(
    body: GenesisDemandInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    """Queue a free-text tool demand in Genesis; no code is deployed by this endpoint."""
    claims, license_record = _active_license(session, license_key or "", user_id, country=_country(body.country))
    try:
        enforce_tool_creation_quota(session, license_record)
        queued = queue_genesis_demand(
            body.demand, source="revelacode-usect-api",
            country=_country(body.country), language=body.language,
        )
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except CoreMeshError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    demand_sha256 = hashlib.sha256(body.demand.encode("utf-8")).hexdigest()
    audit_recorded = _persist_usect_event(
        user_id, "usect.one.genesis_queued", str(queued.get("id") or queued.get("queue_id") or "queued"),
        {"demand_sha256": demand_sha256, "country": _country(body.country),
         "language": body.language, "license_id": str(claims.get("jti") or "")},
    )
    return {
        "core": "USECT-ONE",
        "status": str(queued.get("status") or "queued"),
        "demand_sha256": demand_sha256,
        "queue_result": queued,
        "artifact_created": False,
        "human_review_required": True,
        "automatic_execution": False,
        "audit_chain_recorded": audit_recorded,
    }


@app.post("/v1/two/improve/{tool_id}", status_code=202, tags=["usect-two"])
def usect_two_improve(
    tool_id: str,
    body: ImproveToolInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    """Ask Infinite Mind for an evidence-backed improvement proposal for an owned target."""
    claims, _license = _active_license(session, license_key or "", user_id)
    try:
        require_enterprise_claims(claims, "evolve")
        _owner, target_name = _require_owned_factory_or_tool(tool_id, user_id)
        result = propose_mind_evolution(body.objective, tool_id)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except CoreMeshError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except HTTPException:
        raise
    audit_recorded = _persist_usect_event(
        user_id, "usect.two.improvement_proposed", tool_id,
        {"target_name": target_name[:120], "license_id": str(claims.get("jti") or ""),
         "proposal_only": True},
    )
    return {
        "core": "USECT-TWO",
        "tool_id": tool_id,
        "status": str(result.get("status") or "proposal_created"),
        "improvement": result,
        "performance_multiplier_claimed": None,
        "target_modified": False,
        "automatic_execution": False,
        "human_review_required": True,
        "audit_chain_recorded": audit_recorded,
    }


@app.post("/v1/orchestrator/run", status_code=202, tags=["usect-orchestrator"])
def usect_orchestrator_run(
    body: OrchestratorRunInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    """Run the Zero → One → Two proposal pipeline in order, continuing with explicit per-step failures."""
    claims, license_record = _active_license(session, license_key or "", user_id, country=_country(body.country))
    try:
        require_enterprise_claims(claims, "evolve")
        enforce_tool_creation_quota(session, license_record)
        _require_owned_factory_or_tool(body.tool_id, user_id)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc

    steps: list[dict[str, Any]] = []
    # ZERO: collect actual diagnostics first, then propose recovery for the failure described.
    diagnostic = execute_usect_zero_tool("diagnostics", {})
    steps.append({"core": "USECT-ZERO", "operation": "diagnostics",
                  "status": diagnostic.get("status", "unknown"), "result": diagnostic})
    error_sha256 = hashlib.sha256(body.error.encode("utf-8")).hexdigest()
    recovery = execute_usect_zero_tool("heal", {}) if body.error.strip() else {
        "status": "skipped", "message": "No tool failure was supplied."
    }
    steps.append({"core": "USECT-ZERO", "operation": "recovery_proposal",
                  "status": recovery.get("status", "unknown"), "result": recovery,
                  "tool_id": body.tool_id, "reported_error_sha256": error_sha256,
                  "automatic_repair": False})

    # ONE: queue the free-text demand. This does not mean a tool was born yet.
    demand_sha256 = hashlib.sha256(body.demand.encode("utf-8")).hexdigest()
    try:
        genesis = queue_genesis_demand(
            body.demand, source="revelacode-usect-orchestrator",
            country=_country(body.country), language=body.language,
        )
        steps.append({"core": "USECT-ONE", "operation": "genesis_queue",
                      "status": genesis.get("status", "queued"), "result": genesis,
                      "demand_sha256": demand_sha256, "artifact_created": False})
    except CoreMeshError as exc:
        steps.append({"core": "USECT-ONE", "operation": "genesis_queue",
                      "status": "unavailable", "error_code": exc.code,
                      "message": str(exc)[:300]})

    # TWO: request an improvement proposal for the authenticated user's owned target.
    try:
        two = propose_mind_evolution(body.objective, body.tool_id)
        steps.append({"core": "USECT-TWO", "operation": "improvement_proposal",
                      "status": two.get("status", "proposal_created"), "result": two,
                      "target_modified": False})
    except CoreMeshError as exc:
        steps.append({"core": "USECT-TWO", "operation": "improvement_proposal",
                      "status": "unavailable", "error_code": exc.code,
                      "message": str(exc)[:300]})

    complete = all(step.get("status") not in {"unavailable", "error", "blocked"} for step in steps)
    audit_recorded = _persist_usect_event(
        user_id, "usect.orchestrator.pipeline_proposed", body.tool_id,
        {"demand_sha256": demand_sha256, "error_sha256": error_sha256,
         "step_count": len(steps), "complete": complete,
         "license_id": str(claims.get("jti") or "")},
    )
    return {
        "orchestrator": "USECT-ORCHESTRATOR",
        "status": "proposal_pipeline_completed" if complete else "partial",
        "order": ["USECT-ZERO", "USECT-ONE", "USECT-TWO"],
        "steps": steps,
        "production_merge": False,
        "automatic_execution": False,
        "human_approval_required": True,
        "audit_chain_recorded": audit_recorded,
        "note": "This runs the ordered diagnostics/recovery-proposal, Genesis queue, and Mind improvement-proposal path. A successful response is not a claim that repair, invention, improvement, or deployment completed.",
    }


DAILY_TWIN_SCAN_HOUR_UTC = 2
DAILY_TWIN_SCAN_MINUTE_UTC = 17
DAILY_TWIN_SCAN_THRESHOLD = 0.80
DAILY_TWIN_SCAN_MAX_CANDIDATES = 100
_DAILY_TWIN_SCAN_TASK: asyncio.Task[None] | None = None


def _twin_tokens(tool: ToolRecord) -> set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", f"{tool.name} {tool.description} {tool.industry}".casefold()))


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _daily_twin_scheduler_running() -> bool:
    task = _DAILY_TWIN_SCAN_TASK
    return task is not None and not task.done()


def _next_daily_twin_scan(now: datetime | None = None) -> datetime:
    """Return the next 02:17 UTC run time, always in the future."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    target = current.replace(
        hour=DAILY_TWIN_SCAN_HOUR_UTC,
        minute=DAILY_TWIN_SCAN_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if target <= current:
        target += timedelta(days=1)
    return target


def _collect_twin_candidates(
    session: Session,
    *,
    threshold: float,
    max_candidates: int,
) -> tuple[int, list[dict[str, Any]]]:
    published = session.execute(
        select(ToolRecord).where(ToolRecord.status == "published")
        .order_by(ToolRecord.created_at.desc()).limit(250)
    ).scalars().all()
    token_sets = {tool.id: _twin_tokens(tool) for tool in published}
    candidates: list[dict[str, Any]] = []
    for index, left in enumerate(published):
        for right in published[index + 1:]:
            score = _jaccard_similarity(token_sets[left.id], token_sets[right.id])
            if score >= threshold:
                candidates.append({
                    "left_tool_id": left.id, "right_tool_id": right.id,
                    "left_name": left.name, "right_name": right.name,
                    "lexical_jaccard": round(score, 4),
                    "review_status": "human_review_required",
                })
    candidates.sort(key=lambda item: item["lexical_jaccard"], reverse=True)
    return len(published), candidates[:max_candidates]


def _perform_daily_twin_scan() -> dict[str, Any]:
    """Persist one scheduled catalog scan; never evolves, publishes, or deploys a candidate."""
    scan_id = "twin_" + uuid4().hex[:24]
    with SessionLocal() as session:
        catalogue_size, candidates = _collect_twin_candidates(
            session,
            threshold=DAILY_TWIN_SCAN_THRESHOLD,
            max_candidates=DAILY_TWIN_SCAN_MAX_CANDIDATES,
        )
        row = EvolutionTwinScanRecord(
            id=scan_id,
            trigger="daily",
            status="completed",
            catalogue_size=catalogue_size,
            candidate_count=len(candidates),
            threshold=DAILY_TWIN_SCAN_THRESHOLD,
            similarity_method="lexical-token-jaccard-v1",
            candidates=candidates,
        )
        session.add(row)
        _audit(
            session,
            "system:scheduler",
            "usect.evolve.daily_twin_scan",
            scan_id,
            {
                "catalogue_size": catalogue_size,
                "candidate_count": len(candidates),
                "threshold": DAILY_TWIN_SCAN_THRESHOLD,
                "method": "lexical-token-jaccard-v1",
                "automatic_evolution": False,
            },
        )
        session.commit()
    ledger_recorded = True
    try:
        AuditLedger().append(
            actor_user_id="system:scheduler",
            action="usect.evolve.daily_twin_scan",
            object_id=scan_id,
            detail={
                "catalogue_size": catalogue_size,
                "candidate_count": len(candidates),
                "threshold": DAILY_TWIN_SCAN_THRESHOLD,
                "method": "lexical-token-jaccard-v1",
                "automatic_evolution": False,
            },
        )
    except AuditLedgerError:
        ledger_recorded = False
    return {
        "scan_id": scan_id,
        "status": "completed",
        "trigger": "daily",
        "checked_published_tools": catalogue_size,
        "candidate_count": len(candidates),
        "threshold": DAILY_TWIN_SCAN_THRESHOLD,
        "similarity_method": "lexical-token-jaccard-v1",
        "automatic_evolution": False,
        "automatic_publication": False,
        "audit_chain_recorded": ledger_recorded,
    }


async def _daily_twin_scan_loop() -> None:
    """Run a persisted read-only catalog scan each day at 02:17 UTC."""
    while True:
        due_at = _next_daily_twin_scan()
        await asyncio.sleep(max(1.0, (due_at - datetime.now(timezone.utc)).total_seconds()))
        try:
            await asyncio.to_thread(_perform_daily_twin_scan)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled USECT-EVOLVE twin scan failed; no evolution was attempted.")


@app.on_event("startup")
async def _start_daily_twin_scan_scheduler() -> None:
    global _DAILY_TWIN_SCAN_TASK
    if _DAILY_TWIN_SCAN_TASK is None or _DAILY_TWIN_SCAN_TASK.done():
        _DAILY_TWIN_SCAN_TASK = asyncio.create_task(_daily_twin_scan_loop())


@app.on_event("shutdown")
async def _stop_daily_twin_scan_scheduler() -> None:
    global _DAILY_TWIN_SCAN_TASK
    task = _DAILY_TWIN_SCAN_TASK
    _DAILY_TWIN_SCAN_TASK = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.post("/v1/evolve/scan", tags=["usect-evolve"])
def usect_evolve_twin_scan(
    body: TwinScanInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    """On-demand or scheduled lexical duplicate detection; no semantic similarity is claimed."""
    claims, _license = _active_license(session, license_key or "", user_id)
    try:
        require_enterprise_claims(claims, "evolve")
    except LicenseError as exc:
        raise _license_http_error(exc) from exc

    catalogue_size, candidates = _collect_twin_candidates(
        session, threshold=body.min_similarity, max_candidates=body.max_candidates
    )
    scan_id = "twin_" + uuid4().hex[:24]
    row = EvolutionTwinScanRecord(
        id=scan_id,
        trigger="manual",
        status="completed",
        catalogue_size=catalogue_size,
        candidate_count=len(candidates),
        threshold=body.min_similarity,
        similarity_method="lexical-token-jaccard-v1",
        candidates=candidates,
    )
    session.add(row)
    session.commit()
    audit_recorded = _persist_usect_event(
        user_id, "usect.evolve.twin_scan", scan_id,
        {"catalogue_size": catalogue_size, "candidate_count": len(candidates),
         "threshold": body.min_similarity, "method": "lexical-token-jaccard-v1"},
    )
    return {
        "scan_id": scan_id,
        "status": "completed",
        "checked_published_tools": catalogue_size,
        "candidate_count": len(candidates),
        "threshold": body.min_similarity,
        "similarity_method": "lexical-token-jaccard-v1",
        "daily_schedule_configured": True,
        "daily_schedule": "02:17 UTC",
        "scheduler_running": _daily_twin_scheduler_running(),
        "candidates": candidates,
        "automatic_evolution": False,
        "automatic_publication": False,
        "audit_chain_recorded": audit_recorded,
        "note": "This scanner uses lexical-token Jaccard similarity, not semantic embeddings. Similarity candidates require human review and measured evidence before any evolution or publication.",
    }


@app.get("/v1/evolve/scans/latest", tags=["usect-evolve"])
def usect_evolve_latest_twin_scan(
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    claims, _license = _active_license(session, license_key or "", user_id)
    try:
        require_enterprise_claims(claims, "evolve")
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    row = session.execute(
        select(EvolutionTwinScanRecord).order_by(EvolutionTwinScanRecord.created_at.desc()).limit(1)
    ).scalars().first()
    if row is None:
        return {
            "status": "no_scan_yet",
            "daily_schedule": "02:17 UTC",
            "scheduler_configured": True,
            "scheduler_running": _daily_twin_scheduler_running(),
        }
    return {
        "status": row.status,
        "scan_id": row.id,
        "trigger": row.trigger,
        "created_at": _to_iso(row.created_at),
        "catalogue_size": row.catalogue_size,
        "candidate_count": row.candidate_count,
        "threshold": row.threshold,
        "similarity_method": row.similarity_method,
        "daily_schedule": "02:17 UTC",
        "scheduler_configured": True,
        "scheduler_running": _daily_twin_scheduler_running(),
        "candidates": row.candidates,
        "automatic_evolution": False,
        "automatic_publication": False,
    }


@app.post("/v1/evolve/evolve", status_code=202, tags=["usect-evolve"])
def usect_evolve_start(
    body: EvolutionStartInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    claims, _license = _active_license(session, license_key or "", user_id)
    try:
        require_enterprise_claims(claims, "evolve")
        _require_owned_factory_or_tool(body.factory_id, user_id)
        request_model = EvolutionRequest(
            system_id=body.factory_id,
            objective=body.objective,
            metrics=body.metrics,
            evidence_refs=body.evidence_refs,
            requested_depth=body.requested_depth,
            twin_baseline=body.twin_baseline,
        )
        proposal = EvolutionEngine().propose(request_model)
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except EvolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    audit_recorded = _persist_usect_event(
        user_id, "usect.evolve.proposal_created", proposal.proposal_id,
        {"system_id": body.factory_id, "generation": proposal.generation,
         "evidence_ref_count": len(body.evidence_refs), "automatic_merge": False},
    )
    return {
        "proposal": proposal.model_dump(mode="json"),
        "status": "proposal_created",
        "improvement_factor": None,
        "benchmark_required": True,
        "human_review_required": True,
        "automatic_merge": False,
        "automatic_deployment": False,
        "audit_chain_recorded": audit_recorded,
    }


@app.get("/v1/inspector/inspect", tags=["usect-inspector"])
def usect_inspector_inspect(
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    claims, _license = _active_license(session, license_key or "", user_id)
    try:
        require_enterprise_claims(claims, "factory_build")
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    report = inspect_capabilities(app)
    report["inspected_by"] = user_id
    return report


@app.post("/v1/inspector/produce", status_code=202, tags=["usect-inspector"])
def usect_inspector_produce(
    body: InspectorProduceInput,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    claims, license_record = _active_license(session, license_key or "", user_id, country=_country(body.country))
    try:
        require_enterprise_claims(claims, "factory_build")
        enforce_tool_creation_quota(session, license_record)
        demand_sha256 = hashlib.sha256(body.demand.encode("utf-8")).hexdigest()
        supplied_requirements = body.requirements or [body.demand[:300]]
        proposal = FoundryBuilder().build_plan(
            owner_user_id=user_id,
            name=("Inspector: " + body.demand.strip())[:140],
            description=body.demand,
            requirements=supplied_requirements,
            country=_country(body.country),
            language=body.language,
            industry="inspector-simulation",
            adapters=(),
        )
        watermark = sign_tool_watermark(
            tool_id=proposal["build_id"], creator_user_id=user_id,
            factory_id=proposal["build_id"], artifact_sha256=proposal["manifest_sha256"],
        )
    except LicenseError as exc:
        raise _license_http_error(exc) from exc
    except FactoryBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DnaVaultError as exc:
        raise HTTPException(status_code=503, detail="Founder watermark signing is unavailable; the simulation was not saved.") from exc

    record = FactoryRecord(
        id=proposal["build_id"], owner_user_id=user_id,
        name=proposal["manifest"]["factory"]["name"],
        status="await_merge", country=_country(body.country),
        manifest_sha256=proposal["manifest_sha256"],
        manifest_json=proposal["manifest"],
    )
    session.add(record)
    _audit(session, user_id, "inspector.human_production_simulated", record.id,
           {"manifest_sha256": record.manifest_sha256, "demand_sha256": demand_sha256,
            "resource_claim_count": len(body.resources_available), "license_id": claims["jti"]})
    session.commit()
    audit_chain_recorded = True
    try:
        AuditLedger().append(
            actor_user_id=user_id, action="inspector.human_production_simulated",
            object_id=record.id,
            detail={"manifest_sha256": record.manifest_sha256, "demand_sha256": demand_sha256,
                    "resource_claim_count": len(body.resources_available), "license_id": claims["jti"]},
        )
    except AuditLedgerError:
        audit_chain_recorded = False

    resource_claims = [
        {"resource": str(key)[:100], "declared_value": value, "independently_verified": False}
        for key, value in list(body.resources_available.items())[:50]
    ]
    simulation = {
        "status": "proposal_only",
        "invention_steps": [
            "Normalize the requested demand and constraints.",
            "Generate a bounded Foundry workflow manifest.",
            "Identify missing resources, datasheets, acceptance tests and safeguards for human review.",
            "Hold the package for signed human approval before production use.",
        ],
        "resources_gathered": [],
        "resources_declared_unverified": resource_claims,
        "production_line": [
            {"step": "requirements_review", "executed": False},
            {"step": "prototype_and_bench_test", "executed": False},
            {"step": "qualified_safety_review", "executed": False},
            {"step": "human_release_approval", "executed": False},
        ],
        "usage_world": {
            "simulate_human_usage_requested": body.simulate_human_usage,
            "target_devices_verified": False,
            "device_migration_performed": False,
            "remote_deployment_performed": False,
            "physical_actuation_enabled": False,
        },
        "audit_pack": {
            "status": "not_issued",
            "note": "A separate draft evidence/readiness report may be generated; no legal certification is included.",
        },
        "endpoint": None,
        "guide_human": {
            "language": body.language,
            "country": _country(body.country),
            "next_steps": ["Obtain current supplier quotations.", "Verify exact datasheets and legal requirements.",
                           "Run reproducible tests.", "Secure qualified and human approval."],
        },
    }
    return {
        "factory_id": record.id,
        "seed_id": None,
        "status": "await_merge",
        "manifest_sha256": record.manifest_sha256,
        "provenance_watermark": watermark,
        "manifest": proposal["manifest"],
        "human_production_simulation": simulation,
        "production_deployed": False,
        "physical_actuation_enabled": False,
        "audit_chain_recorded": audit_chain_recorded,
    }


@app.post("/v1/auditor/reports/generate", status_code=201, tags=["usect-auditor"])
@app.post("/v1/audit/generate", status_code=201, tags=["usect-auditor"], include_in_schema=False)
def generate_compliance_readiness_report(
    body: ComplianceReportInput,
    request: Request,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
    license_key: str | None = Header(default=None, alias="X-Revela-License"),
) -> dict[str, Any]:
    claims, _license = _active_license(session, license_key or "", user_id, country=_country(body.country))
    try:
        require_enterprise_claims(claims, "compliance_draft")
    except LicenseError as exc:
        raise _license_http_error(exc) from exc

    report_id = "cr_" + uuid4().hex[:24]
    created_at = utcnow().isoformat()
    report_data: dict[str, Any] = {
        "report_id": report_id,
        "owner_user_id": user_id,
        "report_kind": body.report_kind,
        "country": _country(body.country),
        "scope": body.scope,
        "evidence_refs": body.evidence_refs,
        "checks": body.checks,
        "evidence_gaps": body.evidence_gaps or [
            "No independent laboratory test report was attached or verified.",
            "No conformity assessment by a competent authority was performed.",
            "Applicable standards, product category and jurisdiction must be independently reviewed.",
        ],
        "created_at": created_at,
        "status": "draft_readiness_report",
        "certification_issued": False,
        "certification_authority": None,
    }
    report_hash = canonical_sha256(report_data)
    report_data["report_sha256"] = report_hash
    verification_url = str(request.url_for("verify_compliance_report", report_id=report_id))
    try:
        pdf_bytes = build_compliance_readiness_pdf(report_data, verification_url=verification_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    report_data["pdf_sha256"] = pdf_hash
    record = ComplianceReportRecord(
        id=report_id, owner_user_id=user_id, report_kind=body.report_kind,
        status="draft_readiness_report", report_sha256=report_hash,
        report_json=report_data, pdf_bytes=pdf_bytes,
    )
    session.add(record)
    _audit(session, user_id, "auditor.compliance_readiness_draft_generated", report_id,
           {"report_kind": body.report_kind, "country": _country(body.country),
            "report_sha256": report_hash, "pdf_sha256": pdf_hash,
            "certification_issued": False, "license_id": str(claims.get("jti") or "")})
    session.commit()
    audit_chain_recorded = True
    try:
        AuditLedger().append(
            actor_user_id=user_id, action="auditor.compliance_readiness_draft_generated",
            object_id=report_id,
            detail={"report_kind": body.report_kind, "country": _country(body.country),
                    "report_sha256": report_hash, "pdf_sha256": pdf_hash,
                    "certification_issued": False, "license_id": str(claims.get("jti") or "")},
        )
    except AuditLedgerError:
        audit_chain_recorded = False
    return {
        "report_id": report_id,
        "report_kind": body.report_kind,
        "status": "draft_readiness_report",
        "report_sha256": report_hash,
        "pdf_sha256": pdf_hash,
        "pdf_url": str(request.url_for("download_compliance_readiness_pdf", report_id=report_id)),
        "verification_url": verification_url,
        "certification_issued": False,
        "audit_chain_recorded": audit_chain_recorded,
        "warning": DRAFT_WARNING,
    }


@app.get("/v1/auditor/reports/{report_id}/verify", tags=["usect-auditor"], name="verify_compliance_report")
def verify_compliance_readiness_report(
    report_id: str,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    record = session.get(ComplianceReportRecord, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Compliance readiness report not found.")
    data = dict(record.report_json or {})
    expected_report_hash = str(data.get("report_sha256") or "")
    expected_pdf_hash = str(data.get("pdf_sha256") or "")
    hash_basis = dict(data)
    hash_basis.pop("report_sha256", None)
    hash_basis.pop("pdf_sha256", None)
    actual_report_hash = canonical_sha256(hash_basis)
    actual_pdf_hash = hashlib.sha256(record.pdf_bytes).hexdigest()
    valid = (
        record.status == "draft_readiness_report"
        and expected_report_hash == record.report_sha256 == actual_report_hash
        and expected_pdf_hash == actual_pdf_hash
    )
    return {
        "valid": valid,
        "report_id": record.id,
        "report_kind": record.report_kind,
        "status": record.status,
        "report_sha256": record.report_sha256,
        "pdf_sha256": actual_pdf_hash,
        "created_at": _to_iso(record.created_at),
        "certification_issued": False,
        "verification_scope": "Authenticates report bytes and stored readiness metadata only; does not verify product conformity or confer a regulatory certificate.",
    }


@app.get("/v1/auditor/reports/{report_id}/pdf", tags=["usect-auditor"], name="download_compliance_readiness_pdf")
def download_compliance_readiness_pdf(
    report_id: str,
    user_id: str = Depends(authenticated_user),
    session: Session = Depends(get_db),
) -> Response:
    record = session.get(ComplianceReportRecord, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Compliance readiness report not found.")
    if record.owner_user_id != user_id and not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Only the report owner or a reviewer may download this report.")
    return Response(
        content=record.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{record.id}-{record.report_kind}-draft.pdf"',
            "X-Report-SHA256": record.report_json.get("pdf_sha256", ""),
            "Cache-Control": "private, no-store",
        },
    )


def _usect_meter_key(path: str, method: str) -> str | None:
    """Canonical operation meter map. Body and query values are deliberately ignored."""
    if path == "/v1/zero/heal" and method == "POST":
        return "usect-zero-heal"
    if path == "/v1/one/genesis" and method == "POST":
        return "usect-one-genesis"
    if path.startswith("/v1/two/improve/") and method == "POST":
        return "usect-two-improve"
    if path == "/v1/orchestrator/run" and method == "POST":
        return "usect-orchestrator-run"
    if path.startswith("/v1/evolve/") and method in {"POST", "GET"}:
        return "usect-evolve"
    if path.startswith("/v1/foundry/") or path == "/v1/inspector/produce":
        if method in {"POST", "PATCH", "PUT"}:
            return "usect-foundry-inspector"
    if path.startswith("/v1/seed/") and method in {"POST", "GET"}:
        return "usect-seed"
    if path.startswith("/v1/auditor/") or path.startswith("/v1/audit/"):
        return "usect-auditor"
    if path.startswith("/api/usect/evolve/") or path.startswith("/api/usect/migrate/"):
        return "usect-evolve-migrate"
    if path.startswith("/api/usect-zero/") and method in {"POST", "GET"}:
        return "usect-zero-gateway"
    if path.startswith("/api/core-mesh/genesis/") and method in {"POST", "GET"}:
        return "usect-one-core-mesh"
    if path.startswith("/api/core-mesh/mind/") and method in {"POST", "GET"}:
        return "usect-two-core-mesh"
    if path in {"/api/chat", "/api/chat/", "/api/revelaai/v2/brain/chat"} and method == "POST":
        return "usect-living-brain"
    return None


@app.middleware("http")
async def meter_usect_core_operations(request: Request, call_next):
    """Meter core use without logging prompts, arbitrary request fields or credentials."""
    path = request.url.path
    method = request.method.upper()
    meter_key = _usect_meter_key(path, method)
    if meter_key is None:
        return await call_next(request)

    identity: str | None = None
    try:
        identity = str(_claims_from_bearer(request.headers.get("Authorization"))["sub"])
    except HTTPException:
        # Public health/report verification probes and unauthenticated failures
        # have no account identity; they must not be assigned to a guessed user.
        identity = None

    country = "KE"
    country_hint = request.headers.get("X-Country") or request.query_params.get("country") or "KE"
    try:
        country = _country(country_hint)
    except HTTPException:
        country = "KE"

    started = time.perf_counter()
    response = await call_next(request)
    if identity:
        _record_usage_safely(
            user_id=identity, tool_id=meter_key, country=country,
            latency_ms=(time.perf_counter() - started) * 1000,
            success=response.status_code < 400,
            cost_saved_usd=0.0,
        )
    return response

# Mount RevelaAI's actual ASGI application after the platform routes above.
# The platform endpoints win by routing order; unresolved paths dispatch to FastAPI.
from asgi import app as revelaai_app  # noqa: E402
from mesh.rvx_mesh import MeshCallError, rvx_call  # noqa: E402


@app.post("/v1/{tool_id}", tags=["licensed tools"])
async def invoke_licensed_tool(
    tool_id: str,
    request: Request,
    user_id: str = Depends(authenticated_user),
) -> dict[str, Any]:
    """Invoke a published tool through an RVXP1-capable adapter, never plaintext fallback."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", tool_id):
        raise HTTPException(status_code=404, detail="Tool route is not registered")
    try:
        country = _country(request.headers.get("X-Country") or request.query_params.get("country", "KE"))
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="Tool request exceeds the 1 MB input limit")
    if raw:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Tool input must be valid JSON") from exc
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Tool input must be a JSON object")

    with SessionLocal() as session:
        tool = session.get(ToolRecord, tool_id)
        if tool is None or tool.status != "published":
            raise HTTPException(status_code=404, detail="Tool is not published")
        factory_build_id = tool.factory_build_id

    packet = {
        "protocol": "RVXP1_TOOL_INVOKE",
        "tool_id": tool_id,
        "factory_build_id": factory_build_id,
        "user_id": user_id,
        "country": country,
        "input": payload,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # urllib is blocking; move network I/O off the FastAPI event loop.
        result = await asyncio.to_thread(rvx_call, "tool." + tool_id, packet)
    except MeshCallError as exc:
        raise HTTPException(
            status_code=503,
            detail="Licensed tool adapter is unavailable or failed RVX authentication; no plaintext fallback was attempted.",
        ) from exc
    return {
        "ok": True,
        "tool_id": tool_id,
        "runtime": "rvx_mesh",
        "country": country,
        "result": result,
    }


app.mount("/", revelaai_app, name="revelaai-native-gateway")


async def _run_mounted_lifecycle_handlers(name: str) -> None:
    """Run child FastAPI on_event hooks explicitly; Starlette Mount does not propagate them."""
    for handler in getattr(revelaai_app.router, name, ()) or ():
        result = handler()
        if inspect.isawaitable(result):
            await result


@app.on_event("startup")
async def _startup_mounted_revelaai() -> None:
    await _run_mounted_lifecycle_handlers("on_startup")


@app.on_event("shutdown")
async def _shutdown_mounted_revelaai() -> None:
    await _run_mounted_lifecycle_handlers("on_shutdown")
