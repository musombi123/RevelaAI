"""Python-native RVX source artifact packager.

This module encrypts source bytes; it is not a replacement Go/Python compiler.
Before compiling/birthing a tool, a valid signed RevelaCode license is required.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from rvx.crypto import RecipeError, load_master_key, open_blob, seal_blob


class RvxCompiler:
    def __init__(self, master_key_path: str | Path | None = None) -> None:
        self.master_key_path = Path(master_key_path).expanduser() if master_key_path else None
        self._root_key = load_master_key(self.master_key_path)

    def seal_file(self, source: str | Path, output: str | Path | None = None) -> Path:
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        destination = Path(output).expanduser() if output else Path(str(source_path) + ".rvx")
        destination.parent.mkdir(parents=True, exist_ok=True)
        encrypted = seal_blob(
            source_path.read_bytes(),
            self._root_key,
            metadata={"source_name": source_path.name, "format": "opaque-source-artifact"},
        )
        destination.write_bytes(encrypted)
        return destination

    def open_file(self, source: str | Path, output: str | Path | None = None) -> Path:
        source_path = Path(source).expanduser()
        destination = Path(output).expanduser() if output else (
            Path(str(source_path)[:-4]) if str(source_path).endswith(".rvx")
            else source_path.with_suffix(source_path.suffix + ".opened")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(open_blob(source_path.read_bytes(), self._root_key))
        return destination

    def compile_file(
        self, source: str | Path, output: str | Path | None = None, *,
        license_key: str | None = None, tool_id: str | None = None,
    ) -> Path:
        """Seal a tool artifact only after validating a signed entitlement."""
        from core_billing.licensing import verify_license_token

        claims = verify_license_token(license_key or "", tool_id=tool_id)
        if not claims.get("sub") or claims.get("type") != "platform_license":
            raise RecipeError("Need RevelaCode Provider + Valid License to birth tool.")
        destination = Path(output).expanduser() if output else Path(str(Path(source).expanduser()) + ".rvx")
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        encrypted = seal_blob(
            source_path.read_bytes(),
            self._root_key,
            metadata={
                "source_name": source_path.name,
                "tool_id": tool_id or source_path.stem,
                "license_id": claims.get("jti"),
                "license_plan": claims.get("plan"),
            },
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encrypted)
        return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="RevelaCode RVX authenticated-encryption packager")
    parser.add_argument("--master-key", default=None, help="Path to the 4096-bit owner recipe key")
    parser.add_argument("--file", required=True, help="Source file to seal/open")
    parser.add_argument("--output", default=None, help="Destination path")
    parser.add_argument("--open", action="store_true", help="Decrypt an RVX1 file")
    parser.add_argument("--seal-only", action="store_true", help="Seal a non-tool artifact without a license")
    parser.add_argument("--license-key", default=None, help="Signed RevelaCode tool license")
    parser.add_argument("--tool-id", default=None, help="Tool id bound to the license")
    args = parser.parse_args()
    compiler = RvxCompiler(args.master_key)
    result = (
        compiler.open_file(args.file, args.output) if args.open
        else compiler.seal_file(args.file, args.output) if args.seal_only
        else compiler.compile_file(args.file, args.output, license_key=args.license_key, tool_id=args.tool_id)
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
