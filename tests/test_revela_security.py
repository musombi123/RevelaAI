from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core_billing.licensing import LicenseError, create_license_token, verify_license_token
from recipe.cli import initialize_key
from rvx.compiler import RvxCompiler
from rvx.crypto import RecipeError, StalePacketError, open_blob, open_packet, seal_blob, seal_packet
from rvx.dialect import create_dialect


def _keypair(monkeypatch):
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setenv("REVELA_LICENSE_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("REVELA_LICENSE_PUBLIC_KEY", public_pem)
    return private


def test_owner_key_is_random_4096_bit_material_and_never_overwritten(tmp_path):
    path = initialize_key(tmp_path / "revela_recipe" / "master.key")
    assert len(path.read_bytes()) == 512
    with pytest.raises(FileExistsError):
        initialize_key(path)


def test_rvx_blob_round_trip_and_tamper_detection():
    root = b"r" * 512
    cleartext = b"factory source should not be visible in the RVX envelope"
    blob = seal_blob(cleartext, root, metadata={"source_name": "factory.py"})
    assert blob.startswith(b"RVX1.")
    assert cleartext not in blob
    assert open_blob(blob, root) == cleartext
    changed = bytearray(blob)
    position = len(changed) // 2
    changed[position] = ord("A") if changed[position] != ord("A") else ord("B")
    with pytest.raises(RecipeError):
        open_blob(bytes(changed), root)
    with pytest.raises(RecipeError):
        open_blob(blob, b"x" * 512)


def test_mesh_packets_are_route_bound_and_expire_at_utc_day_change():
    secret = b"m" * 48
    created = datetime(2026, 10, 18, 23, 59, tzinfo=timezone.utc)
    packet = seal_packet({"action": "heal", "id": "sample"}, route="zero.heal",
                         secret=secret, now=created)
    assert "action" not in str(packet)
    assert open_packet(packet, route="zero.heal", secret=secret, now=created)["action"] == "heal"
    with pytest.raises(RecipeError):
        open_packet(packet, route="one.genesis", secret=secret, now=created)
    with pytest.raises(StalePacketError):
        open_packet(packet, route="zero.heal", secret=secret,
                    now=created + timedelta(minutes=2))


def test_daily_dialect_changes_and_is_keyed():
    root = b"z" * 512
    first = create_dialect(root, "2026-10-18")
    second = create_dialect(root, "2026-10-19")
    wrong_key = create_dialect(b"q" * 512, "2026-10-19")
    assert first["keywords"] != second["keywords"]
    assert second["keywords"] != wrong_key["keywords"]


def test_signed_license_is_validated_and_bounded_offline(monkeypatch):
    private = _keypair(monkeypatch)
    token, claims = create_license_token(user_id="user-42", plan_id="pro", country="KE")
    verified = verify_license_token(token)
    assert verified["sub"] == "user-42"
    assert verified["max_tools"] == 100
    assert verified["offline_until"] <= verified["exp"]

    expired_offline = dict(claims)
    expired_offline["offline_until"] = int((datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp())
    expired_token = jwt.encode(expired_offline, private, algorithm="EdDSA")
    with pytest.raises(LicenseError, match="Offline license window"):
        verify_license_token(expired_token)


def test_tool_compilation_requires_license_and_uses_owner_recipe(tmp_path, monkeypatch):
    _keypair(monkeypatch)
    master_key = tmp_path / "master.key"
    master_key.write_bytes(b"k" * 512)
    source = tmp_path / "factory.py"
    source.write_text("def build():\n    return 'reviewed'\n", encoding="utf-8")
    compiler = RvxCompiler(master_key)
    with pytest.raises(LicenseError):
        compiler.compile_file(source, license_key="")
    license_key, _ = create_license_token(user_id="owner-1", plan_id="pro", country="KE")
    artifact = compiler.compile_file(source, license_key=license_key, tool_id="factory-demo")
    assert artifact.read_bytes().startswith(b"RVX1.")
    restored = compiler.open_file(artifact, tmp_path / "restored.py")
    assert restored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
