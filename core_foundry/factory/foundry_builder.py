"""Build auditable factory plans without executing generated or submitted code.

The initial Foundry emits deterministic, reviewable manifests and workflow plans.
Hardware actuation, arbitrary Python execution, firmware flashing and production
deployment are intentionally not performed by this builder.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class FactoryBuildError(ValueError):
    """Factory demand is invalid, unsafe, or cannot be stored."""


BLOCKED = (
    "ransomware", "credential theft", "steal passwords", "keylogger",
    "malware deployment", "explosive device", "weaponized", "spyware",
)
_ALLOWED_STEP_TYPES = {"inspect", "transform", "validate", "notify", "human_approval", "export"}


def factory_root() -> Path:
    return Path(os.getenv("REVELA_FACTORY_ROOT", str(Path.home() / ".revelaai" / "factories"))).expanduser()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    if not slug:
        raise FactoryBuildError("A stable factory/tool identifier is required.")
    return slug[:64]


def _safe_text(value: str, label: str, maximum: int) -> str:
    value = value.strip()
    if not value or len(value) > maximum:
        raise FactoryBuildError(f"{label} must be between 1 and {maximum} characters.")
    lowered = value.casefold()
    if any(term in lowered for term in BLOCKED):
        raise FactoryBuildError(f"{label} was blocked by the initial deterministic safety screen.")
    return value


class FoundryBuilder:
    """Plan factory automation from bounded declarations and reusable adapters."""

    def __init__(self, output_root: str | Path | None = None) -> None:
        self.output_root = Path(output_root).expanduser() if output_root else factory_root()
        self.output_root.mkdir(parents=True, exist_ok=True)

    def build_plan(
        self,
        *,
        owner_user_id: str,
        name: str,
        description: str,
        requirements: Iterable[str],
        country: str = "KE",
        language: str = "en",
        industry: str = "general",
        adapters: Iterable[str] = (),
        source_tool_id: str | None = None,
    ) -> dict[str, Any]:
        if not owner_user_id.strip():
            raise FactoryBuildError("An authenticated owner is required.")
        name = _safe_text(name, "name", 140)
        description = _safe_text(description, "description", 3000)
        country = country.upper().strip()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise FactoryBuildError("country must be a two-letter ISO country code.")
        lang = language.lower().strip()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", lang):
            raise FactoryBuildError("language must be a short language code such as en, de or sw.")
        industry = _slug(industry)[:80]
        normalized_requirements = []
        seen = set()
        for raw in requirements:
            item = _safe_text(str(raw), "requirement", 300)
            key = item.casefold()
            if key not in seen:
                normalized_requirements.append(item)
                seen.add(key)
            if len(normalized_requirements) >= 50:
                break
        if not normalized_requirements:
            raise FactoryBuildError("At least one bounded requirement is required.")
        normalized_adapters = sorted({_slug(str(adapter)) for adapter in adapters if str(adapter).strip()})
        if len(normalized_adapters) > 25:
            raise FactoryBuildError("At most 25 adapter identifiers are allowed.")
        build_id = "fab_" + secrets.token_hex(12)
        now = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "build_id": build_id,
            "status": "await_merge",
            "created_at": now,
            "owner_user_id": owner_user_id,
            "factory": {
                "name": name,
                "description": description,
                "industry": industry,
                "country_origin": country,
                "language": lang,
                "source_tool_id": source_tool_id,
            },
            "requirements": normalized_requirements,
            "adapters_requested": normalized_adapters,
            "steps": [
                {"id": "inspect-input", "type": "inspect", "approval_required": False},
                {"id": "transform", "type": "transform", "approval_required": False},
                {"id": "validate-output", "type": "validate", "approval_required": False},
                {"id": "human-release-gate", "type": "human_approval", "approval_required": True},
                {"id": "export-package", "type": "export", "approval_required": True},
            ],
            "execution_policy": {
                "generated_code_execution": False,
                "hardware_actuation": False,
                "external_network_required_for_plan": False,
                "production_deployment": False,
                "human_review_required": True,
            },
            "unresolved": [
                "Validate domain-specific requirements and selected adapters.",
                "Run sandboxed tests against customer-supplied acceptance cases.",
                "Complete guardian, compliance and hardware review where applicable.",
                "Approve, sign and publish the factory before production use.",
            ],
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
        output_dir = self.output_root / build_id
        output_dir.mkdir(parents=True, exist_ok=False)
        target = output_dir / "manifest.json"
        temporary = output_dir / ".manifest.tmp"
        try:
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return {
            "build_id": build_id,
            "status": "await_merge",
            "manifest_sha256": manifest["manifest_sha256"],
            "manifest_path": str(target),
            "manifest": manifest,
        }

    def get_manifest(self, build_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"fab_[a-f0-9]{24}", build_id):
            raise FactoryBuildError("Invalid factory build identifier.")
        target = (self.output_root / build_id / "manifest.json").resolve()
        if self.output_root.resolve() not in target.parents:
            raise FactoryBuildError("Requested manifest path is outside the factory root.")
        try:
            manifest = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FactoryBuildError("Factory build not found.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise FactoryBuildError("Factory manifest is unreadable.") from exc
        claimed_hash = manifest.pop("manifest_sha256", None)
        actual_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest["manifest_sha256"] = claimed_hash
        if not isinstance(claimed_hash, str) or not hmac_compare(claimed_hash, actual_hash):
            raise FactoryBuildError("Factory manifest integrity check failed.")
        return manifest


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left, right)
