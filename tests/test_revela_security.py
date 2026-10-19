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


from core_auditor.ledger import AuditLedger, AuditLedgerError
from core_foundry.factory.foundry_builder import FactoryBuildError, FoundryBuilder
from core_seed.seed_runner import SeedError, SeedRunner


def test_foundry_manifest_is_hash_checked_and_requires_review(tmp_path):
    builder = FoundryBuilder(tmp_path / "factories")
    proposal = builder.build_plan(
        owner_user_id="owner-1",
        name="Factory Sample",
        description="A deterministic sample factory proposal for acceptance tests.",
        requirements=["Inspect input", "Validate output"],
        country="KE",
        language="sw",
        industry="manufacturing",
        adapters=["csv", "scale-reader"],
    )
    assert proposal["status"] == "await_merge"
    manifest = builder.get_manifest(proposal["build_id"])
    assert manifest["execution_policy"]["generated_code_execution"] is False
    assert manifest["manifest_sha256"] == proposal["manifest_sha256"]
    approved = builder.set_status(proposal["build_id"], "approved")
    assert approved["status"] == "approved"
    assert builder.get_manifest(proposal["build_id"])["status"] == "approved"

    path = tmp_path / "factories" / proposal["build_id"] / "manifest.json"
    tampered = path.read_text(encoding="utf-8").replace("Inspect input", "Skip input")
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(FactoryBuildError, match="integrity"):
        builder.get_manifest(proposal["build_id"])


def test_seed_child_is_offline_verifiable_and_tamper_evident(tmp_path, monkeypatch):
    _keypair(monkeypatch)
    builder = FoundryBuilder(tmp_path / "factories")
    proposal = builder.build_plan(
        owner_user_id="offline-owner",
        name="Offline Factory",
        description="A safe declarative factory for an offline acceptance test.",
        requirements=["Read local file", "Validate local record"],
    )
    token, claims = create_license_token(user_id="offline-owner", plan_id="pro", country="KE")
    with pytest.raises(SeedError, match="human review"):
        SeedRunner(tmp_path / "seeded", builder).seed_child(
            build_id=proposal["build_id"], license_key=token,
            user_id="offline-owner", child_name="Child A"
        )
    builder.set_status(proposal["build_id"], "approved")
    runner = SeedRunner(tmp_path / "seeded", builder)
    child = runner.seed_child(
        build_id=proposal["build_id"], license_key=token,
        user_id="offline-owner", child_name="Child A"
    )
    checked = runner.verify_child_offline(child["seed_id"])
    assert checked["ok"] is True
    assert checked["offline_authorized"] is True
    child_path = Path(child["path"])
    assert child_path.stat().st_mode & 0o077 == 0
    child_json = child_path.read_text(encoding="utf-8").replace("Child A", "Child B")
    child_path.write_text(child_json, encoding="utf-8")
    with pytest.raises(SeedError, match="integrity"):
        runner.verify_child_offline(child["seed_id"])


def test_audit_ledger_detects_record_tampering(tmp_path):
    ledger = AuditLedger(tmp_path / "audit" / "events.jsonl")
    first = ledger.append(actor_user_id="user-1", action="factory.build", object_id="fab_a",
                          detail={"manifest_sha256": "ab" * 32})
    second = ledger.append(actor_user_id="user-1", action="factory.review", object_id="fab_a",
                           detail={"approved": True})
    result = ledger.verify()
    assert result["ok"] is True
    assert result["records"] == 2
    assert result["head_hash"] == second["record_hash"]

    file_path = tmp_path / "audit" / "events.jsonl"
    lines = file_path.read_text(encoding="utf-8").splitlines()
    first_record = __import__("json").loads(lines[0])
    first_record["action"] = "factory.destroy"
    lines[0] = __import__("json").dumps(first_record, sort_keys=True, separators=(",", ":"))
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditLedgerError):
        ledger.verify()
