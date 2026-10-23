"""Signed license tokens. The private signing key is separate from the offline RVX master key."""
from __future__ import annotations

import base64
import hmac
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .plans import get_plan

ISSUER = "revelacode"


class LicenseError(RuntimeError):
    """Missing, invalid, expired, revoked or out-of-scope license."""


def _pem_from_env_or_path(env_name: str, path_env_name: str) -> bytes | None:
    configured = os.getenv(env_name, "").strip()
    if configured:
        if configured.startswith("base64:"):
            try:
                return base64.b64decode(configured[7:], validate=True)
            except Exception as exc:
                raise LicenseError(f"{env_name} is not valid base64.") from exc
        return configured.replace("\\n", "\n").encode()
    path = os.getenv(path_env_name, "").strip()
    if path:
        try:
            return Path(path).expanduser().read_bytes()
        except OSError as exc:
            raise LicenseError(f"Cannot read key configured by {path_env_name}.") from exc
    return None


def load_private_key() -> Ed25519PrivateKey:
    raw = _pem_from_env_or_path("REVELA_LICENSE_PRIVATE_KEY", "REVELA_LICENSE_PRIVATE_KEY_PATH")
    if not raw:
        raise LicenseError("License issuer is not configured; set a protected Ed25519 private signing key.")
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except Exception as exc:
        raise LicenseError("The configured license private key is not a valid PEM key.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseError("License signing key must use Ed25519.")
    return key


def load_public_key() -> Ed25519PublicKey:
    raw = _pem_from_env_or_path("REVELA_LICENSE_PUBLIC_KEY", "REVELA_LICENSE_PUBLIC_KEY_PATH")
    if raw:
        try:
            key = serialization.load_pem_public_key(raw)
        except Exception as exc:
            raise LicenseError("The configured license public key is not a valid PEM key.") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise LicenseError("License verification key must use Ed25519.")
        return key
    # Issuer service can derive its public key from its private signing key.
    return load_private_key().public_key()


def create_license_token(*, user_id: str, plan_id: str, country: str,
                         expires_at: datetime | None = None,
                         license_id: str | None = None,
                         hardware_fingerprint: str | None = None,
                         factory_ids: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    plan = get_plan(plan_id)
    now = datetime.now(timezone.utc)
    expiry = expires_at or (now + timedelta(days=30))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= now:
        raise LicenseError("Cannot issue a license that is already expired.")
    normalized_country = country.upper()
    if len(normalized_country) != 2 or not normalized_country.isalpha():
        raise LicenseError("Country must be a two-letter ISO country code.")
    if not user_id.strip():
        raise LicenseError("A verified user ID is required.")
    jti = license_id or str(uuid4())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": user_id,
        "jti": jti,
        "type": "platform_license",
        "plan": plan.id,
        "country": normalized_country,
        "max_tools": plan.tool_limit,
        "worldwide": plan.worldwide,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
        # Offline runtime is deliberately bounded even when the plan is longer-lived.
        "offline_until": int(min(expiry, now + timedelta(days=30)).timestamp()),
        "entitlements": (
            ["factory_build", "seed_create", "evolve", "migrate", "robot_build", "dna_restore",
             "marketplace_publish", "private_rvx_dialect", "compliance_draft"]
            if plan.id == "enterprise" else
            ["marketplace_publish"] if plan.id == "pro" else []
        ),
    }
    if hardware_fingerprint:
        claims["hardware_fingerprint"] = hardware_fingerprint
    if factory_ids is not None:
        claims["factory_ids"] = sorted({str(value).strip() for value in factory_ids if str(value).strip()})
    token = jwt.encode(claims, load_private_key(), algorithm="EdDSA", headers={"kid": "revela-license-v1"})
    return token, claims


def verify_license_token(token: str, *, tool_id: str | None = None,
                         now: datetime | None = None,
                         hardware_fingerprint: str | None = None,
                         factory_id: str | None = None,
                         entitlement: str | None = None) -> dict[str, Any]:
    if not token or not token.strip():
        raise LicenseError("Need RevelaCode Provider + Valid License.")
    try:
        claims = jwt.decode(
            token,
            load_public_key(),
            algorithms=["EdDSA"],
            issuer=ISSUER,
            options={"require": ["iss", "sub", "jti", "type", "plan", "country", "iat", "exp", "offline_until"]},
        )
    except LicenseError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise LicenseError("License expired. Renew the RevelaCode plan.") from exc
    except jwt.InvalidTokenError as exc:
        raise LicenseError("Need RevelaCode Provider + Valid License.") from exc
    except Exception as exc:
        raise LicenseError("License verification is unavailable; check provider key configuration.") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if int(current.timestamp()) > int(claims.get("offline_until", 0)):
        raise LicenseError("Offline license window ended. Reconnect to RevelaCode to renew verification.")
    if claims.get("type") != "platform_license":
        raise LicenseError("This license does not authorize platform tools.")
    try:
        get_plan(str(claims["plan"]))
    except (KeyError, ValueError) as exc:
        raise LicenseError("License references an unsupported plan.") from exc
    if tool_id and claims.get("tool_ids") is not None and tool_id not in claims["tool_ids"]:
        raise LicenseError("License does not cover this tool.")
    if hardware_fingerprint:
        expected_fingerprint = claims.get("hardware_fingerprint")
        if not isinstance(expected_fingerprint, str) or not hmac.compare_digest(expected_fingerprint, hardware_fingerprint):
            raise LicenseError("Hardware fingerprint mismatch. Device is not licensed.")
    if factory_id:
        allowed_factories = claims.get("factory_ids")
        if not isinstance(allowed_factories, list) or factory_id not in allowed_factories:
            raise LicenseError("License does not cover this factory.")
    if entitlement:
        entitlements = claims.get("entitlements")
        if not isinstance(entitlements, list) or entitlement not in entitlements:
            raise LicenseError(f"License does not grant the {entitlement} entitlement.")
    return claims
