# RevelaAI Portable Field Kit

**Version:** 0.2.0  
**Purpose:** USB-carried, local-first utilities for evidence triage, case documentation, file inspection, source-secret review and offline reference search.

This is the local companion to the RevelaAI AI repository. It deliberately uses only the Python standard library. It does not install third-party tools, upload evidence, execute inspected files, acquire physical disks, perform network scans or make changes to source evidence.

## What works offline

| Tool | Command | Function |
|---|---|---|
| Case workspace | python -m revela_fieldkit case create ... | Create case metadata, evidence and report folders, and a custody log. |
| Evidence inventory | python -m revela_fieldkit inventory ... | Hash regular files with SHA-256 and save an integrity manifest. |
| Integrity verification | python -m revela_fieldkit verify ... | Re-hash source files and compare them to the saved manifest. |
| Custody log verification | python -m revela_fieldkit custody verify ... | Verify the event hash chain; tampered logs are not silently appended. |
| Binary analysis | python -m revela_fieldkit binary inspect FILE | Read PE/ELF/Mach-O/WebAssembly headers and APK package layout without executing or extracting files. |
| File inspection | python -m revela_fieldkit inspect FILE --hash | Report file metadata, a small magic-byte signature set, sample entropy and optional SHA-256. |
| Source secret audit | python -m revela_fieldkit secrets scan PATH | Detect selected credential patterns and redact values in output. |
| Tool discovery | python -m revela_fieldkit doctor | Check whether specialist applications are already installed. |
| Offline notes | python -m revela_fieldkit knowledge search TERMS | Search bundled reference notes without internet. |
| Case report | python -m revela_fieldkit report --case CASE_DIR | Generate a Markdown report from local case records. |

### Optional offline AI

Run:
python -m revela_fieldkit ask --model gemma4:e2b --question "Explain the evidence handling steps"

This sends a prompt and local reference notes to an Ollama server bound to 127.0.0.1, localhost or ::1 only. Remote hosts are rejected. An Ollama installation and the selected model must already be present on the computer or stored on the USB. The model is not included in this source repository.

Ollama's local generate API is documented at https://docs.ollama.com/api/generate. Ollama documents a local Gemma 4 E2B model download of about 7.2 GB and recommends 8 GB available VRAM/unified memory; actual performance depends on hardware and context length. See https://docs.ollama.com/quickstart.

To prepare local AI, install Ollama on a compatible Windows/Linux host, open one terminal on the USB and run Start-LocalAI.ps1 (Windows), then use a second terminal to run prepare-local-model.ps1. After the model is downloaded into the USB model folder, the ask command can use it without an internet connection. The Ollama engine itself must be installed on the host; it is not yet shipped as a fully self-contained executable in this bundle.

## USB layout

Copy the portable/ directory to the USB drive. The Windows runtime preparation script can place the official Python embeddable distribution under runtimes/python-win-x64/. Linux currently uses a local Python 3.10+ installation; a standalone Linux runtime can be added as a separate platform-specific bundle.

Recommended drive: 32 GB minimum for tools and case work; 64 GB or larger if you plan to store a local model. Format the drive as exFAT or NTFS rather than FAT32 when using multi-gigabyte model files. Keep client evidence on an encrypted, access-controlled volume. Avoid storing sensitive cases on a shared USB drive. The Windows launcher changes its working directory to the USB, so default case folders are created on the drive.

## Prepare Windows

Open PowerShell from the portable/ directory and run:

    Set-ExecutionPolicy -Scope Process Bypass
    .\prepare-windows-runtime.ps1
    .\Start-RevelaAI.ps1

The preparation script downloads the official Python 3.14.10 Windows x64 embeddable ZIP from python.org and extracts it into the USB runtime directory. It verifies the archive SHA-256 against the checksum published on the official Python release page. The embedded runtime is isolated and does not include pip; the Field Kit has no third-party Python dependencies.

Or run Start-RevelaAI.cmd from File Explorer. This starts the local utility menu; it does not launch Ollama automatically.

## Linux

    cd /path/to/USB/portable
    chmod +x start-linux.sh
    ./start-linux.sh

Requires Python 3.10 or newer. No pip install is required.

## First use

    python -m revela_fieldkit case create --root cases --id CASE-001 --title "Training evidence triage"
    python -m revela_fieldkit inventory --case cases/CASE-001 --source ./sample-data
    python -m revela_fieldkit verify --case cases/CASE-001
    python -m revela_fieldkit inspect ./sample-data/example.bin --hash
    python -m revela_fieldkit binary inspect ./sample-data/program.exe --hash
    python -m revela_fieldkit custody verify --case cases/CASE-001
    python -m revela_fieldkit secrets scan ./my-repository
    python -m revela_fieldkit doctor
    python -m revela_fieldkit knowledge search "deleted files timeline"
    python -m revela_fieldkit report --case cases/CASE-001

Inventory reads and hashes source files; it does not modify them. A single-file source and a directory source are both supported. The custody log links each event with SHA-256; this detects accidental or partial record edits but is not a digital signature or protection against an attacker who can rewrite the entire case folder.

## Specialist tools are separate components

Ghidra, GNU ddrescue, The Sleuth Kit, Autopsy, TestDisk/PhotoRec, Volatility 3, Wireshark, Zeek, JADX, APKTool, MobSF, Semgrep, Trivy and OSV-Scanner are not copied into this repository. They are separate upstream projects with their own licensing, platform requirements, update schedules and installation processes. The doctor command checks whether they are available. Verify each upstream download and its hash before placing approved binaries in a tools folder.

## Critical limitations

- Inventory hashing is not a forensic image and does not replace a hardware write blocker or a qualified acquisition.
- Do not use a failing drive as a practice target. Physical damage needs specialist equipment and handling.
- Hash equality verifies byte integrity between observations; it does not prove file authenticity or ownership.
- Entropy and magic bytes are triage hints, not malware detection or file validation.
- Secret scanning is pattern-based and incomplete; output is redacted to reduce accidental disclosure.
- Offline AI can hallucinate. Treat it as an assistant, never as a forensic examiner or an authority for legal, medical or safety decisions.
- Live vulnerability assessment must be separately scoped and authorized. This kit contains no arbitrary-target scanner.
- Do not put evidence, credentials, tokens, private keys or customer data in a public repository or unapproved AI service.

The cloud RevelaAI services, Core Mesh and connected provider models remain online services. This USB edition provides an offline utility layer and optional local-model interface; it is not yet a complete offline clone of all cloud platform services.
