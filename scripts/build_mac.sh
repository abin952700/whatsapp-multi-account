#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="WhatsAppClient"
ICON_SRC="${ROOT_DIR}/whatsapp_icon.png"
PYI_CACHE_DIR="${ROOT_DIR}/.pyinstaller-cache"
DIST_APP="${ROOT_DIR}/dist/${APP_NAME}.app"

mkdir -p "${PYI_CACHE_DIR}"

if command -v pyinstaller >/dev/null 2>&1; then
  PYI_BIN="pyinstaller"
elif [[ -x "${ROOT_DIR}/.venv/bin/pyinstaller" ]]; then
  PYI_BIN="${ROOT_DIR}/.venv/bin/pyinstaller"
else
  echo "pyinstaller not found. Install it first: pip install -r requirements.txt"
  exit 1
fi

PYINSTALLER_CONFIG_DIR="${PYI_CACHE_DIR}" "${PYI_BIN}" --clean \
  --name "${APP_NAME}" \
  --windowed \
  --noconfirm \
  --optimize 2 \
  --strip \
  --exclude-module tkinter \
  --exclude-module unittest \
  --exclude-module pydoc \
  --exclude-module doctest \
  --exclude-module test \
  --exclude-module distutils \
  --exclude-module setuptools \
  --exclude-module pip \
  --exclude-module wheel \
  --exclude-module numpy \
  --exclude-module pandas \
  --exclude-module matplotlib \
  --exclude-module scipy \
  --exclude-module IPython \
  --exclude-module jupyter \
  --exclude-module pytest \
  --icon "${ICON_SRC}" \
  "${ROOT_DIR}/main.py"

if [[ -d "${DIST_APP}" ]]; then
  echo "[size] macOS app bundle: $(du -sh "${DIST_APP}" | cut -f1)"
fi
