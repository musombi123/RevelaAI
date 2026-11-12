"""Deterministic, local-only repository diagnostics for the RevelaAI USB Field Kit."""
from __future__ import annotations
import ast, hashlib, json, os, platform, re, shutil, subprocess, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_SCHEMA = "revelaai.workspace-audit.v1"
HANDOFF_SCHEMA_VERSION = "1.0"
MAX_FILES = 25000
MAX_PROJECTS = 300
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_NODE_CHECKS = 150
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea",
    ".vscode", ".next", ".nuxt", ".svelte-kit", "dist", "build", "coverage",
    ".terraform", "vendor", "target", "Pods", "DerivedData", ".gradle",
    ".cache", "site-packages",
}
PROJECT_MARKERS = {
    ".git", "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
    "poetry.lock", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "Gemfile", "render.yaml", "Dockerfile",
}
SOURCE_EXTENSIONS = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".php": "PHP",
    ".rb": "Ruby", ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++",
    ".hpp": "C++", ".swift": "Swift", ".dart": "Dart", ".vue": "Vue",
    ".svelte": "Svelte", ".html": "HTML", ".css": "CSS", ".sql": "SQL",
    ".sh": "Shell", ".ps1": "PowerShell",
}
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock")
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "api_route", "route"}
LOCAL_IMPORT_RE = re.compile(r"""(?:\bfrom\s+|\bimport\s+|\brequire\s*\(\s*|\bimport\s*\(\s*)["'](\.[^"']+)["']""")
HTML_ASSET_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.I)
RESOURCE_RE = re.compile(r"^\s*-\s*type\s*:\s*([A-Za-z0-9_-]+)\s*$")
RESOURCE_NAME_RE = re.compile(r"^\s*name\s*:\s*[\"']?([A-Za-z0-9_.-]+)")
FROM_SERVICE_RE = re.compile(r"^\s*fromService\s*:\s*$")
SERVICE_REF_RE = re.compile(r"^\s*name\s*:\s*[\"']?([A-Za-z0-9_.-]+)")
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def safe_walk(root: Path, include_hidden: bool = True):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Audit root must be an existing, non-symbolic-link directory.")
    yielded = 0
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name not in IGNORED_DIRS and not (current_path / name).is_symlink()
            and (include_hidden or not name.startswith("."))
        ]
        for name in names:
            path = current_path / name
            if path.is_symlink() or (not include_hidden and name.startswith(".")):
                continue
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            yield path
            yielded += 1
            if yielded >= MAX_FILES:
                raise ValueError(f"Workspace file limit reached ({MAX_FILES}); narrow the selected root.")


def has_project_marker(directory: Path) -> bool:
    try:
        return any((directory / marker).exists() for marker in PROJECT_MARKERS)
    except OSError:
        return False


def discover_projects(root: Path) -> list[Path]:
    root = root.expanduser()
    if root.is_symlink():
        raise ValueError("Audit root cannot be a symbolic link; select its real target explicitly.")
    root = root.resolve(strict=True)
    if root.is_file():
        raise ValueError("Select a directory or mounted volume, not a single file.")
    projects = [root] if has_project_marker(root) else []
    for current, dirs, _names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not (current_path / name).is_symlink()]
        if current_path != root and has_project_marker(current_path):
            projects.append(current_path)
        if len(projects) >= MAX_PROJECTS:
            break
    return sorted(set(projects), key=lambda item: (len(item.parts), str(item).lower())) or [root]


def mounted_drives() -> dict[str, Any]:
    candidates: set[Path] = set()
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if drive.exists():
                candidates.add(drive)
    else:
        for parent in (Path("/media"), Path("/mnt"), Path("/run/media"), Path("/Volumes")):
            if parent.is_dir():
                try:
                    candidates.update(child for child in parent.iterdir() if child.is_dir() and not child.is_symlink())
                except OSError:
                    continue
    rows = []
    for path in sorted(candidates, key=lambda item: str(item).lower()):
        try:
            rows.append({"path": str(path.resolve()), "label": path.name or str(path), "is_directory": path.is_dir()})
        except OSError:
            continue
    return {
        "status": "completed", "platform": platform.platform(),
        "candidate_mounts": rows, "count": len(rows),
        "note": "Mount discovery only. Select an authorized path explicitly before auditing its contents.",
    }


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            return None
        return raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def hash_small_file(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def add_finding(
    findings: list[dict[str, Any]], project: Path, rule_id: str, severity: str,
    category: str, title: str, detail: str, recommendation: str,
    path: Path | None = None, line: int | None = None,
) -> None:
    row: dict[str, Any] = {
        "id": hashlib.sha256(f"{project}:{rule_id}:{path or ''}:{line or 0}:{title}".encode("utf-8")).hexdigest()[:16],
        "rule_id": rule_id, "severity": severity, "category": category,
        "title": title[:240], "detail": detail[:3000], "recommendation": recommendation[:2000],
    }
    if path is not None:
        row["file"] = relative(path, project)
        row["file_sha256"] = hash_small_file(path)
    if line is not None:
        row["line"] = int(line)
    findings.append(row)


def git_status(project: Path) -> dict[str, Any]:
    git = shutil.which("git")
    if not git:
        return {"available": False, "reason": "Git executable is not installed."}
    try:
        head = subprocess.run([git, "-C", str(project), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
        if head.returncode != 0:
            return {"available": False, "reason": "Directory is not a readable Git worktree."}
        branch = subprocess.run([git, "-C", str(project), "branch", "--show-current"], capture_output=True, text=True, timeout=5, check=False)
        status = subprocess.run([git, "-C", str(project), "status", "--porcelain=v1", "--untracked-files=no"], capture_output=True, text=True, timeout=5, check=False)
        return {
            "available": True, "commit": head.stdout.strip()[:64], "branch": branch.stdout.strip()[:160],
            "tracked_worktree_changes": len([line for line in status.stdout.splitlines() if line.strip()]),
            "read_only": True,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "Git metadata command timed out or was unavailable."}


def audit_python(project: Path, files: list[Path], findings: list[dict[str, Any]]) -> int:
    checked = 0
    routes: dict[tuple[str, str], tuple[Path, int]] = {}
    for path in files:
        if path.suffix.lower() not in {".py", ".pyi"}:
            continue
        source = read_text(path)
        if source is None:
            continue
        checked += 1
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            add_finding(findings, project, "PY-SYNTAX", "high", "compile", "Python syntax error",
                        f"{exc.msg} (line {exc.lineno or 0}, column {exc.offset or 0}).",
                        "Correct the syntax error, then rerun the project's test/build pipeline.", path, exc.lineno)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                if method not in ROUTE_METHODS or not decorator.args:
                    continue
                first = decorator.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                methods = [method.upper()]
                for keyword in decorator.keywords:
                    if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                        methods = [str(item.value).upper() for item in keyword.value.elts
                                   if isinstance(item, ast.Constant) and isinstance(item.value, str)] or methods
                for verb in methods:
                    key = (verb, first.value)
                    if key in routes:
                        old_path, old_line = routes[key]
                        add_finding(findings, project, "PY-DUPLICATE-ROUTE", "medium", "routing",
                                    "Duplicate Python HTTP route",
                                    f"{verb} {first.value} is also declared in {relative(old_path, project)}:{old_line}.",
                                    "Review router registration and consolidate or disambiguate duplicate method/path pairs.",
                                    path, getattr(decorator, "lineno", node.lineno))
                    else:
                        routes[key] = (path, getattr(decorator, "lineno", node.lineno))
    return checked


def resolve_local_import(project: Path, source_file: Path, module: str) -> bool:
    base = (source_file.parent / module).resolve()
    candidates = [base]
    candidates.extend(Path(str(base) + suffix) for suffix in
                      (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".css", ".vue", ".svelte"))
    candidates.extend(base / ("index" + suffix) for suffix in (".js", ".jsx", ".mjs", ".ts", ".tsx"))
    for candidate in candidates:
        try:
            candidate.relative_to(project.resolve())
        except ValueError:
            continue
        if candidate.is_file() and not candidate.is_symlink():
            return True
    return False


def audit_javascript(project: Path, files: list[Path], findings: list[dict[str, Any]]) -> dict[str, Any]:
    node = shutil.which("node")
    checked = parse_errors = import_checks = 0
    for path in files:
        suffix = path.suffix.lower()
        if suffix not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
            continue
        source = read_text(path)
        if source is None:
            continue
        for match in LOCAL_IMPORT_RE.finditer(source):
            module = match.group(1)
            import_checks += 1
            if not resolve_local_import(project, path, module):
                line = source.count("\n", 0, match.start()) + 1
                add_finding(findings, project, "JS-MISSING-LOCAL-IMPORT", "medium", "routing",
                            "Unresolved relative module import",
                            f"Relative import {module!r} does not resolve to a file under this project.",
                            "Check the import path, filename casing and build alias configuration.", path, line)
        if node and suffix in {".js", ".mjs", ".cjs"} and checked < MAX_NODE_CHECKS:
            checked += 1
            try:
                result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=8, check=False)
                if result.returncode:
                    parse_errors += 1
                    detail = (result.stderr or result.stdout or "Node parser returned a non-zero exit code.")[-1800:]
                    add_finding(findings, project, "JS-SYNTAX", "high", "compile",
                                "JavaScript syntax check failed", detail.strip(),
                                "Correct the parser error and rerun the repository's configured build/test workflow.", path)
            except (OSError, subprocess.TimeoutExpired):
                add_finding(findings, project, "JS-CHECK-TIMEOUT", "low", "tooling",
                            "JavaScript parser check unavailable",
                            "Node syntax validation could not complete within the bounded check window.",
                            "Run the repository's supported Node.js syntax/build checks locally.", path)
    return {
        "node_available": bool(node), "javascript_files_checked": checked,
        "javascript_parse_errors": parse_errors, "relative_imports_checked": import_checks,
        "note": "Node --check is parser-only for .js/.mjs/.cjs. JSX and TypeScript require their project compiler.",
    }


def audit_html_assets(project: Path, files: list[Path], findings: list[dict[str, Any]]) -> int:
    checked = 0
    for path in files:
        if path.suffix.lower() not in {".html", ".htm"}:
            continue
        source = read_text(path)
        if source is None:
            continue
        for match in HTML_ASSET_RE.finditer(source):
            target = match.group(1).strip()
            if (not target or target.startswith(("#", "/", "//"))
                or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I)
                or "{{" in target or (chr(36) + "{") in target):
                continue
            target_path = (path.parent / target.split("#", 1)[0].split("?", 1)[0]).resolve()
            try:
                target_path.relative_to(project.resolve())
            except ValueError:
                continue
            checked += 1
            if not target_path.exists():
                line = source.count("\n", 0, match.start()) + 1
                add_finding(findings, project, "HTML-MISSING-ASSET", "medium", "routing",
                            "Missing local HTML asset",
                            f"The local href/src target {target!r} does not exist relative to this HTML file.",
                            "Restore the asset or update the link to the correct repository-relative path.", path, line)
    return checked


def audit_render(project: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    path = project / "render.yaml"
    if not path.is_file() or path.is_symlink():
        return {"present": False, "declared_services": [], "service_references": [], "missing_references": []}
    source = read_text(path)
    if source is None:
        add_finding(findings, project, "RENDER-UNREADABLE", "low", "configuration",
                    "Render Blueprint could not be parsed",
                    "render.yaml is not readable UTF-8 text within the audit size limit.",
                    "Review the file locally with a YAML parser before deployment.", path)
        return {"present": True, "declared_services": [], "service_references": [], "missing_references": []}
    declared: set[str] = set()
    references: list[str] = []
    resource_active = False
    pending_indent: int | None = None
    for line in source.splitlines():
        resource = RESOURCE_RE.match(line)
        if resource:
            resource_active = True
            pending_indent = None
            continue
        if pending_indent is not None:
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= pending_indent:
                pending_indent = None
            else:
                ref = SERVICE_REF_RE.match(line)
                if ref:
                    references.append(ref.group(1))
                    pending_indent = None
        if resource_active:
            name = RESOURCE_NAME_RE.match(line)
            if name:
                declared.add(name.group(1))
                resource_active = False
        if FROM_SERVICE_RE.match(line):
            pending_indent = len(line) - len(line.lstrip())
    missing = sorted(set(references) - declared)
    for service in missing:
        add_finding(findings, project, "RENDER-MISSING-SERVICE", "high", "service-binding",
                    "Render fromService reference has no declared service",
                    f"render.yaml references service {service!r}, but no matching service name was found in this Blueprint.",
                    "Correct the service name or add the intended service definition before deploying.", path)
    return {
        "present": True, "declared_services": sorted(declared),
        "service_references": sorted(set(references)), "missing_references": missing,
        "note": "Static name matching only; it does not prove Render runtime health or secret availability.",
    }


def audit_package_json(project: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    path = project / "package.json"
    if not path.is_file() or path.is_symlink():
        return {"present": False, "dependencies": 0, "lockfile": None, "missing_lock_entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        add_finding(findings, project, "NPM-MANIFEST-INVALID", "high", "dependencies",
                    "package.json is invalid JSON", "The package manifest could not be parsed.",
                    "Repair the JSON syntax and validate the package manager's dependency graph.", path)
        return {"present": True, "dependencies": 0, "lockfile": None, "missing_lock_entries": []}
    if not isinstance(data, dict):
        return {"present": True, "dependencies": 0, "lockfile": None, "missing_lock_entries": []}
    declared: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = data.get(key, {})
        if isinstance(values, dict):
            declared.update({str(name): str(version) for name, version in values.items()})
    lock_name = next((name for name in LOCKFILES if (project / name).is_file()), None)
    missing: list[str] = []
    if lock_name and lock_name.endswith(".json"):
        try:
            lock = json.loads((project / lock_name).read_text(encoding="utf-8"))
            packages = lock.get("packages", {}) if isinstance(lock, dict) else {}
            legacy = lock.get("dependencies", {}) if isinstance(lock, dict) else {}
            for name in declared:
                if isinstance(packages, dict) and f"node_modules/{name}" in packages:
                    continue
                if isinstance(legacy, dict) and name in legacy:
                    continue
                missing.append(name)
        except (OSError, json.JSONDecodeError):
            add_finding(findings, project, "NPM-LOCK-INVALID", "high", "dependencies",
                        "npm lockfile is invalid JSON", f"{lock_name} exists but cannot be parsed.",
                        "Regenerate the lockfile using the repository's approved npm version, then review the diff.",
                        project / lock_name)
    if declared and not lock_name:
        add_finding(findings, project, "NPM-LOCK-MISSING", "low", "dependencies",
                    "Package manifest has no recognized lockfile",
                    f"{len(declared)} direct dependencies are declared but no npm, pnpm or yarn lockfile was found.",
                    "Commit the lockfile for the package manager used by this project to improve reproducibility.", path)
    if missing:
        add_finding(findings, project, "NPM-LOCK-DRIFT", "medium", "dependencies",
                    "Direct dependencies are missing from the npm lockfile",
                    "Missing lock entries: " + ", ".join(sorted(missing)[:40]),
                    "Regenerate and inspect the lockfile; packages are never installed automatically.",
                    project / lock_name if lock_name else path)
    license_value = data.get("license") if isinstance(data.get("license"), str) else None
    if license_value and license_value.upper() == "UNLICENSED":
        add_finding(findings, project, "PACKAGE-UNLICENSED", "informational", "licensing",
                    "Package metadata declares UNLICENSED",
                    "package.json explicitly marks this package as unlicensed.",
                    "Confirm intended distribution and license policy with the repository owner.", path)
    elif not license_value and not any((project / name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")):
        add_finding(findings, project, "PACKAGE-LICENSE-MISSING", "low", "licensing",
                    "No package license metadata or root license file found",
                    "The audit did not find package.json license metadata or a common root LICENSE filename.",
                    "Add accurate license metadata after confirming ownership and third-party obligations; legal compliance is not inferred.",
                    path)
    scripts = data.get("scripts", {})
    return {
        "present": True, "name": str(data.get("name") or ""), "version": str(data.get("version") or ""),
        "dependencies": len(declared), "lockfile": lock_name, "missing_lock_entries": sorted(missing),
        "license": license_value, "scripts": sorted(scripts.keys()) if isinstance(scripts, dict) else [],
    }


def audit_python_dependencies(project: Path, files: list[Path]) -> dict[str, Any]:
    manifests = [p for p in files if p.name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile"}]
    declared: set[str] = set()
    parsed = 0
    for path in manifests:
        source = read_text(path)
        if source is None:
            continue
        if path.name.startswith("requirements"):
            for line in source.splitlines():
                value = line.strip()
                if not value or value.startswith(("#", "-")):
                    continue
                match = re.match(r"([A-Za-z0-9_.-]+)", value)
                if match:
                    declared.add(match.group(1).lower().replace("_", "-"))
                    parsed += 1
        elif path.name == "pyproject.toml":
            for match in re.finditer(r"""["']([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(?:[<>=!~].*)?["']""", source):
                declared.add(match.group(1).lower().replace("_", "-"))
                parsed += 1
    return {
        "manifests": [relative(p, project) for p in manifests],
        "declared_dependency_names": sorted(declared), "declared_entries": parsed,
        "resolution_note": "Manifest names only; installed versions and transitive resolution are not guessed.",
    }


def optional_npm_audit(project: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    npm = shutil.which("npm")
    if not npm or not (project / "package.json").is_file():
        return {"requested": True, "status": "skipped", "reason": "npm or package.json is unavailable."}
    try:
        result = subprocess.run([npm, "audit", "--json", "--omit=dev"], cwd=project,
                                capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"requested": True, "status": "unavailable", "reason": "npm audit timed out or could not start."}
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"requested": True, "status": "invalid_response", "exit_code": result.returncode}
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    vulnerabilities = metadata.get("vulnerabilities", {}) if isinstance(metadata, dict) else {}
    counts = {}
    for severity in ("critical", "high", "moderate", "low", "info"):
        value = vulnerabilities.get(severity, 0) if isinstance(vulnerabilities, dict) else 0
        counts[severity] = int(value) if isinstance(value, (int, float)) else 0
    for severity, count in counts.items():
        if count:
            mapped = "medium" if severity == "moderate" else "informational" if severity == "info" else severity
            add_finding(findings, project, f"NPM-AUDIT-{severity.upper()}", mapped, "dependency-advisory",
                        f"npm audit reports {count} {severity} production issue(s)",
                        "The optional online npm audit reported advisory counts. Detailed advisory output is not copied into this report.",
                        "Review advisory details from a trusted workstation, assess reachability and upgrade impact, then validate changes in CI.",
                        project / "package.json")
    return {"requested": True, "status": "completed" if result.returncode in (0, 1) else "completed_with_errors",
            "exit_code": result.returncode, "production_vulnerabilities": counts, "network_used": True}


def project_type(project: Path, files: list[Path]) -> list[str]:
    names = {path.name for path in files}
    result = []
    if (project / ".git").exists(): result.append("git")
    if "package.json" in names: result.append("node")
    if names.intersection({"requirements.txt", "pyproject.toml", "Pipfile"}): result.append("python")
    if "go.mod" in names: result.append("go")
    if "Cargo.toml" in names: result.append("rust")
    if names.intersection({"pom.xml", "build.gradle", "build.gradle.kts"}): result.append("java")
    if "render.yaml" in names: result.append("render-blueprint")
    return result or ["filesystem"]


def audit_project(project: Path, include_hidden: bool = True, npm_audit: bool = False) -> dict[str, Any]:
    project = project.resolve(strict=True)
    files = list(safe_walk(project, include_hidden))
    findings: list[dict[str, Any]] = []
    languages = Counter(SOURCE_EXTENSIONS[path.suffix.lower()] for path in files if path.suffix.lower() in SOURCE_EXTENSIONS)
    python_checked = audit_python(project, files, findings)
    javascript = audit_javascript(project, files, findings)
    html_refs = audit_html_assets(project, files, findings)
    package = audit_package_json(project, findings)
    python_deps = audit_python_dependencies(project, files)
    render = audit_render(project, findings)
    npm_result = optional_npm_audit(project, findings) if npm_audit else {
        "requested": False, "status": "not_requested", "network_used": False,
    }
    if not any((project / name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")) and not package.get("license"):
        add_finding(findings, project, "ROOT-LICENSE-NOT-FOUND", "informational", "licensing",
                    "Root license file not detected",
                    "No common root license file was found; this is a metadata observation, not a legal conclusion.",
                    "Confirm the repository's distribution license and third-party notices.")
    go_mod = project / "go.mod"
    go_dependencies = 0
    if go_mod.is_file():
        go_dependencies = len(re.findall(r"^\s*[A-Za-z0-9._~/-]+\s+v[0-9]", read_text(go_mod) or "", re.M))
    findings.sort(key=lambda row: (SEVERITY_RANK.get(row["severity"], 9), row.get("file", ""), row["rule_id"]))
    counts = Counter(row["severity"] for row in findings)
    return {
        "path": str(project), "project_type": project_type(project, files),
        "files_scanned": len(files),
        "source_files_scanned": sum(1 for path in files if path.suffix.lower() in SOURCE_EXTENSIONS),
        "languages": dict(sorted(languages.items())), "git": git_status(project),
        "dependency_inventory": {
            "npm": package, "python": python_deps, "go_direct_require_entries": go_dependencies,
            "online_npm_audit": npm_result,
        },
        "service_bindings": render,
        "static_checks": {
            "python_files_parsed": python_checked, "javascript": javascript,
            "html_local_references_checked": html_refs,
            "build_commands_executed": False, "project_code_executed": False,
        },
        "findings_summary": {name: counts.get(name, 0) for name in SEVERITY_RANK},
        "findings": findings,
    }


def audit_workspace(root: Path, include_hidden: bool = True, npm_audit: bool = False) -> dict[str, Any]:
    root = root.expanduser()
    if root.is_symlink():
        raise ValueError("Audit root cannot be a symbolic link; select its real target explicitly.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Audit root must be an existing, non-symbolic-link directory.")
    projects = discover_projects(root)
    results = [audit_project(project, include_hidden, npm_audit) for project in projects]
    findings = []
    for item in results:
        for finding in item["findings"]:
            enriched = dict(finding)
            enriched["project"] = item["path"]
            findings.append(enriched)
    findings.sort(key=lambda row: (SEVERITY_RANK.get(row["severity"], 9), row["project"], row.get("file", "")))
    counts = Counter(row["severity"] for row in findings)
    return {
        "schema_version": TOOL_SCHEMA, "tool": "RevelaAI Autonomous Workspace Auditor",
        "tool_version": "0.3.0", "created_at": utc_now(),
        "environment": {"platform": platform.platform(), "python_version": sys.version.split()[0],
                        "node_available": bool(shutil.which("node"))},
        "scope": {"root": str(root), "projects_discovered": len(results),
                  "hidden_paths_included": include_hidden, "network_used": bool(npm_audit)},
        "summary": {
            "projects": len(results), "files_scanned": sum(row["files_scanned"] for row in results),
            "source_files_scanned": sum(row["source_files_scanned"] for row in results),
            "findings": len(findings), **{name: counts.get(name, 0) for name in SEVERITY_RANK},
        },
        "projects": results, "findings": findings,
        "safety": {
            "source_files_modified": False, "project_commands_executed": False,
            "binaries_executed": False, "remote_services_contacted": bool(npm_audit),
            "secrets_or_secret_values_collected": False,
            "notes": [
                "Reports contain metadata and findings, not source-file contents or credential values.",
                "Python files use ast parsing; Node checks are parser-only and limited to .js/.mjs/.cjs.",
                "TypeScript, JSX, framework routing and runtime service health require native toolchains.",
                "No source patch is applied during an audit; use a separately reviewed repair plan.",
                "A bounded static audit is not proof that a project is secure or deployable.",
            ],
        },
    }


def export_handoff_findings(report: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    if report.get("schema_version") != TOOL_SCHEMA:
        raise ValueError("Unsupported workspace audit report schema.")
    output_dir = output_dir.expanduser()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Finding output directory must be new or empty; refusing to overwrite.")
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for row in report.get("findings", []):
        severity = row.get("severity")
        if severity not in {"critical", "high", "medium", "low", "informational"}:
            continue
        identity = hashlib.sha256(f"{row.get('project')}:{row.get('id')}".encode("utf-8")).hexdigest()[:16]
        target = str(row.get("project") or "")[:512]
        file_ref = str(row.get("file") or "")
        evidence = [{"kind": "source_reference", "ref": (f"{target}/{file_ref}" if file_ref else target)[:1024]}]
        if isinstance(row.get("file_sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", row["file_sha256"]):
            evidence[0]["sha256"] = row["file_sha256"]
        if isinstance(row.get("line"), int):
            evidence[0]["note"] = f"line {row['line']}"
        finding = {
            "schema_version": HANDOFF_SCHEMA_VERSION, "id": f"field-{identity}",
            "source": "revela-field-engine", "observed_at": report.get("created_at") or utc_now(),
            "target": target or "local workspace", "category": str(row.get("category") or "code-audit")[:80],
            "severity": severity, "title": str(row.get("title") or "Workspace diagnostic finding")[:240],
            "summary": str(row.get("detail") or "")[:4000], "evidence": evidence,
            "recommendation": str(row.get("recommendation") or "Review this finding manually.")[:4000],
            "scope": "local", "simulated": False,
        }
        filename = finding["id"] + ".json"
        (output_dir / filename).write_text(json.dumps(finding, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(filename)
    return {
        "status": "exported", "directory": str(output_dir.resolve()), "count": len(written), "files": written,
        "next_step": "Use the existing authorised Field Engine sync command for one finding at a time. This is a human-reviewed hand-off, not automatic repair or core activation.",
    }
