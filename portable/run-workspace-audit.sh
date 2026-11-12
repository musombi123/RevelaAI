#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"

PYTHON="$HERE/runtimes/python-linux-x64/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.10+ is required. Install it on this host or provide a verified portable runtime." >&2
  exit 2
fi

if [[ "$#" -gt 0 && "$1" == "--drives" ]]; then
  exec "$PYTHON" -m revela_fieldkit drives
fi

if [[ "$#" -eq 0 ]]; then
  echo "REVELAAI WORKSPACE AUDITOR"
  echo "1. List mounted drives"
  echo "2. Audit a repository or mounted volume"
  read -r -p "Choose an action: " choice
  if [[ "$choice" == "1" ]]; then
    exec "$PYTHON" -m revela_fieldkit drives
  fi
  if [[ "$choice" != "2" ]]; then exit 0; fi
  read -r -p "Enter exact authorized directory path: " ROOT
  set -- "$ROOT"
fi

ROOT="$1"
if [[ ! -d "$ROOT" ]]; then
  echo "Audit root is not an existing directory: $ROOT" >&2
  exit 2
fi
shift
exec "$PYTHON" -m revela_fieldkit audit --root "$ROOT" --authorized "$@"
