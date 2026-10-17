import os
import platform

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
    return os.path.expanduser("~/.config/whatsapp-pyqt")


def get_icon_path():
    """项目根目录下的图标路径。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "whatsapp_icon.png")