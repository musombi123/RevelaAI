"""Ed25519 review attestations for offline factory approval.

Review keys are separate from the offline RVX root key and license signing keys.
The manifest checksum is for integrity; this attestation provides authenticity.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from core_foundry.factory.foundry_builder import FactoryBuildError, FoundryBuilder


class AttestationError(RuntimeError):
    """An approval signature is absent or invalid, or signing is not configured."""


def _pem(env_name: str, path_env_name: str) -> bytes | None:
    value = os.getenv(env_name, "").strip()
    if value:
        if value.startswith("base64:"):
            try:
                return base64.b64decode(value[7:], validate=True)
            except Exception as exc:
                raise AttestationError(f"{env_name} is invalid base64.") from exc
        return value.replace("\\n", "\n").encode()
    path = os.getenv(path_env_name, "").strip()
    if path:
        try:
            return Path(path).expanduser().read_bytes()
        except OSError as exc:
            raise AttestationError(f"Could not read {path_env_name}.") from exc
    return None


def _private_key() -> Ed25519PrivateKey:
    raw = _pem("REVELA_REVIEW_PRIVATE_KEY", "REVELA_REVIEW_PRIVATE_KEY_PATH")
    if not raw:
        raise AttestationError("Factory review signing key is not configured.")
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except Exception as exc:
        raise AttestationError("Invalid factory review private key.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise AttestationError("Factory review key must be Ed25519.")
    return key


def _public_key() -> Ed25519PublicKey:
    raw = _pem("REVELA_REVIEW_PUBLIC_KEY", "REVELA_REVIEW_PUBLIC_KEY_PATH")
    if not raw:
        raise AttestationError("Factory review verification key is not configured.")
    try:
        key = serialization.load_pem_public_key(raw)
    except Exception as exc:
        raise AttestationError("Invalid factory review public key.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise AttestationError("Factory review key must be Ed25519.")
    return key


def _signed_message(build_id: str, manifest_sha256: str, reviewer_id: str) -> bytes:
    return ("REVELA-FOUNDRY-APPROVAL-V1|" + build_id + "|" + manifest_sha256 + "|" + reviewer_id).encode()


def sign_approved_manifest(manifest: dict[str, Any], reviewer_id: str) -> dict[str, Any]:
    verified = FoundryBuilder.validate_manifest(manifest)
    if verified.get("status") != "approved":
        raise AttestationError("Only an approved manifest can receive a review attestation.")
    if not reviewer_id.strip():
        raise AttestationError("Reviewer identity is required.")
    # Never preserve an attestation when re-signing a changed manifest.
    verified.pop("review_attestation", None)
    signature = _private_key().sign(
        _signed_message(verified["build_id"], verified["manifest_sha256"], reviewer_id)
    )
    verified["review_attestation"] = {
        "version": 1,
        "algorithm": "EdDSA",
        "reviewer_user_id": reviewer_id[:160],
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }
    return verified


def verify_approval_attestation(manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        verified = FoundryBuilder.validate_manifest(manifest)
    except FactoryBuildError as exc:
        raise AttestationError("Factory manifest integrity check failed.") from exc
    if verified.get("status") != "approved":
        raise AttestationError("Factory manifest has not been approved.")
    attestation = verified.get("review_attestation")
    if not isinstance(attestation, dict) or attestation.get("version") != 1 or attestation.get("algorithm") != "EdDSA":
        raise AttestationError("Factory approval attestation is missing or unsupported.")
    reviewer = attestation.get("reviewer_user_id")
    signature_text = attestation.get("signature")
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(signature_text, str):
        raise AttestationError("Factory approval attestation fields are invalid.")
    try:
        signature = base64.urlsafe_b64decode(signature_text + ("=" * (-len(signature_text) % 4)))
        _public_key().verify(
            signature,
            _signed_message(verified["build_id"], verified["manifest_sha256"], reviewer),
        )
    except AttestationError:
        raise
    except Exception as exc:
        raise AttestationError("Factory approval signature verification failed.") from exc
    return verified
