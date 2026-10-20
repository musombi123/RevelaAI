"""Local owner command for RVX artifacts.

This launcher does not make existing plaintext source disappear from Git.
Repository source-to-blob migration is a separate, reviewable operation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from rvx.compiler import RvxCompiler
from rvx.crypto import RecipeError, default_master_key_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="revela", description="RevelaCode owner recipe CLI")
    parser.add_argument("--recipe", action="store_true", help="Require the owner-held local recipe")
    parser.add_argument("--compile", action="store_true", help="Decrypt and validate RVX blobs into a local build workspace")
    parser.add_argument("--master-key", default=None)
    parser.add_argument("--license-key", default=None, help="Signed plan license required for licensed tool compilation")
    parser.add_argument("--file", default=None, help="Seal one source file into a licensed .rvx artifact")
    parser.add_argument("--factory-build-id", default=None, help="Compile an approved Foundry proposal into a licensed RVX artifact")
    parser.add_argument("--root", default=".", help="Root to scan for .rvx files")
    parser.add_argument("--output-dir", default=".revela-build", help="Destination for decrypted local workspace")
    args = parser.parse_args()

    if not args.recipe:
        parser.error("--recipe is required")
    compiler = RvxCompiler(args.master_key or default_master_key_path())
    if args.file and args.factory_build_id:
        parser.error("Use either --file or --factory-build-id, not both")
    if args.file:
        if not args.compile:
            parser.error("--file requires --compile")
        if not args.license_key:
            raise RecipeError("Need valid license to birth tool; pass --license-key.")
        output = compiler.compile_file(args.file, license_key=args.license_key)
        print(output)
        return 0
    if args.factory_build_id:
        if not args.compile:
            parser.error("--factory-build-id requires --compile")
        if not args.license_key:
            raise RecipeError("Need valid license to birth tool; pass --license-key.")
        from core_foundry.factory.foundry_builder import FactoryBuildError, FoundryBuilder
        builder = FoundryBuilder()
        try:
            manifest = builder.get_manifest(args.factory_build_id)
        except FactoryBuildError as exc:
            raise RecipeError(str(exc)) from exc
        if manifest.get("status") != "approved":
            raise RecipeError("Factory must be approved by a reviewer before compilation.")
        from core_foundry.attestation import AttestationError, verify_approval_attestation
        try:
            manifest = verify_approval_attestation(manifest)
        except AttestationError as exc:
            raise RecipeError("Need a valid signed factory-review attestation before compiling.") from exc
        source_path = builder.output_root / args.factory_build_id / "manifest.json"
        output_path = Path(args.output).expanduser() if args.output else source_path.parent / "factory.rvx"
        output = compiler.compile_file(
            source_path, output_path, license_key=args.license_key, tool_id=args.factory_build_id
        )
        print(output)
        return 0
    if not args.compile:
        parser.error("Use --compile to process RVX files")
    if not args.license_key:
        raise RecipeError("Need valid license to compile RVX artifacts; pass --license-key.")
    from core_billing.licensing import verify_license_token
    verify_license_token(args.license_key)
    root = Path(args.root).resolve()
    blobs = sorted(root.rglob("*.rvx"))
    if not blobs:
        raise RecipeError("No .rvx blobs found. Existing Go/Python source has not been migrated to RVX.")
    destination_root = Path(args.output_dir).resolve()
    for blob in blobs:
        relative = blob.relative_to(root)
        relative_text = str(relative)
        if relative_text.endswith(".rvx"):
            relative_text = relative_text[:-4]
        destination = destination_root / relative_text
        compiler.open_file(blob, destination)
    print(f"Decrypted {len(blobs)} RVX artifact(s) into {destination_root}. Build/test the materialized source separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
