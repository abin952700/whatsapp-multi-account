# WhatsApp Multi-Account Client

A PyQt6-based desktop application that allows you to run multiple WhatsApp Web accounts simultaneously in a single window using tabs. Each account maintains its own separate profile and storage, enabling you to use personal and business accounts simultaneously.

## Features

- **Multi-Account Support**: Run multiple WhatsApp accounts simultaneously
- **Tabbed Interface**: Easy switching between different accounts
- **Persistent Sessions**: Each account maintains its own login session and cookies
- **Separate Storage**: Unique storage path for each account profile
- **Custom User-Agent**: Optimized user agent to avoid "Browser not supported" messages

## Requirements

- Python 3.6 or higher
- PyQt6
- PyQt6-WebEngine
- PyInstaller (for building the executable)

## Required Python Scripts

- `main.py` — application entry point (multi-account UI and web views).

## Installation

### Prerequisites

**Install system dependencies**:
```bash
# Ubuntu/Debian
sudo apt-get install python3-pyqt6 python3-pyqt6.qtwebengine
```
```bash
# Fedora/RHEL
sudo dnf install python3-qt6 python3-qt6-webengine
```

**Install Python dependencies**:
```bash
pip install -r requirements.txt
```

## Running

```bash
python3 main.py
```

## AppImage (Linux)

1. Install build tools (PyInstaller, appimagetool).
2. Build the AppImage:
   ```bash
   bash scripts/build_appimage.sh
   ```

The resulting `WhatsAppClient-x86_64.AppImage` will be created in the project root when `appimagetool` is available.

## macOS (.app)

1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Build the app bundle:
   ```bash
   bash scripts/build_mac.sh
   ```

The resulting `WhatsAppClient.app` will be created in `dist/`.

## Using the AppImage

1. Make it executable:
   ```bash
   chmod +x WhatsAppClient-x86_64.AppImage
   ```
2. Run it:
   ```bash
   ./WhatsAppClient-x86_64.AppImage
   ```

If you hit a FUSE error, run:

```bash
./WhatsAppClient-x86_64.AppImage --appimage-extract-and-run
```

## Desktop Entry (Linux)

Copy the AppImage, icon, and desktop file to standard per-user locations.
Replace `USER` in `whatsapp.desktop` with your actual username (or edit paths).

```bash
mkdir -p ~/Apps ~/.local/share/icons/hicolor/256x256/apps ~/.local/share/applications
cp WhatsAppClient-x86_64.AppImage ~/Apps/
cp whatsapp_icon.png ~/.local/share/icons/hicolor/256x256/apps/whatsapp.png
cp whatsapp.desktop ~/.local/share/applications/
chmod +x ~/Apps/WhatsAppClient-x86_64.AppImage
```
