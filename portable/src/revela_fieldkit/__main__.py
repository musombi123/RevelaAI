"""Module entry point for the Python companion tools."""
import sys

if len(sys.argv) > 1 and sys.argv[1] in {"audit", "drives", "repair"}:
    from .workspace_cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
