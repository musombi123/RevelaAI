"""Founder-signed tool provenance and safe DNA Vault restoration."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from core_billing.licensing import LicenseError, load_private_key, load_public_key
from rvx.crypto import RecipeError, load_master_key, open_blob, seal_blob


class DnaVaultError(RuntimeError):
    """A provenance watermark or restore authorization failed."""


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _watermark_dir() -> Path:
    return Path(os.getenv("REVELA_WATERMARK_STORE", ".revela/watermarks")).expanduser()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_tool_watermark(
    *,
    tool_id: str,
    creator_user_id: str,
    factory_id: str,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    if not tool_id.strip() or not creator_user_id.strip() or not factory_id.strip():
        raise DnaVaultError("tool_id, creator_user_id and factory_id are required.")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "issuer": "RevelaCode",
        "tool_id": tool_id,
        "creator_user_id": creator_user_id,
        "factory_id": factory_id,
        "artifact_sha256": artifact_sha256,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "Ed25519",
        "key_id": "revelacode-founder-v1",
    }
    try:
        signature = load_private_key().sign(canonical_json(payload))
    except LicenseError as exc:
        raise DnaVaultError("Founder watermark signing key is not configured.") from exc
    document = {**payload, "signature": _b64(signature)}
    target = _watermark_dir() / f"{hashlib.sha256(tool_id.encode()).hexdigest()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(canonical_json(document))
    temporary.replace(target)
    return document


def verify_tool_watermark(tool_id: str) -> dict[str, Any]:
    target = _watermark_dir() / f"{hashlib.sha256(tool_id.encode()).hexdigest()}.json"
    if not target.is_file():
        return {"valid": False, "tool_id": tool_id, "message": "Not genuine RevelaCode"}
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
        signature = _unb64(str(document.pop("signature")))
        if document.get("tool_id") != tool_id or document.get("issuer") != "RevelaCode":
            raise DnaVaultError("Watermark identity mismatch.")
        load_public_key().verify(signature, canonical_json(document))
        return {"valid": True, **document, "signature": _b64(signature), "message": "Genuine RevelaCode provenance"}
    except (OSError, ValueError, KeyError, TypeError, InvalidSignature, LicenseError, json.JSONDecodeError, DnaVaultError):
        return {"valid": False, "tool_id": tool_id, "message": "Not genuine RevelaCode"}


def sign_dna_vault(payload: dict[str, Any], *, master_key_path: str | Path | None = None) -> bytes:
    """Encrypt a JSON DNA snapshot; founder signature is required separately at restore."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
        raise DnaVaultError("DNA snapshot must contain schema_version=1 and a records list.")
    root = load_master_key(master_key_path)
    return seal_blob(canonical_json(payload), root, metadata={"type": "revela-dna-vault", "schema_version": 1})


def restore_dna_vault(
    encrypted_blob: bytes,
    *,
    signature_payload: dict[str, Any],
    signature_b64: str,
    destination: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Restore only authenticated encrypted JSON after validating a fresh founder signature."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    digest = hashlib.sha256(encrypted_blob).hexdigest()
    expected = {
        "action": "restore_dna",
        "vault_sha256": digest,
        "issued_at": signature_payload.get("issued_at"),
        "nonce": signature_payload.get("nonce"),
    }
    if signature_payload != expected:
        raise DnaVaultError("Restore signature payload does not match the vault digest or required fields.")
    try:
        issued = datetime.fromisoformat(str(expected["issued_at"]).replace("Z", "+00:00"))
        if issued.tzinfo is None or abs(moment.astimezone(timezone.utc) - issued.astimezone(timezone.utc)) > timedelta(minutes=5):
            raise DnaVaultError("Founder restore signature is outside the five-minute authorization window.")
        nonce = str(expected["nonce"] or "")
        if len(nonce) < 24 or len(nonce) > 200:
            raise DnaVaultError("Restore nonce is invalid.")
        signature = _unb64(signature_b64)
        load_public_key().verify(signature, canonical_json(signature_payload))
    except (ValueError, TypeError, InvalidSignature, LicenseError) as exc:
        raise DnaVaultError("Founder restore signature is invalid.") from exc
    root = load_master_key()
    try:
        document = json.loads(open_blob(encrypted_blob, root))
    except (RecipeError, json.JSONDecodeError) as exc:
        raise DnaVaultError("DNA Vault blob failed recipe authentication.") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("records"), list):
        raise DnaVaultError("DNA Vault payload schema is invalid.")
    target = Path(destination or os.getenv("REVELA_DNA_VAULT_PATH", ".revela/dna_vault.json")).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + secrets.token_hex(6) + ".tmp")
    temporary.write_bytes(canonical_json(document))
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(target)
    return {"restored": True, "path": str(target), "records": len(document["records"]), "vault_sha256": digest}
