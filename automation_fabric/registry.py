"""Deterministic built-in tools for RevelaAI Automation Fabric.

No built-in tool runs a shell command, imports generated Python, installs a
package, changes OS settings, or drives an actuator. New tools are proposals
until a developer explicitly reviews and registers them.
"""
from __future__ import annotations

import ast
import html
import ipaddress
import json
import os
import platform
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .policy import resolve_workspace_path


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    scopes: tuple[str, ...]
    risk: str
    confirmation_required: bool
    local_only: bool
    argument_schema: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": "1.0.0",
            "required_scopes": list(self.scopes),
            "risk": self.risk,
            "confirmation_required": self.confirmation_required,
            "local_agent_required": self.local_only,
            "arguments": self.argument_schema,
            "execution_model": "deterministic_no_model",
        }


TOOLS: dict[str, ToolSpec] = {
    "system.inventory": ToolSpec(
        "system.inventory", "Report non-secret runtime and platform information.",
        ("system:read",), "low", False, True, {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "math.evaluate": ToolSpec(
        "math.evaluate", "Evaluate a bounded arithmetic expression without eval or code execution.",
        (), "low", False, False,
        {"type": "object", "required": ["expression"], "properties": {"expression": {"type": "string", "maxLength": 256}}, "additionalProperties": False},
    ),
    "workspace.list": ToolSpec(
        "workspace.list", "List immediate entries in the signed-in user's isolated workspace.",
        ("workspace:read",), "low", False, False,
        {"type": "object", "properties": {"path": {"type": "string", "default": "."}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
    ),
    "workspace.read_text": ToolSpec(
        "workspace.read_text", "Read UTF-8 text from the user's isolated workspace.",
        ("workspace:read",), "low", False, False,
        {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000}}, "additionalProperties": False},
    ),
    "workspace.write_text": ToolSpec(
        "workspace.write_text", "Atomically write UTF-8 text inside the user's isolated workspace.",
        ("workspace:write",), "high", True, False,
        {"type": "object", "required": ["path", "content"], "properties": {"path": {"type": "string"}, "content": {"type": "string", "maxLength": 262144}}, "additionalProperties": False},
    ),
    "factory.scaffold_python_tool": ToolSpec(
        "factory.scaffold_python_tool", "Create a reviewed-but-disabled Python tool proposal and manifest.",
        ("tools:scaffold", "workspace:write"), "medium", True, False,
        {"type": "object", "required": ["name", "description"], "properties": {"name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,39}$"}, "description": {"type": "string", "maxLength": 240}}, "additionalProperties": False},
    ),
    "research.fetch_public_page": ToolSpec(
        "research.fetch_public_page", "Fetch a public HTTPS documentation page from the configured host allowlist.",
        ("research:public_web",), "medium", True, False,
        {"type": "object", "required": ["url"], "properties": {"url": {"type": "string", "maxLength": 2048}}, "additionalProperties": False},
    ),
    "hardware.discover": ToolSpec(
        "hardware.discover", "Read-only discovery of common Linux device nodes; does not open or control hardware.",
        ("hardware:discover",), "low", False, True,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
}

MAX_TEXT_BYTES = 262144
MAX_READ_BYTES = 131072
MAX_PLAN_ARGUMENTS_BYTES = 350000
MAX_FETCH_BYTES = 200000


def tool_catalog() -> list[dict[str, Any]]:
    return [spec.public_dict() for spec in TOOLS.values()]


def validate_arguments(name: str, args: Any) -> dict[str, Any]:
    if name not in TOOLS:
        raise ValueError("unknown tool")
    if not isinstance(args, dict):
        raise ValueError("tool args must be a JSON object")
    schema = TOOLS[name].argument_schema
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False and any(key not in properties for key in args):
        raise ValueError("tool args include an unsupported field")
    for key in schema.get("required", []):
        if key not in args:
            raise ValueError(f"missing required argument: {key}")

    result = dict(args)
    if name == "math.evaluate":
        if not isinstance(result.get("expression"), str) or len(result["expression"]) > 256:
            raise ValueError("expression must be a string of at most 256 characters")
        # Parse and evaluate at planning time as validation, using the safe AST interpreter.
        _calculate(result["expression"])
    elif name == "workspace.list":
        if "path" in result and not isinstance(result["path"], str):
            raise ValueError("path must be a string")
        result.setdefault("path", ".")
        result["limit"] = _bounded_integer(result.get("limit", 50), 1, 100, "limit")
    elif name == "workspace.read_text":
        if not isinstance(result.get("path"), str):
            raise ValueError("path must be a string")
        result["max_chars"] = _bounded_integer(result.get("max_chars", 30000), 1, 100000, "max_chars")
    elif name == "workspace.write_text":
        if not isinstance(result.get("path"), str) or not isinstance(result.get("content"), str):
            raise ValueError("path and content must be strings")
        if len(result["content"].encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("content exceeds the 256 KiB limit")
    elif name == "factory.scaffold_python_tool":
        tool_name = result.get("name")
        description = result.get("description")
        if not isinstance(tool_name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", tool_name):
            raise ValueError("name must match ^[a-z][a-z0-9_]{1,39}$")
        if not isinstance(description, str) or not description.strip() or len(description) > 240:
            raise ValueError("description must be 1–240 characters")
        result["description"] = description.strip()
    elif name == "research.fetch_public_page":
        if not isinstance(result.get("url"), str) or len(result["url"]) > 2048:
            raise ValueError("url must be a string of at most 2048 characters")
        _validate_public_url(result["url"])
    elif name in {"system.inventory", "hardware.discover"}:
        if result:
            raise ValueError("this tool does not accept arguments")
    return result


def _bounded_integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


_ALLOWED_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}
_ALLOWED_UNARY = {ast.UAdd: lambda a: +a, ast.USub: lambda a: -a}


def _calculate(expression: str) -> int | float:
    if not expression.strip() or len(expression) > 256:
        raise ValueError("expression is empty or too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid arithmetic expression") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("expression is too complex")

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
            if abs(value) > 1e12:
                raise ValueError("numeric literal is out of range")
            return value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 10 or abs(left) > 1e6):
                raise ValueError("exponentiation is out of bounds")
            value = _ALLOWED_BINARY[type(node.op)](left, right)
            if not isinstance(value, (int, float)) or abs(value) > 1e100:
                raise ValueError("result is out of range")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](visit(node.operand))
        raise ValueError("only numeric literals and basic arithmetic operators are allowed")

    try:
        return visit(tree)
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError("arithmetic operation is undefined or out of range") from exc


def _tool_workspace_path(workspace: str | Path, raw: str, *, allow_root: bool = False) -> Path:
    return resolve_workspace_path(workspace, raw, allow_root=allow_root)


def run_tool(name: str, args: dict[str, Any], workspace: str | Path, *, local_mode: bool = False) -> dict[str, Any]:
    safe_args = validate_arguments(name, args)
    spec = TOOLS[name]
    if spec.local_only and not local_mode:
        raise ValueError("this tool requires the installed local agent on the target device")
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)

    if name == "math.evaluate":
        return {"expression": safe_args["expression"], "value": _calculate(safe_args["expression"])}
    if name == "system.inventory":
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "runtime": "revelaai-automation-fabric",
            "workspace_ready": root.is_dir(),
        }
    if name == "workspace.list":
        folder = _tool_workspace_path(root, safe_args["path"], allow_root=True)
        if not folder.is_dir():
            raise ValueError("workspace path is not a directory")
        entries = []
        for item in sorted(folder.iterdir(), key=lambda p: p.name.casefold())[:safe_args["limit"]]:
            entries.append({
                "name": item.name,
                "path": item.relative_to(root).as_posix(),
                "kind": "symlink" if item.is_symlink() else "directory" if item.is_dir() else "file",
                "size_bytes": None if item.is_symlink() or item.is_dir() else item.stat().st_size,
            })
        return {"path": folder.relative_to(root).as_posix() or ".", "entries": entries, "count": len(entries)}
    if name == "workspace.read_text":
        target = _tool_workspace_path(root, safe_args["path"])
        if not target.is_file() or target.is_symlink():
            raise ValueError("workspace file does not exist or is not a regular file")
        with target.open("rb") as handle:
            raw = handle.read(min(MAX_READ_BYTES, safe_args["max_chars"] * 4) + 1)
        if len(raw) > min(MAX_READ_BYTES, safe_args["max_chars"] * 4):
            raise ValueError("file exceeds the bounded read limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("only UTF-8 text files are supported") from exc
        return {"path": target.relative_to(root).as_posix(), "content": content[:safe_args["max_chars"]], "truncated": len(content) > safe_args["max_chars"]}
    if name == "workspace.write_text":
        target = _tool_workspace_path(root, safe_args["path"])
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists() and (target.is_dir() or target.is_symlink()):
            raise ValueError("target must be a regular file, not a directory or symlink")
        fd, temp_name = tempfile.mkstemp(prefix=".revelaai-write-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(safe_args["content"])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        return {"path": target.relative_to(root).as_posix(), "bytes_written": len(safe_args["content"].encode("utf-8"))}
    if name == "factory.scaffold_python_tool":
        safe_name = safe_args["name"]
        proposal = _tool_workspace_path(root, f"proposals/{safe_name}")
        proposal.mkdir(parents=True, exist_ok=False, mode=0o700)
        manifest = {
            "name": safe_name, "version": "0.1.0", "description": safe_args["description"],
            "entrypoint": "tool.py", "status": "proposal_only", "enabled": False,
            "required_scopes": [], "execution_policy": "manual_review_required",
        }
        source = (
            '"""Untrusted proposal scaffold. Review and test before registering."""\n\n'
            "def run(args: dict) -> dict:\n"
            '    """Implement the tool only after defining a strict input contract."""\n'
            '    return {"status": "not_implemented", "message": "Review this proposal before use."}\n'
        )
        (proposal / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (proposal / "tool.py").write_text(source, encoding="utf-8")
        (proposal / "README.md").write_text(
            "# Tool proposal: " + safe_name + "\n\n" + safe_args["description"] +
            "\n\nStatus: proposal only. This file is never imported or executed automatically.\n"
            "Before registering, add a strict input schema, permission scopes, tests, timeouts, "
            "resource limits, and a security review.\n",
            encoding="utf-8",
        )
        return {"proposal_path": proposal.relative_to(root).as_posix(), "files": ["manifest.json", "tool.py", "README.md"], "enabled": False, "executed": False}
    if name == "research.fetch_public_page":
        return _fetch_public_page(safe_args["url"])
    if name == "hardware.discover":
        candidates: list[dict[str, str]] = []
        if platform.system() == "Linux":
            patterns = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/i2c-*", "/dev/gpiochip*", "/dev/hidraw*")
            import glob
            for pattern in patterns:
                for path in sorted(glob.glob(pattern))[:50]:
                    candidates.append({"path": path, "kind": Path(path).name.split("-")[0]})
        return {
            "platform": platform.system(),
            "read_only": True,
            "opened_devices": False,
            "devices": candidates[:100],
            "note": "Discovery is best-effort. No device was opened or controlled; drivers must be installed and explicitly approved separately.",
        }
    raise ValueError("tool implementation is missing")


def _allowed_research_hosts() -> set[str]:
    configured = os.getenv(
        "REVELAAI_AUTOMATION_ALLOWED_HOSTS",
        "github.com,raw.githubusercontent.com,docs.python.org,developer.mozilla.org,pypi.org",
    )
    return {part.strip().lower().strip(".") for part in configured.split(",") if part.strip()}


def _validate_public_url(raw_url: str, *, resolve_dns: bool = False) -> str:
    parsed = urllib.parse.urlparse(raw_url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("research URLs must be public HTTPS URLs without embedded credentials")
    host = parsed.hostname.rstrip(".").lower()
    allowlist = _allowed_research_hosts()
    if not any(host == item or host.endswith("." + item) for item in allowlist):
        raise ValueError("host is not on REVELAAI_AUTOMATION_ALLOWED_HOSTS")
    # Planning only validates syntax and the explicit host allowlist. Do not
    # cause even DNS/network activity until consent is granted and execution starts.
    if resolve_dns:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("research host could not be resolved") from exc
        if not addresses:
            raise ValueError("research host did not resolve to a public address")
        for item in addresses:
            try:
                address = ipaddress.ip_address(item[4][0])
            except ValueError as exc:
                raise ValueError("research host resolved to an invalid address") from exc
            if not address.is_global:
                raise ValueError("research host resolved to a non-public address")
    return urllib.parse.urlunparse(("https", host, parsed.path or "/", parsed.params, parsed.query, ""))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "br"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag.lower() == "title":
            self.in_title = False
        if tag.lower() in {"p", "div", "li", "h1", "h2", "h3"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self.skip_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned + " ")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_public_page(raw_url: str) -> dict[str, Any]:
    # Called only during approved execution; resolve and reject non-public DNS targets here.
    url = _validate_public_url(raw_url, resolve_dns=True)
    opener = urllib.request.build_opener(_NoRedirect)
    response = None
    for _ in range(4):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "RevelaAI-Automation-Fabric/1.0", "Accept": "text/html,text/plain,application/json"},
            method="GET",
        )
        try:
            response = opener.open(request, timeout=8)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                exc.close()
                if not location:
                    raise ValueError("research redirect omitted Location")
                url = _validate_public_url(urllib.parse.urljoin(url, location), resolve_dns=True)
                continue
            raise ValueError(f"research server returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ValueError("public page could not be fetched") from exc
    if response is None:
        raise ValueError("too many research redirects")
    try:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if not any(value in content_type for value in ("text/html", "text/plain", "application/json", "application/xhtml+xml", "text/markdown")):
            raise ValueError("only text-based public pages are supported")
        raw = response.read(MAX_FETCH_BYTES + 1)
        if len(raw) > MAX_FETCH_BYTES:
            raise ValueError("public page exceeds the 200 KB limit")
        charset = response.headers.get_content_charset() or "utf-8"
        decoded = raw.decode(charset, errors="replace")
        extractor = _TextExtractor()
        extractor.feed(decoded)
        text = html.unescape(" ".join(" ".join(extractor.parts).split()))
        return {
            "url": url,
            "status_code": getattr(response, "status", 200),
            "title": " ".join(" ".join(extractor.title_parts).split())[:240],
            "text": text[:12000],
            "truncated": len(text) > 12000,
            "bytes_read": len(raw),
        }
    finally:
        response.close()
