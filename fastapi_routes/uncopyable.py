"""FastAPI routes for recipe integrity, signed provenance and DNA Vault controls."""
from __future__ import annotations

import base64
import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from core_uncopyable.dna_vault_guard import (
    DnaVaultError,
    restore_dna_vault,
    verify_tool_watermark,
)
from core_uncopyable.hardware_bind import hardware_status
from core_uncopyable.recipe_lock import recipe_lock_status
from core_uncopyable.rvx_evolver import verify_dialect

router = APIRouter(tags=["uncopyable"])


def _require_admin(supplied: str | None) -> None:
    expected = os.getenv("REVELA_ORGAN_ADMIN_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="Uncopyable administration is not configured.")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid organ administrator token.")


class RestoreInput(BaseModel):
    encrypted_blob_b64: str = Field(min_length=20, max_length=8_000_000)
    signature_payload: dict[str, Any]
    founder_signature_b64: str = Field(min_length=40, max_length=1000)


@router.get("/v1/verify/{tool_id}", tags=["provenance"])
def verify_tool(tool_id: str) -> dict[str, Any]:
    """Publicly verify a tool's founder-signed provenance watermark."""
    if not tool_id.strip() or len(tool_id) > 180:
        raise HTTPException(status_code=422, detail="Invalid tool identifier.")
    return verify_tool_watermark(tool_id)


@router.get("/v1/uncopyable/status", tags=["uncopyable"])
def uncopyable_status(
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_organ_admin_token)
    recipe = recipe_lock_status()
    hardware = hardware_status()
    dialect = verify_dialect()
    return {
        "ok": bool(recipe.get("locked") and hardware.get("available")),
        "mode": "observe_and_enforce_when_configured",
        "locks": {
            "recipe": recipe,
            "license": {
                "configured": bool(os.getenv("REVELA_LICENSE_PUBLIC_KEY") or os.getenv("REVELA_LICENSE_PUBLIC_KEY_PATH")),
                "private_signing_key_configured": bool(os.getenv("REVELA_LICENSE_PRIVATE_KEY") or os.getenv("REVELA_LICENSE_PRIVATE_KEY_PATH")),
            },
            "hardware": hardware,
            "rvx_dialect": dialect,
            "dna_vault": {
                "configured": bool(os.getenv("REVELA_DNA_VAULT_PATH")),
                "watermark_store_configured": bool(os.getenv("REVELA_WATERMARK_STORE")),
            },
        },
        "destructive_self_wipe": False,
    }


@router.post("/v1/uncopyable/restore", tags=["uncopyable"])
def restore_dna(
    body: RestoreInput,
    x_organ_admin_token: str | None = Header(default=None, alias="X-Organ-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_organ_admin_token)
    try:
        encrypted_blob = base64.b64decode(body.encrypted_blob_b64, validate=True)
        if not encrypted_blob:
            raise ValueError("empty encrypted vault")
        result = restore_dna_vault(
            encrypted_blob,
            signature_payload=body.signature_payload,
            signature_b64=body.founder_signature_b64,
        )
    except (ValueError, DnaVaultError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True, **result}
