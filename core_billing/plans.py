"""Published platform plans; monetary values are USD list prices in cents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    id: str
    monthly_usd_cents: int
    tool_limit: int | None
    worldwide: bool
    description: str


PLANS: dict[str, Plan] = {
    "local": Plan("local", 1000, 10, False, "Local plan; one licensed country; up to 10 tools"),
    "pro": Plan("pro", 50000, 100, True, "Pro Worldwide; up to 100 tools; marketplace access"),
    "enterprise": Plan("enterprise", 1000000, None, True, "Enterprise; unlimited tools; private deployment/dialect options"),
}


def get_plan(plan_id: str) -> Plan:
    normalized = plan_id.strip().lower()
    try:
        return PLANS[normalized]
    except KeyError as exc:
        raise ValueError("Unknown plan. Available plans: local, pro, enterprise.") from exc


def can_use_country(plan_id: str, licensed_country: str, request_country: str) -> bool:
    plan = get_plan(plan_id)
    return plan.worldwide or licensed_country.upper() == request_country.upper()
