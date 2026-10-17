  #!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="WhatsAppClient"
ICON_SRC="${ROOT_DIR}/whatsapp_icon.png"
PYI_CACHE_DIR="${ROOT_DIR}/.pyinstaller-cache"
DIST_APP="${ROOT_DIR}/dist/${APP_NAME}.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

mkdir -p "${PYI_CACHE_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 not found. Install Python 3 first."
  exit 1
fi

if ! "${PYTHON_BIN}" -c "import PyInstaller, PyQt6.QtWebEngineWidgets" 2>/dev/null; then
  echo "Build dependencies are missing for ${PYTHON_BIN}."
  "${PYTHON_BIN}" -c "import PyInstaller, PyQt6.QtWebEngineWidgets" || true
  echo "Run: make mac-setup"
  exit 1
fi

echo "Building ${APP_NAME}.app with ${PYTHON_BIN} ($(uname -m))..."

PYINSTALLER_CONFIG_DIR="${PYI_CACHE_DIR}" "${PYTHON_BIN}" -m PyInstaller --clean \
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
  --add-data "${ICON_SRC}:." \
  --osx-bundle-identifier "io.github.sejanh.whatsapp-multi-account" \
  "${ROOT_DIR}/main.py"

if [[ -d "${DIST_APP}" ]]; then
  # 让 LaunchServices 忽略同 bundle id 的旧构建缓存。
  touch "${DIST_APP}" "${DIST_APP}/Contents/MacOS/${APP_NAME}"
  echo "[size] macOS app bundle: $(du -sh "${DIST_APP}" | cut -f1)"
  echo "Built: ${DIST_APP}"
  echo "Launch: open \"${DIST_APP}\""
fi
