"""Generate a separate Ed25519 factory-review signing pair."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_review_keypair(output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path = directory / "review_private.pem"
    public_path = directory / "review_public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("Refusing to overwrite existing review signing keys.")
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
    for path, data, mode in ((private_path, private_bytes, 0o600), (public_path, public_bytes, 0o644)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    return private_path, public_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate factory review attestation keys")
    parser.add_argument("--output-dir", default="~/.revelaai/review-keys")
    args = parser.parse_args()
    private_path, public_path = generate_review_keypair(args.output_dir)
    print(f"Private review signing key (secret-manager input): {private_path}")
    print(f"Public review verification key (owner/local CLI): {public_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
