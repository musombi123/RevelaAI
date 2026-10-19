"""Generate a separate Ed25519 license-signing pair. Do not commit the private key."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair(output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path = directory / "license_private.pem"
    public_path = directory / "license_public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("Refusing to overwrite existing license signing keys.")
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    for path, payload, mode in ((private_path, private_bytes, 0o600), (public_path, public_bytes, 0o644)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    return private_path, public_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the separate platform license signing key pair")
    parser.add_argument("--output-dir", default="~/.revelaai/license-keys")
    args = parser.parse_args()
    private_path, public_path = generate_keypair(args.output_dir)
    print(f"Private key (secret-manager input): {private_path}")
    print(f"Public verification key: {public_path}")
    print("Keep the private key out of Git; configure it as REVELA_LICENSE_PRIVATE_KEY_PATH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
