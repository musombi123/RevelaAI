"""Stripe Checkout and signature validation. No license is minted from a browser redirect."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

import httpx


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentProviderError(RuntimeError):
    pass


async def create_stripe_checkout(*, intent_id: str, user_id: str, purpose: str,
                                 amount_cents: int, name: str, country: str,
                                 metadata: dict[str, str], subscription: bool) -> dict[str, str]:
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise PaymentConfigurationError("Stripe Checkout is not configured. No license was issued.")
    if amount_cents < 100:
        raise ValueError("Checkout amount must be at least USD 1.00.")
    success = os.getenv("REVELA_BILLING_SUCCESS_URL", "https://revelacode.com/billing/success")
    cancel = os.getenv("REVELA_BILLING_CANCEL_URL", "https://revelacode.com/billing/cancel")
    mode = "subscription" if subscription else "payment"
    form: dict[str, str] = {
        "mode": mode,
        "success_url": success + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel,
        "client_reference_id": user_id,
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": name[:120],
        "metadata[intent_id]": intent_id,
        "metadata[purpose]": purpose,
        "metadata[user_id]": user_id,
        "metadata[country]": country,
    }
    if not subscription:
        form["customer_creation"] = "always"
    if subscription:
        form["line_items[0][price_data][recurring][interval]"] = "month"
        form["subscription_data[metadata][intent_id]"] = intent_id
        form["subscription_data[metadata][user_id]"] = user_id
        form["subscription_data[metadata][plan]"] = metadata.get("plan", "")
        form["subscription_data[metadata][country]"] = country
    for key, value in metadata.items():
        if value:
            form[f"metadata[{key}]"] = str(value)[:500]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=form,
                auth=(secret, ""),
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PaymentProviderError("Stripe checkout could not be created.") from exc
    url = payload.get("url")
    session_id = payload.get("id")
    if not isinstance(url, str) or not url.startswith("https://checkout.stripe.com/") or not isinstance(session_id, str):
        raise PaymentProviderError("Stripe returned an unexpected checkout response.")
    return {"checkout_url": url, "session_id": session_id}


def verify_stripe_signature(body: bytes, signature_header: str, *,
                             secret: str | None = None, now: int | None = None,
                             tolerance_seconds: int = 300) -> bool:
    webhook_secret = (secret or os.getenv("STRIPE_WEBHOOK_SECRET", "")).strip()
    if not webhook_secret or not signature_header:
        return False
    parts: dict[str, list[str]] = {}
    for component in signature_header.split(","):
        if "=" not in component:
            continue
        key, value = component.split("=", 1)
        parts.setdefault(key.strip(), []).append(value.strip())
    timestamps = parts.get("t", [])
    signatures = parts.get("v1", [])
    if len(timestamps) != 1 or not signatures:
        return False
    try:
        timestamp = int(timestamps[0])
    except ValueError:
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > tolerance_seconds:
        return False
    signed_payload = str(timestamp).encode() + b"." + body
    expected = hmac.new(webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)
