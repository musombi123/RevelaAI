"""Marketplace policy and response shaping."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from revela_platform.database import CreatorEarning, ToolRecord

BLOCKED_TERMS = (
    "ransomware", "credential theft", "steal passwords", "keylogger",
    "malware deployment", "explosive device", "weaponized", "spyware",
)


def safety_screen(name: str, description: str, endpoint: str) -> tuple[bool, str]:
    material = " ".join((name, description, endpoint)).casefold()
    if any(term in material for term in BLOCKED_TERMS):
        return False, "Listing was blocked by the deterministic safety screen."
    return True, "No deterministic block matched; human review is still required."


def country_bundle(tool: ToolRecord, country: str, language: str | None = None) -> dict[str, Any]:
    country = country.upper()
    bom = tool.bom_by_country or {}
    guides = tool.guides_by_language or {}
    selected_bom = bom.get(country) or bom.get("global")
    selected_language = (language or ("sw" if country == "KE" else "en")).lower()
    selected_guide = guides.get(selected_language) or guides.get("en")
    return {
        "tool_id": tool.id,
        "name": tool.name,
        "description": tool.description,
        "industry": tool.industry,
        "country_origin": tool.country_origin,
        "endpoint": tool.endpoint,
        "price_usd": round(tool.price_usd_cents / 100, 2),
        "buyer_country": country,
        "bom": selected_bom,
        "bom_available_for_country": selected_bom is not None,
        "guide_language": selected_language if selected_guide is not None else None,
        "hardware_guide": selected_guide,
        "rating": round(tool.rating_total / tool.rating_count, 2) if tool.rating_count else None,
        "usage_count": tool.usage_count,
    }


def creator_earnings(session: Session, user_id: str) -> dict[str, Any]:
    rows = session.execute(
        select(CreatorEarning).where(CreatorEarning.creator_user_id == user_id)
    ).scalars().all()
    total = sum(row.amount_usd_cents for row in rows)
    pending = sum(row.amount_usd_cents for row in rows if row.status == "pending_payout")
    return {
        "user_id": user_id,
        "currency": "USD",
        "earned_total": round(total / 100, 2),
        "pending_payout": round(pending / 100, 2),
        "sales_count": len(rows),
        "payout_note": "Recorded earnings are pending until a payout provider is configured.",
    }
