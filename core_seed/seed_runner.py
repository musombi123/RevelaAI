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
from core_foundry.factory.foundry_builder import FactoryBuildError, FoundryBuilder


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
                   child_name: str, now: datetime | None = None,
                   purchase_verified: bool = False,
                   source_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9 _.-]{1,99}", child_name.strip()):
            raise SeedError("Child name contains unsupported characters or length.")
        try:
            claims = verify_license_token(license_key, now=now)
        except LicenseError as exc:
            raise SeedError(str(exc)) from exc
        if claims.get("sub") != user_id:
            raise SeedError("License owner does not match authenticated user.")
        try:
            if source_manifest is None:
                source = self.foundry.get_manifest(build_id)
            else:
                source = FoundryBuilder.validate_manifest(source_manifest)
                if source.get("build_id") != build_id:
                    raise SeedError("Factory manifest ID does not match requested build.")
        except (FactoryBuildError, ValueError, OSError) as exc:
            raise SeedError("Source factory manifest is invalid or unavailable.") from exc
        if source.get("owner_user_id") != user_id and not purchase_verified:
            raise SeedError("Only the owner or a verified marketplace buyer may seed this factory.")
        if source.get("status") != "approved":
            raise SeedError("Factory must pass human review before seeding.")
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
            "license_token": license_key,
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
        canonical_child = json.dumps(child, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        child["child_sha256"] = hashlib.sha256(canonical_child).hexdigest()
        target_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        temp = target_dir / ".child.tmp"
        final = target_dir / "child.json"
        try:
            temp.write_text(json.dumps(child, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            try:
                temp.chmod(0o600)
            except OSError:
                pass
            os.replace(temp, final)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return {"seed_id": seed_id, "status": child["status"], "offline_until": offline_until,
                "path": str(final), "note": "Declarative child seeded; code execution and activation remain disabled."}

    def verify_child_offline(self, seed_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Locally verify a child manifest and its signed offline entitlement."""
        if not re.fullmatch(r"seed_[a-f0-9]{24}", seed_id):
            raise SeedError("Invalid child seed identifier.")
        path = (self.output_root / seed_id / "child.json").resolve()
        if self.output_root.resolve() not in path.parents:
            raise SeedError("Child manifest path is outside the seed root.")
        try:
            child = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SeedError("Child bundle could not be read.") from exc
        claimed_hash = child.pop("child_sha256", None)
        actual_hash = hashlib.sha256(
            json.dumps(child, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if not isinstance(claimed_hash, str) or not __import__("hmac").compare_digest(claimed_hash, actual_hash):
            raise SeedError("Child manifest integrity check failed.")
        token = child.get("license_token")
        try:
            claims = verify_license_token(token, now=now)
        except LicenseError as exc:
            raise SeedError(str(exc)) from exc
        if claims.get("sub") != child.get("owner_user_id"):
            raise SeedError("Child owner does not match signed license.")
        if claims.get("jti") != child.get("license_id"):
            raise SeedError("Child license ID does not match signed license.")
        if int(claims.get("offline_until", 0)) != int(child.get("offline_until", -1)):
            raise SeedError("Child offline lease differs from signed license.")
        if child.get("status") != "seeded_review_required":
            raise SeedError("Child is not in an authorized seed state.")
        return {
            "ok": True, "seed_id": seed_id, "owner_user_id": child["owner_user_id"],
            "license_id": child["license_id"], "plan": child.get("plan"),
            "offline_until": child["offline_until"],
            "offline_authorized": int((now or datetime.now(timezone.utc)).timestamp()) <= child["offline_until"],
            "execution_enabled": False,
        }
