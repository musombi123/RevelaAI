"""Usage metrics for the authenticated account. Payload contents are never logged."""
from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from revela_platform.database import ToolRecord, UsageEvent


def record_usage(session: Session, *, user_id: str, tool_id: str, country: str,
                 latency_ms: float, success: bool, cost_saved_usd: float = 0.0) -> UsageEvent:
    """Record verified usage; savings without a reviewed estimate remain zero."""
    normalized_country = country.upper() if len(country) == 2 else "KE"
    event = UsageEvent(
        user_id=user_id,
        tool_id=tool_id,
        country=normalized_country,
        latency_ms=max(0.0, float(latency_ms)),
        success=bool(success),
        cost_saved_usd=max(0.0, float(cost_saved_usd)) if success else 0.0,
    )
    session.add(event)
    tool = session.get(ToolRecord, tool_id)
    if tool is not None:
        tool.usage_count += 1
    session.commit()
    session.refresh(event)
    return event


def usage_summary(session: Session, user_id: str) -> dict[str, Any]:
    total, successful, cost_saved = session.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(case((UsageEvent.success.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(UsageEvent.cost_saved_usd), 0.0),
        ).where(UsageEvent.user_id == user_id)
    ).one()
    by_country_rows = session.execute(
        select(UsageEvent.country, func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.cost_saved_usd), 0.0))
        .where(UsageEvent.user_id == user_id)
        .group_by(UsageEvent.country)
    ).all()
    top_rows = session.execute(
        select(UsageEvent.tool_id, func.count(UsageEvent.id).label("calls"))
        .where(UsageEvent.user_id == user_id)
        .group_by(UsageEvent.tool_id)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(10)
    ).all()
    return {
        "user_id": user_id,
        "total_calls": int(total or 0),
        "successful_calls": int(successful or 0),
        "cost_saved_usd": round(float(cost_saved or 0.0), 2),
        "cost_saved_per_country": {
            row[0]: {"calls": int(row[1]), "cost_saved_usd": round(float(row[2] or 0.0), 2)}
            for row in by_country_rows
        },
        "top_tools": [{"tool_id": row[0], "calls": int(row[1])} for row in top_rows],
        "savings_note": "Only amounts backed by a reviewed tool estimate are counted.",
    }
