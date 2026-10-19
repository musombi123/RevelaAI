"""Initialize an owner-held RVX master key outside the repository by default."""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from rvx.crypto import ROOT_KEY_BYTES, default_master_key_path


def initialize_key(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path else default_master_key_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"Refusing to overwrite existing owner key: {target}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secrets.token_bytes(ROOT_KEY_BYTES))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            target.unlink(missing_ok=True)
        finally:
            raise
    try:
        target.chmod(0o600)
        target.parent.chmod(0o700)
    except OSError:
        # Windows ACLs do not implement POSIX mode semantics.
        pass
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="RevelaCode owner recipe tools")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Generate a new 4096-bit local master key")
    init.add_argument("--path", default=None, help="Destination (default: ~/.revela_recipe/master.key)")
    args = parser.parse_args()
    if args.command == "init":
        print(initialize_key(args.path))
        print("BACK UP THIS KEY OFFLINE. It is never printed, uploaded, or committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
