"""Regression tests for the USECT-UNCOPYABLE trust boundaries."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from core_billing.keys import generate_keypair
from core_billing.licensing import create_license_token, verify_license_token
from core_uncopyable.dna_vault_guard import (
    DnaVaultError,
    restore_dna_vault,
    sign_dna_vault,
    sign_tool_watermark,
    verify_tool_watermark,
)
from core_uncopyable.hardware_bind import compare_hardware_binding, hardware_fingerprint
from core_uncopyable.license_lock import EntitlementError, require_entitlement
from core_uncopyable.recipe_lock import RecipeLockError, verify_recipe
from core_uncopyable.rvx_evolver import evolve_dialect, verify_dialect
from rvx.crypto import StalePacketError, open_packet, seal_packet


def configure_keys(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    private_path, public_path = generate_keypair(tmp_path / "issuer")
    monkeypatch.setenv("REVELA_LICENSE_PRIVATE_KEY_PATH", str(private_path))
    monkeypatch.setenv("REVELA_LICENSE_PUBLIC_KEY_PATH", str(public_path))
    monkeypatch.delenv("REVELA_LICENSE_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("REVELA_LICENSE_PUBLIC_KEY", raising=False)
    return private_path, public_path


def test_recipe_lock_requires_owner_key_and_checks_pinned_digest(tmp_path, monkeypatch):
    key_path = tmp_path / "recipe" / "master.key"
    monkeypatch.setenv("REVELA_MASTER_KEY_PATH", str(key_path))
    with pytest.raises(RecipeLockError, match="Need RevelaCode Brain"):
        verify_recipe()
    key_path.parent.mkdir()
    key_path.write_bytes(b"k" * 512)
    key_path.chmod(0o600)
    monkeypatch.setenv("REVELA_RECIPE_EXPECTED_SHA256", hashlib.sha256(b"x" * 512).hexdigest())
    with pytest.raises(RecipeLockError, match="fingerprint mismatch"):
        verify_recipe()


def test_enterprise_entitlement_is_signed_and_plan_scoped(tmp_path, monkeypatch):
    configure_keys(tmp_path, monkeypatch)
    local, _ = create_license_token(user_id="user-1", plan_id="local", country="KE")
    with pytest.raises(EntitlementError, match="Enterprise plan required"):
        require_entitlement(local, "factory_build")
    monkeypatch.setenv("REVELA_HARDWARE_ID", "license-bound-test-device")
    fingerprint = hardware_fingerprint()
    enterprise, claims = create_license_token(
        user_id="user-1", plan_id="enterprise", country="KE",
        hardware_fingerprint=fingerprint, factory_ids=["factory-1"],
    )
    assert require_entitlement(enterprise, "factory_build", hardware_fingerprint=fingerprint)["plan"] == "enterprise"
    assert verify_license_token(enterprise, hardware_fingerprint=fingerprint)["sub"] == "user-1"
    with pytest.raises(Exception, match="Hardware fingerprint mismatch"):
        verify_license_token(enterprise, hardware_fingerprint="b" * 64)
    with pytest.raises(Exception, match="does not cover this factory"):
        verify_license_token(enterprise, factory_id="factory-2")
    assert "factory_build" in claims["entitlements"]


def test_hardware_fingerprint_is_stable_and_bound_claims_are_checked(monkeypatch):
    monkeypatch.setenv("REVELA_HARDWARE_ID", "test-device-001")
    first = hardware_fingerprint()
    assert first == hardware_fingerprint()
    assert compare_hardware_binding({"hardware_fingerprint": first}, current=first)
    assert not compare_hardware_binding({"hardware_fingerprint": "f" * 64}, current=first)


def test_dialect_is_encrypted_authenticated_and_date_scoped(tmp_path, monkeypatch):
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"r" * 512)
    key_path.chmod(0o600)
    monkeypatch.setenv("REVELA_MASTER_KEY_PATH", str(key_path))
    output = tmp_path / "dialect.json"
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("REVELA_DIALECT_PATH", str(output))
    result = evolve_dialect(output_path=output, now=now, reason="test")
    assert result["artifact_sha256"]
    assert output.read_bytes().startswith(b"RVX1.")
    assert verify_dialect(output, now=now)["valid"] is True
    packet = seal_packet({"action": "test"}, route="marketplace.search", secret=b"m" * 32,
                         now=datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc))
    evolve_dialect(output_path=output, now=datetime(2026, 10, 20, 12, 32, tzinfo=timezone.utc),
                   reason="twin_detected")
    with pytest.raises(StalePacketError, match="Dialect obsolete"):
        open_packet(packet, route="marketplace.search", secret=b"m" * 32,
                    now=datetime(2026, 10, 20, 12, 33, tzinfo=timezone.utc))
    old = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    assert verify_dialect(output, now=old)["reason"] == "Dialect obsolete - Pull new"


def test_watermark_is_signed_and_missing_or_tampered_tool_is_not_genuine(tmp_path, monkeypatch):
    configure_keys(tmp_path, monkeypatch)
    monkeypatch.setenv("REVELA_WATERMARK_STORE", str(tmp_path / "watermarks"))
    signed = sign_tool_watermark(
        tool_id="factory-123", creator_user_id="creator-1",
        factory_id="factory-123", artifact_sha256="a" * 64,
    )
    assert verify_tool_watermark("factory-123")["valid"] is True
    assert verify_tool_watermark("not-signed")["message"] == "Not genuine RevelaCode"
    file_path = next((tmp_path / "watermarks").glob("*.json"))
    document = json.loads(file_path.read_text())
    document["creator_user_id"] = "attacker"
    file_path.write_text(json.dumps(document))
    assert verify_tool_watermark("factory-123")["valid"] is False


def test_dna_restore_requires_master_key_and_fresh_founder_signature(tmp_path, monkeypatch):
    private_path, _ = configure_keys(tmp_path, monkeypatch)
    master_path = tmp_path / "master.key"
    master_path.write_bytes(b"d" * 512)
    master_path.chmod(0o600)
    monkeypatch.setenv("REVELA_MASTER_KEY_PATH", str(master_path))
    payload = {"schema_version": 1, "records": [{"id": "core-one", "digest": "a" * 64}]}
    encrypted = sign_dna_vault(payload)
    issued_at = datetime.now(timezone.utc).isoformat()
    signature_payload = {
        "action": "restore_dna",
        "vault_sha256": hashlib.sha256(encrypted).hexdigest(),
        "issued_at": issued_at,
        "nonce": "n" * 32,
    }
    private_key = load_pem_private_key(private_path.read_bytes(), password=None)
    signature = base64.urlsafe_b64encode(
        private_key.sign(json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode())
    ).decode().rstrip("=")
    destination = tmp_path / "restored" / "vault.json"
    result = restore_dna_vault(
        encrypted, signature_payload=signature_payload, signature_b64=signature,
        destination=destination,
    )
    assert result["restored"] is True
    assert json.loads(destination.read_text()) == payload
    invalid_payload = {**signature_payload, "nonce": "x" * 32}
    with pytest.raises(DnaVaultError, match="signature is invalid"):
        restore_dna_vault(
            encrypted, signature_payload=invalid_payload,
            signature_b64=base64.urlsafe_b64encode(b"x" * 64).decode().rstrip("="),
            destination=destination,
        )
