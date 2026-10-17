import os
import platform
import sys
import json
import tempfile
import re
import shutil

APP_VERSION = "1.0.1"
GITHUB_REPO = "sejanH/whatsapp-multi-account"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

WHATSAPP_WEB_URL = "https://web.whatsapp.com"

INACTIVE_UNLOAD_MS = 3 * 60 * 1000
TOP_BAR_HEIGHT = 32
ENABLE_LIFECYCLE_FREEZE = False

_INSTANCE_NAME = "instance-1"
_INSTANCE_LOCK = None


def _application_root():
    if platform.system() == "Windows":
        # 便携模式：打包后固定使用 EXE 所在目录，不能使用进程当前工作
        # 目录，因为从快捷方式启动时工作目录可能是 System32 等位置。
        if getattr(sys, "frozen", False):
            program_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            program_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        portable_root = os.path.join(program_dir, "data")
        legacy_base = os.environ.get("APPDATA") or os.path.expanduser("~")
        legacy_root = os.path.join(legacy_base, "whatsapp-pyqt")
        if not os.path.exists(portable_root) and os.path.isdir(legacy_root):
            try:
                shutil.copytree(
                    legacy_root,
                    portable_root,
                    ignore=shutil.ignore_patterns("ipc", ".instance-locks", "crash.log"),
                )
            except OSError:
                # 后续创建目录时会给出真实的权限错误；迁移失败不应破坏
                # 已保存在旧目录里的任何数据。
                pass
        return portable_root
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/WhatsAppClient")
    return os.path.expanduser("~/.config/whatsapp-pyqt")


def _safe_instance_name(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", value):
        raise ValueError("实例名称只能包含字母、数字、下划线和短横线")
    return value


def initialize_instance(requested="", acquire_lock=True):
    """选择并锁定实例目录；工作进程只继承实例，不重复加锁。"""
    global _INSTANCE_NAME, _INSTANCE_LOCK
    requested = _safe_instance_name(requested)
    if not acquire_lock:
        _INSTANCE_NAME = requested or "instance-1"
        return _INSTANCE_NAME

    candidates = [requested] if requested else [f"instance-{i}" for i in range(1, 100)]
    lock_dir = os.path.join(_application_root(), ".instance-locks")
    os.makedirs(lock_dir, mode=0o700, exist_ok=True)
    for name in candidates:
        path = os.path.join(lock_dir, name + ".lock")
        handle = open(path, "a+")
        try:
            if platform.system() == "Windows":
                import msvcrt
                handle.seek(0)
                handle.write("0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            handle.close()
            continue
        _INSTANCE_NAME = name
        _INSTANCE_LOCK = handle
        return name
    if requested:
        raise RuntimeError(f"实例 {requested} 已经在运行")
    raise RuntimeError("没有可用的程序实例槽位")


def get_instance_name():
    return _INSTANCE_NAME


def get_base_storage_dir():
    """返回账号数据根目录；Windows 使用程序目录下的便携数据。"""
    root = _application_root()
    # instance-1 沿用原目录，确保升级后已有账号和登录状态不丢失。
    if _INSTANCE_NAME == "instance-1":
        return root
    return os.path.join(root, "instances", _INSTANCE_NAME)


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
