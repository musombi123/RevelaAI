"""Optional Python bridge to the deterministic USECT-ZERO Go CLI.

This bridge does not call a model or the network. It invokes the local CLI
without a shell, limits runtime and captured output, and parses scan evidence
as a JSON object.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, BinaryIO


_MAX_TIMEOUT_SECONDS = 300.0
_DEFAULT_TIMEOUT_SECONDS = 20.0

# Scan evidence can include repository manifests, so allow substantial output
# while still preventing unbounded memory consumption.
_MAX_STDOUT_BYTES = 64 * 1024 * 1024
_MAX_STDERR_BYTES = 1 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_PIPE_JOIN_TIMEOUT_SECONDS = 5.0

# Environment needed for executable discovery, common OS runtime behavior,
# temporary directories, and optional USECT-ZERO data-directory configuration.
# Administrator tokens and other unneeded environment variables are not passed
# to the scanning subprocess.
_ALLOWED_ENVIRONMENT_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "TZ",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "USECT_ZERO_DATA_DIR",
}


class USECTZeroBridgeError(RuntimeError):
    """Raised when the local USECT-ZERO CLI cannot produce valid scan evidence."""


def _validate_timeout(timeout: int | float) -> float:
    """Validate a finite, positive timeout bounded to five minutes."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise USECTZeroBridgeError("timeout must be a number of seconds")

    value = float(timeout)
    if not math.isfinite(value) or value <= 0 or value > _MAX_TIMEOUT_SECONDS:
        raise USECTZeroBridgeError(
            f"timeout must be greater than 0 and at most "
            f"{int(_MAX_TIMEOUT_SECONDS)} seconds"
        )

    return value


def _resolve_paths(
    repo_root: str | os.PathLike[str],
    binary: str | os.PathLike[str],
) -> tuple[Path, Path]:
    """Resolve the repository and CLI paths before spawning the subprocess."""
    try:
        root = Path(repo_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise USECTZeroBridgeError(
            f"invalid repository root ({type(exc).__name__})"
        ) from exc

    if not root.is_dir():
        raise USECTZeroBridgeError("repository root must be an existing directory")

    try:
        executable = Path(binary).expanduser()
        if not executable.is_absolute():
            executable = root / executable

        # Support the conventional Windows executable suffix when the caller
        # uses the documented suffix-free default path.
        if (
            os.name == "nt"
            and not executable.suffix
            and not executable.is_file()
        ):
            windows_candidate = executable.with_suffix(".exe")
            if windows_candidate.is_file():
                executable = windows_candidate

        executable = executable.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise USECTZeroBridgeError(
            f"could not resolve USECT-ZERO CLI path ({type(exc).__name__})"
        ) from exc

    if not executable.is_file():
        raise USECTZeroBridgeError("USECT-ZERO CLI path is not a regular file")

    return root, executable


def _child_environment(root: Path) -> dict[str, str]:
    """Build a minimal environment for offline scanning."""
    environment: dict[str, str] = {}

    for key, value in os.environ.items():
        if key.upper() in _ALLOWED_ENVIRONMENT_KEYS:
            environment[key] = value

    # The CLI receives the repository root explicitly in both its arguments
    # and environment so the root cannot be inherited accidentally from a
    # parent process configured for a different repository.
    environment["USECT_ZERO_REPO_ROOT"] = str(root)

    # Deliberately do not pass USECT_ZERO_ADMIN_TOKEN or API-key variables.
    return environment


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    """Best-effort termination; another reader may already have killed it."""
    try:
        process.kill()
    except (OSError, ProcessLookupError):
        pass


def _drain_pipe(
    stream: BinaryIO,
    process: subprocess.Popen[bytes],
    limit: int,
    captured: bytearray,
    overflow: threading.Event,
) -> None:
    """Drain a pipe continuously, retaining at most limit bytes."""
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break

            remaining = limit - len(captured)

            if remaining > 0:
                captured.extend(chunk[:remaining])

            if len(chunk) > remaining:
                # Signal the coordinator and terminate the child so output
                # cannot grow without bound or deadlock on a full pipe.
                overflow.set()
                _kill_process(process)

                # Continue draining and discarding until EOF.
                # This lets the pipe close after the child terminates.
    except (OSError, ValueError):
        # Termination may close a pipe while its reader is running.
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _clean_stderr(data: bytes, max_chars: int = 1000) -> str:
    """Create a short, single-line diagnostic suitable for an exception."""
    text = data.decode("utf-8", errors="replace")
    text = " ".join(text.split())
    return text[-max_chars:]


def scan_repository(
    repo_root: str | os.PathLike[str],
    binary: str | os.PathLike[str] = "core-zero/usect-zero",
    timeout: int | float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the local USECT-ZERO CLI in scan mode and return JSON evidence.

    Args:
        repo_root: Existing repository directory to scan.
        binary: Absolute CLI path or a path relative to repo_root.
        timeout: Maximum execution time in seconds, between 0 and 300.

    Returns:
        A decoded JSON object containing scan evidence.

    Raises:
        USECTZeroBridgeError: If the binary is missing, execution times out,
            output exceeds configured limits, execution fails, or evidence
            is not a valid JSON object.
    """
    timeout_seconds = _validate_timeout(timeout)
    root, executable = _resolve_paths(repo_root, binary)

    try:
        process = subprocess.Popen(
            [
                str(executable),
                "-mode",
                "scan",
                "-root",
                str(root),
            ],
            cwd=str(root),
            env=_child_environment(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )
    except (OSError, ValueError) as exc:
        raise USECTZeroBridgeError(
            f"could not start USECT-ZERO CLI ({type(exc).__name__})"
        ) from exc

    # PIPE is guaranteed by the Popen arguments above.
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_capture = bytearray()
    stderr_capture = bytearray()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()

    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(
            process.stdout,
            process,
            _MAX_STDOUT_BYTES,
            stdout_capture,
            stdout_overflow,
        ),
        name="usect-zero-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(
            process.stderr,
            process,
            _MAX_STDERR_BYTES,
            stderr_capture,
            stderr_overflow,
        ),
        name="usect-zero-stderr",
        daemon=True,
    )

    stdout_thread.start()
    stderr_thread.start()

    timed_out = False

    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process(process)

        try:
            return_code = process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            # Unexpected after kill; do not wait indefinitely.
            raise USECTZeroBridgeError(
                "USECT-ZERO CLI did not terminate after timeout cancellation"
            ) from None

    stdout_thread.join(timeout=_PIPE_JOIN_TIMEOUT_SECONDS)
    stderr_thread.join(timeout=_PIPE_JOIN_TIMEOUT_SECONDS)

    if stdout_thread.is_alive() or stderr_thread.is_alive():
        raise USECTZeroBridgeError(
            "USECT-ZERO output streams did not close after process termination"
        )

    if timed_out:
        raise USECTZeroBridgeError(
            f"USECT-ZERO scan timed out after {timeout_seconds:g} seconds"
        )

    if stdout_overflow.is_set():
        raise USECTZeroBridgeError(
            f"scan output exceeded the {_MAX_STDOUT_BYTES}-byte limit"
        )

    if stderr_overflow.is_set():
        raise USECTZeroBridgeError(
            f"scan diagnostics exceeded the {_MAX_STDERR_BYTES}-byte limit"
        )

    if return_code != 0:
        detail = _clean_stderr(bytes(stderr_capture))
        message = f"scan failed with exit code {return_code}"
        if detail:
            message += f": {detail}"
        raise USECTZeroBridgeError(message)

    if not stdout_capture:
        raise USECTZeroBridgeError(
            "Go CLI returned empty scan evidence"
        )

    try:
        stdout_text = bytes(stdout_capture).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise USECTZeroBridgeError(
            "Go CLI returned scan evidence that is not valid UTF-8"
        ) from exc

    try:
        evidence = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise USECTZeroBridgeError(
            "Go CLI returned invalid JSON evidence"
        ) from exc

    if not isinstance(evidence, dict):
        raise USECTZeroBridgeError(
            "Go CLI scan evidence must be a JSON object"
        )

    return evidence
