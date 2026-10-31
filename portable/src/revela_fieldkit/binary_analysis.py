"""Read-only executable-format triage. Never maps or executes inspected files."""
from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

from .cli import safe_regular_file, sha256_file

_PE_MACHINES = {
    0x014C: "x86",
    0x8664: "x86-64",
    0x01C0: "ARM",
    0x01C4: "ARMv7",
    0xAA64: "ARM64",
    0x0200: "IA64",
}
_ELF_MACHINES = {
    3: "x86",
    40: "ARM",
    62: "x86-64",
    183: "AArch64",
    243: "RISC-V",
}
_MACHO_CPUS = {
    7: "x86",
    0x01000007: "x86-64",
    12: "ARM",
    0x0100000C: "ARM64",
    18: "PowerPC",
    0x01000012: "PowerPC64",
}

def _read_at(path: Path, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or length > 1024 * 1024:
        raise ValueError("Invalid or oversized header read.")
    with path.open("rb") as stream:
        stream.seek(offset)
        return stream.read(length)

def _inspect_elf(path: Path, size: int) -> dict[str, Any]:
    header = _read_at(path, 0, 64)
    if len(header) < 52 or header[:4] != b"\x7fELF":
        return {"format": "ELF", "status": "truncated_header"}
    elf_class, data_encoding = header[4], header[5]
    if elf_class not in {1, 2} or data_encoding not in {1, 2}:
        return {"format": "ELF", "status": "unsupported_class_or_endianness"}
    endian = "<" if data_encoding == 1 else ">"
    if elf_class == 2:
        if len(header) < 64:
            return {"format": "ELF", "status": "truncated_64_bit_header"}
        values = struct.unpack_from(endian + "HHIQQQIHHHHHH", header, 16)
        entry = values[3]
        section_offset = values[5]
        section_count = values[11]
        machine = values[1]
        elf_type = values[0]
        bits = 64
    else:
        values = struct.unpack_from(endian + "HHIIIIIHHHHHH", header, 16)
        entry = values[3]
        section_offset = values[5]
        section_count = values[11]
        machine = values[1]
        elf_type = values[0]
        bits = 32
    return {
        "format": "ELF",
        "status": "header_parsed",
        "architecture": _ELF_MACHINES.get(machine, f"unknown machine {machine}"),
        "class_bits": bits,
        "endianness": "little" if data_encoding == 1 else "big",
        "object_type": {1: "relocatable", 2: "executable", 3: "shared_object", 4: "core_dump"}.get(elf_type, f"type_{elf_type}"),
        "entry_point": hex(entry),
        "section_header_offset": section_offset,
        "section_count": section_count,
        "file_size_bytes": size,
        "note": "Header metadata only; section tables, symbols and code have not been fully parsed.",
    }

def _inspect_pe(path: Path, size: int) -> dict[str, Any]:
    dos = _read_at(path, 0, 64)
    if len(dos) < 64 or dos[:2] != b"MZ":
        return {"format": "PE", "status": "invalid_dos_header"}
    pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
    if pe_offset < 64 or pe_offset > min(size - 24, 16 * 1024 * 1024):
        return {"format": "PE", "status": "invalid_pe_header_offset"}
    header = _read_at(path, pe_offset, 24)
    if len(header) < 24 or header[:4] != b"PE\x00\x00":
        return {"format": "PE", "status": "missing_pe_signature"}
    machine, section_count, timestamp, _symbol_ptr, _symbol_count, optional_size, characteristics = struct.unpack_from("<HHIIIHH", header, 4)
    if section_count > 96 or optional_size > 4096:
        return {"format": "PE", "status": "header_limits_exceeded"}
    optional = _read_at(path, pe_offset + 24, optional_size)
    if len(optional) < 2:
        return {"format": "PE", "status": "truncated_optional_header"}
    magic = struct.unpack_from("<H", optional, 0)[0]
    if magic == 0x10B and len(optional) >= 32:
        pe_kind = "PE32"
        image_base = struct.unpack_from("<I", optional, 28)[0]
    elif magic == 0x20B and len(optional) >= 32:
        pe_kind = "PE32+"
        image_base = struct.unpack_from("<Q", optional, 24)[0]
    else:
        pe_kind = "unknown_optional_header"
        image_base = None
    entry_point = struct.unpack_from("<I", optional, 16)[0] if len(optional) >= 20 else None
    section_table_offset = pe_offset + 24 + optional_size
    section_bytes = _read_at(path, section_table_offset, section_count * 40)
    sections = []
    for index in range(min(section_count, len(section_bytes) // 40)):
        offset = index * 40
        raw_name = section_bytes[offset:offset + 8].split(b"\x00", 1)[0]
        name = raw_name.decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", section_bytes, offset + 8)
        sections.append({
            "name": name,
            "virtual_size": virtual_size,
            "virtual_address": hex(virtual_address),
            "raw_size": raw_size,
            "raw_offset": raw_pointer,
        })
    return {
        "format": "PE",
        "status": "header_parsed",
        "architecture": _PE_MACHINES.get(machine, f"unknown machine 0x{machine:04x}"),
        "pe_kind": pe_kind,
        "entry_point_rva": hex(entry_point) if entry_point is not None else None,
        "image_base": hex(image_base) if image_base is not None else None,
        "coff_timestamp_unix": timestamp,
        "characteristics": hex(characteristics),
        "section_count_declared": section_count,
        "sections_parsed": len(sections),
        "sections": sections,
        "file_size_bytes": size,
        "note": "Header metadata only; imports, resources, signatures and code have not been fully parsed.",
    }

def _inspect_macho(path: Path, size: int) -> dict[str, Any]:
    header = _read_at(path, 0, 32)
    variants = {
        b"\xfe\xed\xfa\xce": (">", 28, 32),
        b"\xce\xfa\xed\xfe": ("<", 28, 32),
        b"\xfe\xed\xfa\xcf": (">", 32, 64),
        b"\xcf\xfa\xed\xfe": ("<", 32, 64),
    }
    variant = variants.get(header[:4])
    if not variant:
        return {"format": "Mach-O", "status": "unknown_magic_or_fat_binary"}
    endian, needed, bits = variant
    if len(header) < needed:
        return {"format": "Mach-O", "status": "truncated_header"}
    cpu_type, _subtype, file_type, command_count, command_bytes, flags = struct.unpack_from(endian + "iiIIII", header, 4)
    return {
        "format": "Mach-O",
        "status": "header_parsed",
        "architecture": _MACHO_CPUS.get(cpu_type, f"unknown cpu {cpu_type}"),
        "class_bits": bits,
        "file_type": file_type,
        "load_command_count": command_count,
        "load_command_bytes": command_bytes,
        "flags": hex(flags),
        "file_size_bytes": size,
        "note": "Thin Mach-O header only. Universal/fat binaries require a separate slice-table parser.",
    }

def _inspect_apk(path: Path, size: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return {"format": "ZIP/APK", "status": "invalid_or_unsupported_archive"}
    if len(infos) > 20000:
        return {"format": "ZIP/APK", "status": "archive_entry_limit_exceeded", "entry_count": len(infos)}
    names = [item.filename.replace("\\", "/") for item in infos]
    normalized = [name.lstrip("/") for name in names]
    dex_files = [name for name in normalized if name.startswith("classes") and name.endswith(".dex")]
    native_libraries = [name for name in normalized if name.startswith("lib/") and name.endswith(".so")]
    manifest_present = "AndroidManifest.xml" in normalized
    apk_detected = manifest_present and bool(dex_files)
    if not apk_detected:
        return {
            "format": "ZIP",
            "status": "zip_archive_not_confirmed_as_apk",
            "entry_count": len(infos),
            "file_size_bytes": size,
        }
    return {
        "format": "Android APK",
        "status": "package_structure_parsed",
        "manifest_present": manifest_present,
        "dex_count": len(dex_files),
        "dex_files": dex_files[:20],
        "native_library_count": len(native_libraries),
        "native_libraries": native_libraries[:40],
        "entry_count": len(infos),
        "compressed_total_bytes": sum(item.compress_size for item in infos),
        "uncompressed_total_bytes": sum(item.file_size for item in infos),
        "note": "Package listing only. No files were extracted and no Android binary XML, signatures, permissions or code paths were decoded.",
    }

def inspect_binary(path: Path, full_hash: bool = False) -> dict[str, Any]:
    """Read format headers and archive directory metadata. Never executes or extracts content."""
    info = safe_regular_file(path)
    header = _read_at(path, 0, 64)
    if header.startswith(b"\x7fELF"):
        result = _inspect_elf(path, info.st_size)
    elif header.startswith(b"MZ"):
        result = _inspect_pe(path, info.st_size)
    elif header[:4] in {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"}:
        result = _inspect_macho(path, info.st_size)
    elif header.startswith(b"\x00asm"):
        version = struct.unpack_from("<I", header, 4)[0] if len(header) >= 8 else None
        result = {"format": "WebAssembly", "status": "header_parsed" if version is not None else "truncated_header", "version": version}
    elif header.startswith(b"PK\x03\x04") or path.suffix.lower() == ".apk":
        result = _inspect_apk(path, info.st_size)
    else:
        result = {"format": "unknown", "status": "unsupported_or_unrecognized_header"}
    result["path"] = str(path.resolve())
    result["file_size_bytes"] = info.st_size
    if full_hash:
        digest, _size, stable = sha256_file(path)
        result["sha256"] = digest
        result["stable_during_hash"] = stable
    result["execution_performed"] = False
    return result
