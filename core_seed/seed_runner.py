"""Seed child factory bundles offline using signed, time-bounded license claims.

This runner copies and verifies declarative factory manifests; it never imports
or executes untrusted child Python. Offline time is limited by the signed license
claim. Local clock rollback cannot be fully prevented without trusted hardware.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core_billing.licensing import LicenseError, verify_license_token
from core_foundry.factory.foundry_builder import FoundryBuilder, factory_root


class SeedError(RuntimeError):
    """Seed cannot validate, authorize, or persist a child factory."""


def seed_root() -> Path:
    return Path(os.getenv("REVELA_SEED_ROOT", str(Path.home() / ".revelaai" / "seeded"))).expanduser()


class SeedRunner:
    def __init__(self, output_root: str | Path | None = None,
                 foundry: FoundryBuilder | None = None) -> None:
        self.output_root = Path(output_root).expanduser() if output_root else seed_root()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.foundry = foundry or FoundryBuilder()

    def seed_child(self, *, build_id: str, license_key: str, user_id: str,
                   child_name: str, now: datetime | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9 _.-]{1,99}", child_name.strip()):
            raise SeedError("Child name contains unsupported characters or length.")
        try:
            claims = verify_license_token(license_key, now=now)
        except LicenseError as exc:
            raise SeedError(str(exc)) from exc
        if claims.get("sub") != user_id:
            raise SeedError("License owner does not match authenticated user.")
        try:
            source = self.foundry.get_manifest(build_id)
        except (ValueError, OSError) as exc:
            raise SeedError("Source factory manifest is invalid or unavailable.") from exc
        if source.get("owner_user_id") != user_id:
            # Enterprise customers may seed a factory purchased from the marketplace.
            # That case requires caller-provided proof of purchase; not implied here.
            raise SeedError("Only the owner of this factory proposal may seed it.")
        if source.get("status") != "await_merge":
            raise SeedError("Only reviewable factory proposals may be seeded by this runner.")
        seed_id = "seed_" + hashlib.sha256(
            f"{build_id}:{user_id}:{child_name.strip()}".encode()
        ).hexdigest()[:24]
        target_dir = self.output_root / seed_id
        if target_dir.exists():
            raise SeedError("This child factory has already been seeded.")
        created = datetime.now(timezone.utc)
        offline_until = int(claims.get("offline_until", 0))
        if int((now or created).timestamp()) > offline_until:
            raise SeedError("Offline authorization window expired.")
        child = {
            "schema_version": 1,
            "seed_id": seed_id,
            "parent_build_id": build_id,
            "child_name": child_name.strip(),
            "owner_user_id": user_id,
            "license_id": claims.get("jti"),
            "plan": claims.get("plan"),
            "seeded_at": created.isoformat(),
            "offline_until": offline_until,
            "status": "seeded_review_required",
            "factory_manifest": source,
            "execution_policy": {
                "offline_declarative_mode": True,
                "arbitrary_code_execution": False,
                "network_required_for_validation": False,
                "hardware_actuation": False,
                "human_activation_required": True,
            },
        }
        target_dir.mkdir(parents=True, exist_ok=False)
        temp = target_dir / ".child.tmp"
        final = target_dir / "child.json"
        try:
            temp.write_text(json.dumps(child, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, final)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return {"seed_id": seed_id, "status": child["status"], "offline_until": offline_until,
                "path": str(final), "note": "Declarative child seeded; code execution and activation remain disabled."}
