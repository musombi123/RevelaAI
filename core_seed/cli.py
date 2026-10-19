"""Verify a seeded child's signed offline lease without network access."""
from __future__ import annotations

import argparse
import json

from core_seed.seed_runner import SeedError, SeedRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline verification for a RevelaCode seeded child")
    parser.add_argument("--seed-id", required=True)
    parser.add_argument("--root", default=None, help="Seed directory; defaults to REVELA_SEED_ROOT")
    args = parser.parse_args()
    try:
        result = SeedRunner(output_root=args.root).verify_child_offline(args.seed_id)
    except SeedError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
