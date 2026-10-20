"""Signed-license entitlement checks shared by API and internal services."""
from __future__ import annotations

from typing import Any

from core_billing.licensing import LicenseError, verify_license_token

ENTERPRISE_ENTITLEMENTS = frozenset({
    "factory_build", "seed_create", "evolve", "migrate", "robot_build", "dna_restore",
})


class EntitlementError(LicenseError):
    """The signed license is valid but does not grant the requested capability."""


def require_entitlement(
    token: str,
    entitlement: str,
    *,
    hardware_fingerprint: str | None = None,
    factory_id: str | None = None,
) -> dict[str, Any]:
    """Verify signature, expiry, device/factory scope and the requested entitlement."""
    claims = verify_license_token(
        token,
        hardware_fingerprint=hardware_fingerprint,
        factory_id=factory_id,
        entitlement=entitlement,
    )
    if entitlement in ENTERPRISE_ENTITLEMENTS and claims.get("plan") != "enterprise":
        raise EntitlementError(f"Enterprise plan required for {entitlement}.")
    return claims


def require_enterprise_claims(claims: dict[str, Any], entitlement: str) -> dict[str, Any]:
    """Enforce an already-verified token's entitlement without trusting request data."""
    if entitlement not in ENTERPRISE_ENTITLEMENTS:
        raise EntitlementError("Unknown protected entitlement.")
    granted = claims.get("entitlements")
    if claims.get("plan") != "enterprise" or not isinstance(granted, list) or entitlement not in granted:
        raise EntitlementError(f"Enterprise plan with {entitlement} entitlement required.")
    return claims
