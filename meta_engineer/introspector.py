"""Read-only architecture scanner for the native FastAPI RevelaAI runtime."""
from __future__ import annotations
import ast, json, re
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ["fastapi_routes/auth.py", "fastapi_routes/admin_auth.py", "revelai/core/config.py", "revelai/core/brain_os.py"]

def scan_architecture() -> dict[str, Any]:
    """Walk source roots and map Python imports without writing files."""
    roots = [ROOT / "fastapi_routes", ROOT / "revelai", ROOT / "services", ROOT / "ai", ROOT / "models", ROOT / "automation_fabric", ROOT / "meta_engineer"]
    structure, dependencies, schemas, files = {}, {}, {}, []
    for root in roots:
        if not root.is_dir(): continue
        key = root.relative_to(ROOT).as_posix(); structure[key] = []
        for path in sorted(root.rglob("*.py")):
            if any(p in {".git", "__pycache__", ".venv", "venv"} for p in path.parts): continue
            rel = path.relative_to(ROOT).as_posix(); structure[key].append(rel); files.append(path)
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try: source = path.read_text(encoding="utf-8"); tree = ast.parse(source, filename=rel)
        except (OSError, UnicodeError, SyntaxError) as exc:
            dependencies[rel] = ["parse-error:" + type(exc).__name__]; continue
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imports.add("." * node.level + node.module)
        dependencies[rel] = sorted(imports)
        if "/models/" in "/" + rel or rel.startswith("models/") or rel.startswith("revelai/models/"):
            classes = {}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    fields = [{"name": n.target.id, "annotation": ast.unparse(n.annotation)} for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
                    classes[node.name] = {"fields": fields, "docstring": ast.get_docstring(node)}
            schemas[rel] = classes
    for rel in ("config/db.py", "services/memory_store.py"):
        path = ROOT / rel
        if path.is_file():
            try: source = path.read_text(encoding="utf-8")
            except OSError: continue
            names = sorted(set(re.findall(r"""["'](conversations|memories|ideas|bestThings|learnings)["']""", source)))
            if names: schemas["collections:" + rel] = {"database": "revelai", "collections": names}
    route_root = ROOT / "routes"
    if not route_root.is_dir(): route_root = ROOT / "revelai" / "routers"
    free_slots = [str((route_root / n).relative_to(ROOT)) for n in ("meta_engineer_routes.py", "feature_routes.py", "health_routes.py") if not (route_root / n).exists()] if route_root.is_dir() else ["routes/meta_engineer_routes.py"]
    return {"structure": structure, "dependencies": dependencies, "schemas": schemas, "free_slots": free_slots or ["No obvious free route slot; review an existing blueprint"], "protected_paths": PROTECTED, "read_only": True, "framework": "FastAPI runtime; dormant legacy Flask route source is excluded from the active gateway"}

if __name__ == "__main__": print(json.dumps(scan_architecture(), indent=2, default=str))
