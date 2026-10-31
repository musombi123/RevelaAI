# Reverse Engineering Field Notes

## Static workflow
Preserve the source, hash it, identify format and architecture, record headers/sections/symbols/imports/exports, load it into a disassembler, trace cross-references and control-flow, and compare decompiler output with actual instructions. Decompilation is an approximation, not the original source.

## Relevant executable formats
- PE: Windows executables and DLLs.
- ELF: common Linux and embedded executable/shared-object format.
- Mach-O: macOS and Apple platform executable format.
- DEX/APK: Android bytecode and application package.
- WebAssembly: portable binary instruction format used in compatible runtimes.

## Tools to learn
Ghidra, radare2/Cutter, Capstone, LIEF, YARA, JADX, APKTool, Androguard and Frida. Dynamic instrumentation belongs in a disposable lab and only applies to binaries you own or have permission to assess.

## Analysis record
Record input SHA-256, original source, acquisition time, tool versions, operating system, architecture, analysis steps, observations, hypotheses, confidence, limitations and references.
