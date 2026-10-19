"""Generate today's RVX keyword labels.

The mapping is not a secure compiler or security boundary. It is encrypted with
the recipe key to prevent accidental disclosure of private dialect metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from rvx.crypto import load_master_key, seal_blob

KEYWORDS = ("func", "struct", "call", "return", "import", "class", "def", "async", "await", "interface")
ALPHABET = "αβγδεζηθικλμνξοπρστυφχψω"


def create_dialect(root_key: bytes, day: str | None = None) -> dict[str, object]:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mapping: dict[str, str] = {}
    for word in KEYWORDS:
        digest = hmac.new(root_key, f"{day}:{word}".encode(), hashlib.sha256).digest()
        a, b, c = digest[0] % len(ALPHABET), digest[1] % len(ALPHABET), digest[2] % len(ALPHABET)
        mapping[word] = f"k{ALPHABET[a]}{ALPHABET[b]}_{ALPHABET[c]}{digest[3]:02x}"
    return {"version": 1, "day": day, "dialect": "v" + day.replace("-", ".") + "_α", "keywords": mapping}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an encrypted, date-scoped RVX keyword map")
    parser.add_argument("--master-key", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--day", default=None, help="UTC day YYYY-MM-DD (defaults to today)")
    args = parser.parse_args()
    root = load_master_key(args.master_key)
    dialect = create_dialect(root, args.day)
    destination = Path(args.output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(seal_blob(json.dumps(dialect, sort_keys=True).encode(), root,
                                      metadata={"type": "dialect", "day": dialect["day"]}))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
