import os
import platform
import sys
import json
import tempfile

APP_VERSION = "1.0.1"
GITHUB_REPO = "sejanH/whatsapp-multi-account"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

WHATSAPP_WEB_URL = "https://web.whatsapp.com"

INACTIVE_UNLOAD_MS = 3 * 60 * 1000
TOP_BAR_HEIGHT = 32
ENABLE_LIFECYCLE_FREEZE = False


def get_base_storage_dir():
    """按平台返回账号数据存储根目录。"""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "whatsapp-pyqt")
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/WhatsAppClient")
    return os.path.expanduser("~/.config/whatsapp-pyqt")


def get_icon_path():
    """返回源码目录或 PyInstaller 应用包中的图标路径。"""
    root = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(root, "whatsapp_icon.png")


def get_config_file_path():
    """获取账号配置文件的路径"""
    return os.path.join(get_base_storage_dir(), "accounts.json")


def get_settings_file_path():
    return os.path.join(get_base_storage_dir(), "settings.json")


def load_settings():
    try:
        with open(get_settings_file_path(), "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    atomic_write_json(get_settings_file_path(), settings)


def load_accounts():
    try:
        with open(get_config_file_path(), "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_accounts(accounts):
    atomic_write_json(get_config_file_path(), accounts)


def atomic_write_json(path, data):
    """在同一目录内原子替换 JSON，避免异常退出损坏配置。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".whatsapp-client-",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise
