"""Generate an RSA key pair for RevelaCode certificate signing.

By default this creates files under ./secrets, which is git-ignored. The script
will not overwrite existing files unless --force is supplied. Move the private
key into the deployment's secret manager; never commit it.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="secrets", help="Directory for PEM outputs (default: secrets)")
    parser.add_argument("--private-name", default="revelacode_certificate_private.pem")
    parser.add_argument("--public-name", default="revelacode_certificate_public.pem")
    parser.add_argument("--bits", type=int, choices=(2048, 3072, 4096), default=3072)
    parser.add_argument("--force", action="store_true", help="Allow replacing existing PEM files")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    private_path = output_dir / args.private_name
    public_path = output_dir / args.public_name
    if private_path.parent != output_dir or public_path.parent != output_dir:
        parser.error("PEM filenames must be simple filenames, not paths.")
    if private_path.exists() or public_path.exists():
        if not args.force:
            parser.error("An output file already exists. Choose another directory or pass --force intentionally.")

    output_dir.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=args.bits)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    try:
        private_path.write_bytes(private_bytes)
        public_path.write_bytes(public_bytes)
        if os.name != "nt":
            os.chmod(private_path, 0o600)
            os.chmod(public_path, 0o644)
    except Exception:
        # If the second write fails, do not leave half of an apparent key pair.
        for path in (private_path, public_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    print(f"Private key: {private_path}")
    print(f"Public key:  {public_path}")
    print("Keep the private key outside source control and store it as a deployment secret.")
    print("Configure REVELACODE_CERTIFICATE_PRIVATE_KEY_PATH and REVELACODE_CERTIFICATE_PUBLIC_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
