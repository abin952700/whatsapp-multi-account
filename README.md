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

## Per-account proxies

Configure the shared proxy from **Menu > Global proxy settings**. When adding
an account, choose either the global proxy or enter a custom proxy for that
account. Supported formats include:

```text
http://host:port
http://username:password@host:port
https://username:password@host:port
socks5://username:password@host:port
```

Each account runs in its own WebEngine worker process. The worker applies that
account's proxy before loading WhatsApp, so different accounts can remain online
simultaneously without sharing an application-level proxy. The main window is an
account controller; selecting an account opens its independent native window.
Leave the global proxy setting empty to disable it. The account list resolves the
proxy IP's country in the background and displays its flag and country name.
Credentials are stored locally with the account configuration; protect access
to your user account.

## Persistent sessions

Account definitions, proxy choices, and the last selected account are restored
on the next launch. Each account has a permanent isolated profile directory
containing its WhatsApp cookies, local storage, IndexedDB, service workers,
cache, and persisted permissions. On macOS this data is stored under:

```text
~/Library/Application Support/WhatsAppClient/
```

Do not delete this directory if you want to keep WhatsApp login sessions.

## AppImage (Linux)

1. Install build tools (PyInstaller, appimagetool).
2. Build the AppImage:
   ```bash
   bash scripts/build_appimage.sh
   ```

The resulting `WhatsAppClient-x86_64.AppImage` will be created in the project root when `appimagetool` is available.

## macOS

The following commands must be run on macOS. First, create the virtual
environment and install dependencies:

```bash
make mac-setup
```

The setup script selects an installed Python version from 3.9 through 3.14;
Python 3.15 is not supported by the pinned PyInstaller version. To choose an
interpreter explicitly, run `MAC_PYTHON=/path/to/python3 make mac-setup`.

Run directly from source:

```bash
make mac-run
```

Build the `.app` bundle and open it:

```bash
make mac-build
make mac-open
```

The resulting application is created at `dist/WhatsAppClient.app`. The bundle
is built for the architecture of the Python interpreter used by `.venv`
(`arm64` on Apple Silicon or `x86_64` on Intel Macs).

The underlying scripts can also be run without `make`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/start_mac.sh
bash scripts/build_mac.sh
open dist/WhatsAppClient.app
```

The application is unsigned. On first launch, if Gatekeeper blocks it, use
Finder's **Open** context-menu action. For distribution to other users, sign
and notarize the application with an Apple Developer ID.

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
