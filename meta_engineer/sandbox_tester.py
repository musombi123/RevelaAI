"""Bounded static tests for generated proposals; candidate code is never imported or executed."""
from __future__ import annotations
import os, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any

def _memory_mb(pid: int) -> float:
    try:
        import psutil
        proc = psutil.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try: total += child.memory_info().rss
            except Exception: pass
        return total / (1024 * 1024)
    except Exception:
        return 0.0

def test_feature(feature_path: str | Path, code: str | None = None) -> dict[str, Any]:
    """Run four trusted static-contract tests with a 10s / 150MB process budget."""
    path = Path(feature_path)
    if code is None:
        try: code = path.read_text(encoding="utf-8")
        except OSError as exc: return {"passed": False, "logs": "Cannot read proposal: " + str(exc), "coverage": 0.0}
    test_source = """import ast
from pathlib import Path
candidate = Path('candidate.txt').read_text(encoding='utf-8')
def test_source_nonempty():
    assert candidate.strip()
def test_source_syntax_or_typescript_shape():
    try: ast.parse(candidate)
    except SyntaxError: assert 'export ' in candidate or 'interface ' in candidate
def test_review_boundary_present():
    assert 'AUTO-GENERATED' in candidate and ('approval' in candidate.lower() or 'proposed' in candidate.lower())
def test_no_obvious_destructive_operation():
    lowered = candidate.lower()
    assert 'shutil.rmtree(' not in lowered and 'os.remove(' not in lowered and 'subprocess.run(' not in lowered
"""
    with tempfile.TemporaryDirectory(prefix="revelaai-meta-test-") as temp:
        folder = Path(temp)
        (folder / "candidate.txt").write_text(code, encoding="utf-8")
        test_file = folder / "test_feature_autogen.py"
        test_file.write_text(test_source, encoding="utf-8")
        start = time.monotonic()
        try:
            proc = subprocess.Popen([sys.executable, "-I", "-m", "pytest", "-q", str(test_file)],
                cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        except OSError as exc:
            return {"passed": False, "logs": "Could not start pytest: " + str(exc), "coverage": 0.0}
        peak, timeout_hit, memory_hit = 0.0, False, False
        while proc.poll() is None:
            peak = max(peak, _memory_mb(proc.pid))
            if peak > 150: memory_hit = True; proc.kill(); break
            if time.monotonic() - start > 10: timeout_hit = True; proc.kill(); break
            time.sleep(0.05)
        try: output, _ = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired: proc.kill(); output, _ = proc.communicate()
        logs = (output or "") + "\nObserved peak memory MB: %.1f" % peak
        if timeout_hit: logs += "\nKILL SWITCH: sandbox exceeded 10 seconds"
        if memory_hit: logs += "\nKILL SWITCH: sandbox exceeded 150 MB"
        passed = proc.returncode == 0 and not timeout_hit and not memory_hit
        return {"passed": passed, "logs": logs, "coverage": 0.0,
                "coverage_note": "Coverage instrumentation is not installed; 0.0 means unmeasured.",
                "tests_expected": 4, "timeout_seconds": 10, "memory_limit_mb": 150}
