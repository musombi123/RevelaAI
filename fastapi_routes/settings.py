"""Authenticated, versioned user preferences API for RevelaAI."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fastapi_routes.auth import authenticate_identity
from revela_platform.database import SessionLocal, UserPreferenceRecord

router = APIRouter(prefix="/api/settings", tags=["Settings"])
LOG = logging.getLogger("revelaai.settings")
SCHEMA_VERSION = 1
ALLOWED_SECTIONS = {
    "appearance", "language_region", "ai_behavior", "search_research", "images",
    "office_accounting", "voice", "memory", "notifications", "privacy",
    "accessibility", "plan_usage", "models_mode",
}
SECTION_FIELDS = {
    "appearance": {"theme","scheduled_start","scheduled_end","accent","custom_accent","chat_background","font","font_size","density","message_width","style","code_theme","reduce_motion","high_contrast"},
    "language_region": {"interface_language","ai_reply_language","country","timezone","date_format","number_format","currency","units","week_start"},
    "ai_behavior": {"response_style","tone","reading_level","role_preset","about_me","custom_instructions","show_step_by_step","always_show_sources","ask_deep_search","default_tools"},
    "search_research": {"default_mode","preferred_regions","preferred_languages","trusted_sources","blocked_domains","citation_style","freshness"},
    "images": {"aspect_ratio","style","auto_enhance","save_format","watermark"},
    "office_accounting": {"document_language","template","page_size","default_font","brand_colours","brand_logo","company_name","company_address","vat_region","vat_rate","financial_year_start","currency","number_format","export_format"},
    "voice": {"voice","speed","language","auto_read","mode"},
    "memory": {"enabled","paused"},
    "notifications": {"email_jobs","in_app_jobs","daily_limits","plan_expiry","support_replies","product_news","quiet_start","quiet_end"},
    "privacy": {"history_enabled","auto_delete_days","shared_links","third_party_connections"},
    "accessibility": {"screen_reader","large_targets","voice_captions","colour_blind_charts","keyboard_shortcuts"},
    "plan_usage": set(),
    "models_mode": {"quality","allow_backup"},
}
_BLOCKED_INSTRUCTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|system|developer)\s+instructions", re.I),
    re.compile(r"(?:disable|bypass|override|ignore)\s+(?:safety|sci\s*defender|meta\s*(?:lab\s*)?engine|plan\s*limits|tool\s*entitlements)", re.I),
    re.compile(r"reveal\s+(?:the\s+)?(?:system\s+prompt|secrets|api\s*keys|credentials)", re.I),
)

class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=SCHEMA_VERSION, ge=1, le=SCHEMA_VERSION)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - ALLOWED_SECTIONS
        if unknown:
            raise ValueError("Unknown settings section: " + ", ".join(sorted(unknown)))
        for section, values in value.items():
            if not isinstance(values, dict):
                raise ValueError(f"{section} must be an object.")
            unknown_fields = set(values) - SECTION_FIELDS[section]
            if unknown_fields:
                raise ValueError(f"Unknown fields in {section}: " + ", ".join(sorted(unknown_fields)))
            for field_name, item in values.items():
                if isinstance(item, str) and len(item) > 1500:
                    raise ValueError(f"{section}.{field_name} exceeds 1500 characters.")
                if isinstance(item, list) and (len(item) > 100 or not all(isinstance(part, (str, int, float, bool)) for part in item)):
                    raise ValueError(f"{section}.{field_name} must be a list of simple values.")
                if item is not None and not isinstance(item, (str, int, float, bool, list)):
                    raise ValueError(f"{section}.{field_name} has an unsupported value type.")
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) > 48_000:
            raise ValueError("Settings payload is too large.")
        behavior = value.get("ai_behavior")
        if isinstance(behavior, dict):
            for key in ("about_me", "custom_instructions"):
                item = behavior.get(key)
                if item is not None and (not isinstance(item, str) or len(item) > 1500):
                    raise ValueError(f"{key} must be text no longer than 1500 characters.")
        return value


def _identity(request: Request) -> str:
    oid, user_id, error = authenticate_identity(
        request.headers.get("Authorization", ""), dict(request.headers), {},
    )
    if error:
        raise HTTPException(status_code=error.status_code, detail="A valid RevelaCode login is required.")
    if not user_id:
        raise HTTPException(status_code=401, detail="A valid RevelaCode account is required.")
    return str(user_id)


def _screen_custom_instructions(settings: dict[str, Any]) -> None:
    behavior = settings.get("ai_behavior")
    if not isinstance(behavior, dict):
        return
    text_value = "\n".join(str(behavior.get(key) or "") for key in ("about_me", "custom_instructions"))
    if not text_value.strip():
        return
    if any(pattern.search(text_value) for pattern in _BLOCKED_INSTRUCTION_PATTERNS):
        raise HTTPException(status_code=422, detail="These instructions attempt to override protected RevelaAI rules and were not saved.")
    try:
        from revelai.sci_core.defensive_shield import PATTERNS
        normalized = json.dumps({"user_preferences": text_value}, ensure_ascii=False)
        for pattern, severity, _recommendation in PATTERNS:
            if severity == "critical" and pattern.search(normalized):
                raise HTTPException(status_code=422, detail="Sci Defender rejected unsafe custom instructions.")
    except HTTPException:
        raise
    except Exception as exc:
        LOG.warning("Sci Defender could not validate custom preferences | type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Sci Defender is unavailable; custom instructions were not saved.") from exc


@router.get("")
def get_settings(request: Request):
    user_id = _identity(request)
    with SessionLocal() as session:
        record = session.get(UserPreferenceRecord, user_id)
        if record is None:
            return {"version": SCHEMA_VERSION, "settings": {}, "updated_at": None}
        return {"version": record.schema_version, "settings": record.settings_json or {},
                "updated_at": record.updated_at.isoformat() if record.updated_at else None}


@router.put("")
def put_settings(body: SettingsInput, request: Request):
    user_id = _identity(request)
    _screen_custom_instructions(body.settings)
    with SessionLocal() as session:
        record = session.get(UserPreferenceRecord, user_id)
        if record is None:
            record = UserPreferenceRecord(user_id=user_id, schema_version=SCHEMA_VERSION,
                                          settings_json=body.settings)
            session.add(record)
        else:
            record.schema_version = SCHEMA_VERSION
            record.settings_json = body.settings
        session.commit()
        session.refresh(record)
        return {"version": record.schema_version, "settings": record.settings_json,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None}
