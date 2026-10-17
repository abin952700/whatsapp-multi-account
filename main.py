import sys
import os
import traceback
import datetime
import platform

from app.config import (
    get_base_storage_dir,
    get_icon_path,
    initialize_instance,
    load_accounts,
    load_settings,
)

_worker_process = any(
    flag in sys.argv for flag in ("--windows-account-worker", "--background-account-worker")
)
_requested_instance = ""
if "--instance" in sys.argv:
    position = sys.argv.index("--instance")
    if position + 1 >= len(sys.argv):
        raise SystemExit("--instance requires a name")
    _requested_instance = sys.argv[position + 1]
initialize_instance(_requested_instance, acquire_lock=not _worker_process)

# Chromium 参数必须在导入 Qt WebEngine 前设置。macOS 不需要 Linux 的 GPU 沙盒参数。
chromium_flags = [
    "--enable-logging",
    "--log-level=1",
    "--disable-quic",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]
if platform.system() == "Linux":
    chromium_flags.append("--disable-gpu-sandbox")

# Windows 的每账号代理必须在导入 Qt WebEngine 之前配置，否则 Chromium
# 网络服务可能已启动并忽略后续的 QNetworkProxy 设置，页面会停在 0%。
_prepared_windows_worker_proxy = False
if "--windows-account-worker" in sys.argv:
    from app.proxy_extension import prepare_chromium_proxy

    profile_arg = sys.argv[sys.argv.index("--windows-account-worker") + 1]
    account_config = next(
        item for item in load_accounts()
        if item.get("profile_name") == profile_arg
    )
    proxy_mode_arg = str(account_config.get("proxy_mode") or "none")
    custom_proxy_arg = str(account_config.get("proxy_url") or "")
    proxy_url_arg = (
        str(load_settings().get("global_proxy_url") or "")
        if proxy_mode_arg == "global"
        else custom_proxy_arg if proxy_mode_arg == "custom" else ""
    )
    proxy_flag = prepare_chromium_proxy(proxy_mode_arg, proxy_url_arg)
    if proxy_flag:
        chromium_flags.append(proxy_flag)
    _prepared_windows_worker_proxy = True
if _prepared_windows_worker_proxy:
    # 主进程的环境变量会被账号进程继承，因此这里必须覆盖，不能使用
    # setdefault，否则本账号专属的 --proxy-server 不会进入 Chromium。
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(chromium_flags)
else:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", " ".join(chromium_flags))

# 关键：必须在 QApplication 创建之前导入
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

# 获取当前运行目录
os.makedirs(get_base_storage_dir(), exist_ok=True)
LOG_FILE = os.path.join(get_base_storage_dir(), "crash.log")


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局异常拦截器，把 Python 报错写入 crash.log"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"时间: {now}\n")
        f.write(f"崩溃信息 (Python 层):\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
        f.write(f"{'='*50}\n")

    # 依然在终端打印一份
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
    print(f"\n程序发生异常，日志已保存至: {LOG_FILE}")


# 劫持系统异常钩子
sys.excepthook = global_exception_handler

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    try:
        worker_flag = next(
            (flag for flag in ("--windows-account-worker", "--background-account-worker") if flag in sys.argv),
            None,
        )
        if worker_flag:
            from PyQt6.QtWidgets import QMainWindow
            from app.account import WhatsAppAccount
            from app.config import load_accounts, load_settings
            from app.proxy_extension import apply_proxy_mode
            from app.windows_account import WindowsWorkerState
            profile = sys.argv[sys.argv.index(worker_flag) + 1]
            worker_token = ""
            if "--worker-token" in sys.argv:
                token_position = sys.argv.index("--worker-token")
                if token_position + 1 < len(sys.argv):
                    worker_token = sys.argv[token_position + 1]
            config = next(item for item in load_accounts() if item.get("profile_name") == profile)
            mode = str(config.get("proxy_mode") or "none")
            custom = str(config.get("proxy_url") or "")
            proxy = str(load_settings().get("global_proxy_url") or "") if mode == "global" else (custom if mode == "custom" else "")
            if not _prepared_windows_worker_proxy:
                apply_proxy_mode(mode, proxy)
            window = QMainWindow()
            window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint)
            if worker_flag == "--background-account-worker":
                window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            account = WhatsAppAccount(profile, proxy_url=proxy)
            window.setCentralWidget(account)
            window.resize(1200, 900); window.show()
            window._state = WindowsWorkerState(
                profile, window, account, worker_token=worker_token
            )
            account.request_load()
            sys.exit(app.exec())
        from app.window import MainWindow
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        global_exception_handler(type(e), e, e.__traceback__)
