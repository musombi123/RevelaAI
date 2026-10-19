"""SQLAlchemy persistence for licenses, usage, marketplace and webhook idempotency."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class LicenseRecord(Base):
    __tablename__ = "revela_licenses"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    plan: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(2))
    tool_limit: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    checkout_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactoryRecord(Base):
    __tablename__ = "revela_factory_builds"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(32), default="await_merge", index=True)
    country: Mapped[str] = mapped_column(String(2), default="KE")
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SeedRecord(Base):
    __tablename__ = "revela_seeded_children"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_build_id: Mapped[str] = mapped_column(String(64), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), index=True)
    license_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="seeded_review_required")
    offline_until: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolRecord(Base):
    __tablename__ = "revela_marketplace_tools"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    creator_user_id: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(String(80), default="general", index=True)
    country_origin: Mapped[str] = mapped_column(String(2), default="KE")
    endpoint: Mapped[str] = mapped_column(String(240))
    factory_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    price_usd_cents: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(24), default="pending_review", index=True)
    bom_by_country: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    guides_by_language: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verified_cost_saved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    rating_total: Mapped[int] = mapped_column(Integer, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageEvent(Base):
    __tablename__ = "revela_usage_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    tool_id: Mapped[str] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(2), default="KE", index=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_saved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CheckoutIntent(Base):
    __tablename__ = "revela_checkout_intents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    plan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="KE")
    tool_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    creator_user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    amount_usd_cents: Mapped[int] = mapped_column(Integer)
    creator_share_cents: Mapped[int] = mapped_column(Integer, default=0)
    platform_share_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatorEarning(Base):
    __tablename__ = "revela_creator_earnings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkout_intent_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    creator_user_id: Mapped[str] = mapped_column(String(160), index=True)
    amount_usd_cents: Mapped[int] = mapped_column(Integer)
    platform_fee_usd_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending_payout")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessedWebhook(Base):
    __tablename__ = "revela_processed_webhooks"
    event_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolRating(Base):
    __tablename__ = "revela_tool_ratings"
    __table_args__ = (UniqueConstraint("tool_id", "user_id", name="uq_revela_rating_user_tool"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_id: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditRecord(Base):
    __tablename__ = "revela_platform_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[str] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    object_id: Mapped[str] = mapped_column(String(160), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def _database_url() -> str:
    configured = os.getenv("REVELA_DATABASE_URL", "").strip()
    if configured:
        # Render and other PostgreSQL providers may supply postgres:// URLs.
        if configured.startswith("postgres://"):
            configured = "postgresql+psycopg://" + configured[len("postgres://"):]
        elif configured.startswith("postgresql://") and "+" not in configured.split(":", 1)[0]:
            configured = "postgresql+psycopg://" + configured[len("postgresql://"):]
        return configured
    data_dir = Path(os.getenv("REVELA_DATA_DIR", str(Path.home() / ".revelaai"))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(data_dir / "revela_platform.sqlite3")


DATABASE_URL = _database_url()
_engine_options: dict[str, Any] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite:"):
    _engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
engine = create_engine(DATABASE_URL, **_engine_options)
if DATABASE_URL.startswith("sqlite:"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
