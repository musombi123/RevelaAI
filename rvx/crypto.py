"""Authenticated RVX envelopes.

RVX blobs use AES-256-GCM with a stable, context-derived key so owner-held
artifacts remain decryptable across days. Mesh packets use a UTC-day key and
are rejected after the UTC dialect day changes. The dialect label is metadata;
confidentiality and integrity come from AES-GCM, not keyword obfuscation.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT_KEY_BYTES = 512  # 4096 bits of random root-key material.
_BLOB_AAD = b"REVELA-RVX-BLOB-V1"
_PACKET_PREFIX = "RVXP1."


class RecipeError(RuntimeError):
    """The owner-held recipe is missing, invalid, or cannot decrypt this data."""


class StalePacketError(RecipeError):
    """A mesh packet was created in a different UTC dialect day."""


def default_master_key_path() -> Path:
    configured = os.getenv("REVELA_MASTER_KEY_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".revela_recipe" / "master.key"


def load_master_key(path: str | Path | None = None) -> bytes:
    key_path = Path(path).expanduser() if path else default_master_key_path()
    try:
        key = key_path.read_bytes()
    except OSError as exc:
        raise RecipeError(
            f"Need RevelaCode Brain: owner recipe key not found at {key_path}. "
            "Generate it locally with python -m recipe.cli init."
        ) from exc
    if len(key) != ROOT_KEY_BYTES:
        raise RecipeError(
            f"Invalid master key length at {key_path}; expected {ROOT_KEY_BYTES} random bytes."
        )
    return key


def _derive_key(root: bytes, *, salt: bytes, info: bytes) -> bytes:
    if len(root) < 32:
        raise RecipeError("Key material is too short.")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(root)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + ("=" * (-len(text) % 4)))


def seal_blob(plaintext: bytes, root_key: bytes, *, metadata: dict[str, Any] | None = None) -> bytes:
    """Encrypt bytes as an RVX blob. Metadata is visible and must not contain secrets."""
    key = _derive_key(root_key, salt=b"revela-rvx-blob-v1", info=b"artifact-encryption")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _BLOB_AAD)
    envelope = {
        "version": 1,
        "kind": "blob",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
        "metadata": metadata or {},
    }
    return b"RVX1." + _b64e(json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()).encode()


def open_blob(blob: bytes, root_key: bytes) -> bytes:
    """Decrypt an authenticated RVX blob; any tampering fails closed."""
    if not blob.startswith(b"RVX1."):
        raise RecipeError("Not an RVX1 blob.")
    try:
        envelope = json.loads(_b64d(blob[5:].decode("ascii")))
        if envelope.get("version") != 1 or envelope.get("kind") != "blob":
            raise ValueError("unsupported envelope")
        nonce = _b64d(envelope["nonce"])
        ciphertext = _b64d(envelope["ciphertext"])
        if len(nonce) != 12:
            raise ValueError("invalid nonce")
        key = _derive_key(root_key, salt=b"revela-rvx-blob-v1", info=b"artifact-encryption")
        return AESGCM(key).decrypt(nonce, ciphertext, _BLOB_AAD)
    except RecipeError:
        raise
    except Exception as exc:
        raise RecipeError("RVX blob authentication/decryption failed; wrong recipe or damaged data.") from exc


def _mesh_secret() -> bytes:
    configured = os.getenv("REVELA_RVX_MESH_SECRET", "").strip()
    if configured:
        if configured.startswith("base64:"):
            try:
                raw = base64.b64decode(configured[7:], validate=True)
            except Exception as exc:
                raise RecipeError("REVELA_RVX_MESH_SECRET has invalid base64.") from exc
        else:
            raw = configured.encode("utf-8")
        if len(raw) < 32:
            raise RecipeError("REVELA_RVX_MESH_SECRET must contain at least 32 bytes.")
        return raw
    # Local-owner mode only. Hosted services should use a separately provisioned
    # mesh secret instead of copying the offline root recipe into cloud runtime.
    return load_master_key()


def seal_packet(payload: Any, *, route: str, secret: bytes | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """Create an encrypted daily RVX mesh packet bound to its intended route."""
    if not route or len(route) > 160:
        raise ValueError("route must be a non-empty route identifier")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    root = secret if secret is not None else _mesh_secret()
    key = _derive_key(root, salt=day.encode(), info=("revela-rvx-mesh-v1:" + route).encode())
    nonce = secrets.token_bytes(12)
    aad = ("REVELA-RVXP1|" + route + "|" + day).encode()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ciphertext = AESGCM(key).encrypt(nonce, raw, aad)
    return {
        "protocol": "RVXP1",
        "dialect": "v" + day.replace("-", ".") + "_α",
        "day": day,
        "route": route,
        "nonce": _b64e(nonce),
        "body": _b64e(ciphertext),
    }


def open_packet(envelope: dict[str, Any], *, route: str, secret: bytes | None = None,
                now: datetime | None = None) -> Any:
    """Decrypt only same-day packets addressed to the exact route."""
    if not isinstance(envelope, dict) or envelope.get("protocol") != "RVXP1":
        raise RecipeError("Unsupported RVX mesh packet.")
    if envelope.get("route") != route:
        raise RecipeError("RVX mesh route binding mismatch.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    day = envelope.get("day")
    if day != today:
        raise StalePacketError("Stale RVX packet: its UTC dialect has expired.")
    root = secret if secret is not None else _mesh_secret()
    try:
        key = _derive_key(root, salt=day.encode(), info=("revela-rvx-mesh-v1:" + route).encode())
        aad = ("REVELA-RVXP1|" + route + "|" + day).encode()
        plaintext = AESGCM(key).decrypt(_b64d(envelope["nonce"]), _b64d(envelope["body"]), aad)
        return json.loads(plaintext)
    except StalePacketError:
        raise
    except Exception as exc:
        raise RecipeError("RVX packet authentication/decryption failed.") from exc
