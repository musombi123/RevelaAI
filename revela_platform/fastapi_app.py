"""FastAPI revenue gateway with the existing Flask API mounted as a fallback.

Registered published tool routes are license-gated before Flask dispatch. The
existing Flask app and ZERO/ONE/TWO Go services are not rewritten.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.wsgi import WSGIMiddleware

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
from marketplace.service import country_bundle, creator_earnings, safety_screen
from revela_platform.database import (
    AuditRecord,
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

app = FastAPI(
    title="RevelaCode Revenue and RVX API",
    version="0.1.0",
    description="Python-native billing, signed licensing, usage metering, marketplace and encrypted RVX integrations.",
    docs_url="/v1/platform/docs",
    openapi_url="/v1/platform/openapi.json",
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
            options={"require": ["sub", "iat", "exp"]},
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
    price_usd_cents: int = Field(ge=100, le=100000000)
    bom_by_country: dict[str, Any] = Field(default_factory=dict)
    guides_by_language: dict[str, Any] = Field(default_factory=dict)
    verified_cost_saved_usd: float = Field(default=0.0, ge=0, le=10000000)


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
    allowed, note = safety_screen(body.name, body.description, body.endpoint)
    status = "pending_review" if allowed else "rejected"
    tool = ToolRecord(
        id=body.tool_id, creator_user_id=user_id, name=body.name.strip(),
        description=body.description.strip(), industry=body.industry.strip().lower(),
        country_origin=country, endpoint=body.endpoint, price_usd_cents=body.price_usd_cents,
        status=status, bom_by_country={str(k).upper(): v for k, v in body.bom_by_country.items()},
        guides_by_language={str(k).lower(): v for k, v in body.guides_by_language.items()},
        # This amount only counts when a verified reference has been supplied by review.
        verified_cost_saved_usd=body.verified_cost_saved_usd,
    )
    session.add(tool)
    _audit(session, user_id, "marketplace.tool.submitted", tool.id,
           {"status": status, "safety_note": note, "license_id": claims["jti"]})
    session.commit()
    if not allowed:
        raise HTTPException(status_code=403, detail=note)
    return {"tool_id": tool.id, "status": status, "safety_note": note,
            "next_step": "A configured reviewer must approve this listing before it becomes searchable or callable."}


class ReviewToolInput(BaseModel):
    approved: bool
    review_note: str = Field(min_length=3, max_length=1200)


@app.post("/v1/marketplace/{tool_id}/review", tags=["marketplace"])
def review_tool(tool_id: str, body: ReviewToolInput,
                user_id: str = Depends(authenticated_user),
                session: Session = Depends(get_db)) -> dict[str, Any]:
    if not _reviewer(user_id):
        raise HTTPException(status_code=403, detail="Marketplace reviewer permission required")
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
    _audit(session, user_id, "marketplace.tool.reviewed", tool_id,
           {"approved": body.approved, "review_note": body.review_note})
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
    if rating is None:
        rating = ToolRating(tool_id=tool_id, user_id=user_id, rating=body.rating)
        session.add(rating)
    else:
        tool.rating_total -= rating.rating
        rating.rating = body.rating
    tool.rating_total += body.rating
    if not session.execute(
        select(ToolRating.id).where(ToolRating.tool_id == tool_id, ToolRating.user_id == user_id)
    ).first() or rating.id is None:
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


# Tool licensing guard for future and already-registered single-segment tool endpoints.
# Unregistered paths continue into the original Flask gateway unchanged.
@app.middleware("http")
async def licensed_tool_guard(request: Request, call_next):
    path = request.url.path
    parts = path.strip("/").split("/")
    tool_id = parts[1] if len(parts) == 2 and parts[0] == "v1" else None
    method = request.method.upper()
    tracked_tool: ToolRecord | None = None
    if tool_id and method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        try:
            with SessionLocal() as lookup:
                candidate = lookup.get(ToolRecord, tool_id)
                if candidate is not None and candidate.status == "published":
                    tracked_tool = candidate
        except Exception:
            tracked_tool = None
    if tracked_tool is None:
        return await call_next(request)

    identity = None
    try:
        identity = _claims_from_bearer(request.headers.get("Authorization")).get("sub")
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    license_key = request.headers.get("X-Revela-License", "")
    country = _country(request.headers.get("X-Country") or request.query_params.get("country", "KE"))
    started = time.perf_counter()
    try:
        with SessionLocal() as guard_session:
            _active_license(guard_session, license_key, str(identity), country=country, tool_id=tool_id)
            if tracked_tool.creator_user_id != identity:
                paid = guard_session.execute(
                    select(CheckoutIntent.id).where(
                        CheckoutIntent.user_id == identity,
                        CheckoutIntent.purpose == "marketplace",
                        CheckoutIntent.tool_id == tool_id,
                        CheckoutIntent.status == "paid",
                    ).limit(1)
                ).first()
                if not paid:
                    return JSONResponse(
                        status_code=402,
                        content={"error": "A paid marketplace purchase is required for this tool.",
                                 "endpoint": "/v1/marketplace/buy"},
                    )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})
    response = await call_next(request)
    latency_ms = (time.perf_counter() - started) * 1000
    try:
        with SessionLocal() as meter_session:
            current_tool = meter_session.get(ToolRecord, tool_id)
            cost = current_tool.verified_cost_saved_usd if current_tool is not None else 0.0
            record_usage(
                meter_session, user_id=str(identity), tool_id=tool_id, country=country,
                latency_ms=latency_ms, success=response.status_code < 400,
                cost_saved_usd=cost,
            )
    except Exception:
        # Meter failure should be observable in logs but must not turn a completed
        # tool action into a retry that could duplicate physical actions.
        import logging
        logging.getLogger(__name__).exception("usage event could not be persisted")
    return response


# Preserve all existing Flask endpoints. FastAPI routers/docs above this mount win
# route priority; unresolved routes are passed to the original Flask WSGI app.
from app import app as flask_app  # noqa: E402

app.mount("/", WSGIMiddleware(flask_app), name="existing-flask-gateway")
