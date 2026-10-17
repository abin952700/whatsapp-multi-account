#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 not found. Install Python 3 first."
  exit 1
fi

if ! "${PYTHON_BIN}" -c "import PyQt6.QtWebEngineWidgets" 2>/dev/null; then
  echo "Runtime dependencies are missing for ${PYTHON_BIN}."
  "${PYTHON_BIN}" -c "import PyQt6.QtWebEngineWidgets" || true
  echo "Run: make mac-setup"
  exit 1
fi

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" main.py "$@"
