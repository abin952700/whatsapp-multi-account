#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:?Usage: prune_appdir.sh <AppDir>}"
TARGET="${APP_DIR}/usr/bin"
QT_ROOT="${TARGET}/_internal/PyQt6/Qt6"

if [[ ! -d "${TARGET}" ]]; then
  echo "No usr/bin found in ${APP_DIR}; skipping prune."
  exit 0
fi

# Python build leftovers
find "${TARGET}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${TARGET}" -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.a" \) -delete

# Prune common non-runtime docs/tests if present.
find "${TARGET}" -type d \( -name "tests" -o -name "test" -o -name "docs" -o -name "doc" \) -prune -exec rm -rf {} +

# Keep only en-US locale for QtWebEngine if locale pack exists.
if [[ -d "${QT_ROOT}/translations/qtwebengine_locales" ]]; then
  find "${QT_ROOT}/translations/qtwebengine_locales" -type f ! -name "en-US.pak" -delete
fi

# Keep only English Qt translations.
if [[ -d "${QT_ROOT}/translations" ]]; then
  find "${QT_ROOT}/translations" -maxdepth 1 -type f -name "*.qm" \
    ! -name "*_en.qm" \
    ! -name "*_en_US.qm" \
    -delete

  # Drop optional module translation groups not needed for this app.
  rm -f "${QT_ROOT}/translations"/qt_help_* \
        "${QT_ROOT}/translations"/qtlocation_* \
        "${QT_ROOT}/translations"/qtconnectivity_* \
        "${QT_ROOT}/translations"/qtmultimedia_* \
        "${QT_ROOT}/translations"/qtserialport_*
fi
