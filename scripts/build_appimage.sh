#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_REAL_DIR="$(readlink -f "${ROOT_DIR}")"
APP_NAME="WhatsAppClient"
APP_DIR="${ROOT_REAL_DIR}/AppDir"
ICON_SRC="${ROOT_REAL_DIR}/whatsapp_icon.png"
SPEC_FILE="${ROOT_REAL_DIR}/WhatsAppClient.spec"
PRUNE_SCRIPT="${ROOT_REAL_DIR}/scripts/prune_appdir.sh"
DIST_APP_DIR="${ROOT_REAL_DIR}/dist/${APP_NAME}"
PYI_CACHE_DIR="${ROOT_REAL_DIR}/.pyinstaller-cache"
APPIMAGETOOL_LOCAL="${ROOT_REAL_DIR}/tools/appimagetool"

mkdir -p "${ROOT_REAL_DIR}/dist"
mkdir -p "${PYI_CACHE_DIR}"

if command -v pyinstaller >/dev/null 2>&1; then
  PYI_BIN="pyinstaller"
elif [[ -x "${ROOT_DIR}/.venv/bin/pyinstaller" ]]; then
  PYI_BIN="${ROOT_DIR}/.venv/bin/pyinstaller"
else
  echo "pyinstaller not found (PATH or .venv/bin)."
  exit 1
fi

PYINSTALLER_CONFIG_DIR="${PYI_CACHE_DIR}" "${PYI_BIN}" --clean "${SPEC_FILE}"

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/usr/bin"
mkdir -p "${APP_DIR}/usr/share/applications"
mkdir -p "${APP_DIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APP_DIR}/usr/share/metainfo"

if [[ ! -d "${DIST_APP_DIR}" ]]; then
  echo "Expected onedir build output missing: ${DIST_APP_DIR}"
  exit 1
fi

cp -a "${DIST_APP_DIR}/." "${APP_DIR}/usr/bin/"
cp "${ICON_SRC}" "${APP_DIR}/usr/share/icons/hicolor/256x256/apps/whatsapp.png"
cp "${ICON_SRC}" "${APP_DIR}/whatsapp.png"
cp "${ROOT_DIR}/packaging/AppRun" "${APP_DIR}/AppRun"
cp "${ROOT_DIR}/packaging/WhatsAppClient.desktop" "${APP_DIR}/WhatsAppClient.desktop"
cp "${ROOT_DIR}/packaging/WhatsAppClient.desktop" "${APP_DIR}/usr/share/applications/WhatsAppClient.desktop"
cp "${ROOT_DIR}/packaging/WhatsAppClient.appdata.xml" "${APP_DIR}/usr/share/metainfo/com.github.sejanh.whatsappclient.appdata.xml"

chmod +x "${APP_DIR}/AppRun"

if [[ -x "${PRUNE_SCRIPT}" ]]; then
  echo "[size] AppDir before prune: $(du -sh "${APP_DIR}" | cut -f1)"
  "${PRUNE_SCRIPT}" "${APP_DIR}"
  echo "[size] AppDir after prune:  $(du -sh "${APP_DIR}" | cut -f1)"
fi

if [[ -x "${APPIMAGETOOL_LOCAL}" ]]; then
  "${APPIMAGETOOL_LOCAL}" "${APP_DIR}"
elif command -v appimagetool >/dev/null 2>&1; then
  appimagetool "${APP_DIR}"
else
  echo "appimagetool not found. Place it at tools/appimagetool or install it in PATH."
fi
