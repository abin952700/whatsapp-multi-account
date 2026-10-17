#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

is_supported_python() {
  "$1" -c 'import sys; raise SystemExit(not ((3, 9) <= sys.version_info[:2] < (3, 15)))' \
    >/dev/null 2>&1
}

if [[ -n "${MAC_PYTHON:-}" ]]; then
  if [[ ! -x "${MAC_PYTHON}" ]] || ! is_supported_python "${MAC_PYTHON}"; then
    echo "MAC_PYTHON must point to Python 3.9 through 3.14: ${MAC_PYTHON}"
    exit 1
  fi
  PYTHON_BIN="${MAC_PYTHON}"
else
  PYTHON_BIN=""
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 /usr/bin/python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      resolved="$(command -v "${candidate}")"
      if is_supported_python "${resolved}"; then
        PYTHON_BIN="${resolved}"
        break
      fi
    fi
  done
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "No compatible Python found. Install Python 3.9 through 3.14."
  echo "Python 3.15 is not supported by the pinned PyInstaller version."
  exit 1
fi

if [[ -x "${VENV_DIR}/bin/python" ]] && ! is_supported_python "${VENV_DIR}/bin/python"; then
  current_version="$(${VENV_DIR}/bin/python --version 2>&1)"
  echo "Existing .venv uses unsupported ${current_version}."
  echo "Move or remove .venv, then run: make mac-setup"
  exit 1
fi

echo "Using $(${PYTHON_BIN} --version 2>&1) at ${PYTHON_BIN}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt"

echo "macOS environment is ready: ${VENV_DIR}"
