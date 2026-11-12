"""Command entry point for repository audits and guarded source repairs."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .repair import apply_repair_plan, rollback_repair
from .workspace_audit import audit_workspace, export_handoff_findings, mounted_drives


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="revela-fieldkit",
        description="RevelaAI local-first workspace diagnostics and human-gated repair tools.",
    )
    parser.add_argument("--version", action="version", version="RevelaAI Workspace Auditor 0.3.0")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("drives", help="List candidate mounted volumes without reading their contents.")

    audit = commands.add_parser("audit", help="Discover repositories and run bounded static diagnostics.")
    audit.add_argument("--root", type=Path, required=True, help="Explicit local repository, folder or mounted volume.")
    audit.add_argument("--out", type=Path, help="Write the full JSON report to a new file.")
    audit.add_argument("--findings-dir", type=Path, help="Export individual findings in the existing Meta Engineer hand-off schema.")
    audit.add_argument("--exclude-hidden", action="store_true", help="Skip hidden directories/files.")
    audit.add_argument("--npm-audit", action="store_true", help="Explicitly allow npm audit to use the network.")
    audit.add_argument("--fail-on", choices=("critical", "high", "medium", "low", "informational"),
                       help="Return exit code 1 if any finding meets this severity or a higher severity.")
    audit.add_argument("--authorized", action="store_true", help="Confirm that you own or are authorized to inspect this path.")

    repair = commands.add_parser("repair", help="Apply or roll back a reviewable text-only repair transaction.")
    repair_sub = repair.add_subparsers(dest="repair_action", required=True)
    apply = repair_sub.add_parser("apply", help="Apply a hash-guarded JSON repair plan.")
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--backup-dir", type=Path, help="External backup directory (default: user profile).")
    apply.add_argument("--authorized", action="store_true", help="Confirm ownership or written authorization.")
    apply.add_argument("--approve", action="store_true", help="Explicitly approve every change in this plan.")

    rollback = repair_sub.add_parser("rollback", help="Restore a prior repair transaction when files have not changed since.")
    rollback.add_argument("--transaction", type=Path, required=True)
    rollback.add_argument("--authorized", action="store_true", help="Confirm ownership or written authorization.")
    rollback.add_argument("--approve", action="store_true", help="Explicitly approve rollback of this transaction.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "drives":
            _emit(mounted_drives())
            return 0
        if args.command == "audit":
            if not args.authorized:
                raise ValueError("Read-only repository audit still requires --authorized for the selected path.")
            result = audit_workspace(
                args.root,
                include_hidden=not args.exclude_hidden,
                npm_audit=args.npm_audit,
            )
            if args.out:
                target = args.out.expanduser()
                if target.exists() or target.is_symlink():
                    raise ValueError(f"Report output already exists; refusing to overwrite: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                result["report_file"] = str(target.resolve())
            if args.findings_dir:
                result["handoff_export"] = export_handoff_findings(result, args.findings_dir)
            _emit(result)
            if args.fail_on:
                from .workspace_audit import SEVERITY_RANK
                threshold = SEVERITY_RANK[args.fail_on]
                if any(SEVERITY_RANK[row["severity"]] <= threshold for row in result["findings"]):
                    return 1
            return 0
        if args.command == "repair" and args.repair_action == "apply":
            result = apply_repair_plan(
                args.root, args.plan, args.backup_dir,
                authorized=args.authorized, approved=args.approve,
            )
            _emit(result)
            return 0
        if args.command == "repair" and args.repair_action == "rollback":
            _emit(rollback_repair(
                args.transaction, authorized=args.authorized, approved=args.approve,
            ))
            return 0
        parser.error("Unsupported command.")
    except (OSError, ValueError) as exc:
        _emit({"status": "error", "message": str(exc)})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
