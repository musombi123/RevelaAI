#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

# Prefer the self-contained Go Field Engine. It does not need Ollama or Go installed.
NATIVE="$ROOT/bin/linux-amd64/revela-field"
if [ -x "$NATIVE" ]; then
  exec "$NATIVE" menu
fi

# Retain the standard-library Python companion as a compatibility fallback.
export PYTHONPATH="$ROOT/src"
if command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "No native Field Engine and Python 3.10+ is required for the companion tools." >&2
  exit 1
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10 or newer is required." >&2
  exit 1
}
exec "$PYTHON" -m revela_fieldkit menu
