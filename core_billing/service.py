"""Server-side license state and quota checks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_billing.licensing import LicenseError, verify_license_token
from core_billing.plans import get_plan
from revela_platform.database import FactoryRecord, LicenseRecord, SeedRecord, ToolRecord


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def require_active_license(session: Session, token: str, user_id: str, *,
                           country: str | None = None, tool_id: str | None = None) -> tuple[dict[str, Any], LicenseRecord]:
    claims = verify_license_token(token, tool_id=tool_id)
    if claims.get("sub") != user_id:
        raise LicenseError("License owner does not match the authenticated user.")
    record = session.get(LicenseRecord, str(claims["jti"]))
    if record is None or record.status != "active":
        raise LicenseError("License is missing, revoked or not activated by the provider.")
    if _aware(record.expires_at) <= datetime.now(timezone.utc):
        raise LicenseError("License expired. Renew the RevelaCode plan.")
    if country and not get_plan(record.plan).worldwide and record.country.upper() != country.upper():
        raise LicenseError("This Local license is limited to its licensed country. Upgrade to Pro Worldwide.")
    return claims, record


def enforce_tool_creation_quota(session: Session, license_record: LicenseRecord) -> None:
    plan = get_plan(license_record.plan)
    if plan.tool_limit is None:
        return
    factory_count = session.scalar(
        select(func.count()).select_from(FactoryRecord).where(
            FactoryRecord.owner_user_id == license_record.user_id,
            FactoryRecord.status != "rejected",
        )
    ) or 0
    standalone_tool_count = session.scalar(
        select(func.count()).select_from(ToolRecord).where(
            ToolRecord.creator_user_id == license_record.user_id,
            ToolRecord.status != "rejected",
            ToolRecord.factory_build_id.is_(None),
        )
    ) or 0
    seeded_children_count = session.scalar(
        select(func.count()).select_from(SeedRecord).where(
            SeedRecord.owner_user_id == license_record.user_id,
            SeedRecord.status != "revoked",
        )
    ) or 0
    created = int(factory_count) + int(standalone_tool_count) + int(seeded_children_count)
    if created >= plan.tool_limit:
        raise LicenseError(f"Plan limit reached ({plan.tool_limit} tools). Upgrade to Enterprise or a higher plan.")
