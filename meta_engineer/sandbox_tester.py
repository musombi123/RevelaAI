"""Bounded static tests for generated proposals; candidate code is never executed."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 10
MEMORY_LIMIT_MB = 150


def _memory_mb(pid: int) -> float:
    """Measure pytest RSS; psutil is a required dependency for this module."""
    import psutil
    process = psutil.Process(pid)
    total = process.memory_info().rss
    for child in process.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            continue
    return total / (1024 * 1024)


def test_feature(feature_path: str | Path, code: str | None = None) -> dict[str, Any]:
    """Run four static-contract tests under a ten-second, 150MB process budget.

    Candidate source is treated as text and is never imported or executed.
    A pass is a static review gate, not proof of production correctness.
    """
    path = Path(feature_path)
    if code is None:
        try:
            code = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"passed": False, "logs": "Cannot read proposal: " + str(exc), "coverage": 0.0}

    test_source = """import ast
from pathlib import Path
candidate = Path('candidate.txt').read_text(encoding='utf-8')
def test_source_nonempty():
    assert candidate.strip()
def test_source_syntax_or_typescript_shape():
    try:
        ast.parse(candidate)
    except SyntaxError:
        assert 'export ' in candidate or 'interface ' in candidate
def test_review_boundary_present():
    assert 'AUTO-GENERATED' in candidate
    assert 'approval' in candidate.lower() or 'proposed' in candidate.lower()
def test_no_obvious_destructive_operation():
    lowered = candidate.lower()
    assert 'shutil.rmtree(' not in lowered
    assert 'os.remove(' not in lowered
    assert 'subprocess.run(' not in lowered
"""
    with tempfile.TemporaryDirectory(prefix="revelaai-meta-test-") as temp:
        folder = Path(temp)
        (folder / "candidate.txt").write_text(code, encoding="utf-8")
        stem = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in path.stem)[:64]
        test_file = folder / ("test_" + (stem or "feature") + "_autogen.py")
        test_file.write_text(test_source, encoding="utf-8")
        started = time.monotonic()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-m", "pytest", "-q", str(test_file)],
                cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=env,
            )
        except OSError as exc:
            return {"passed": False, "logs": "Could not start pytest: " + str(exc), "coverage": 0.0}

        peak = 0.0
        timeout_hit = False
        memory_hit = False
        monitor_error = None
        while process.poll() is None:
            try:
                peak = max(peak, _memory_mb(process.pid))
            except Exception as exc:
                monitor_error = "Sandbox memory monitoring failed: " + type(exc).__name__
                process.kill()
                break
            if peak > MEMORY_LIMIT_MB:
                memory_hit = True
                process.kill()
                break
            if time.monotonic() - started > TIMEOUT_SECONDS:
                timeout_hit = True
                process.kill()
                break
            time.sleep(0.05)

        try:
            output, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        logs = (output or "") + "\nObserved peak process memory MB: %.1f" % peak
        if timeout_hit:
            logs += "\nKILL SWITCH: sandbox exceeded 10 seconds"
        if memory_hit:
            logs += "\nKILL SWITCH: sandbox exceeded 150 MB"
        if monitor_error:
            logs += "\nKILL SWITCH: " + monitor_error
        passed = process.returncode == 0 and not timeout_hit and not memory_hit and not monitor_error
        return {
            "passed": bool(passed), "logs": logs, "coverage": 0.0,
            "coverage_note": "Runtime coverage is not measured because candidate code is not executed.",
            "tests_expected": 4, "timeout_seconds": TIMEOUT_SECONDS,
            "memory_limit_mb": MEMORY_LIMIT_MB, "peak_memory_mb": round(peak, 2),
        }
