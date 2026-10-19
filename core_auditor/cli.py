"""Local audit-chain verification utility."""
from __future__ import annotations

import argparse
import json

from core_auditor.ledger import AuditLedger, AuditLedgerError


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify RevelaCode's local hash-chained audit evidence")
    parser.add_argument("--path", default=None, help="Optional JSONL ledger path")
    args = parser.parse_args()
    try:
        result = AuditLedger(args.path).verify()
    except AuditLedgerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
