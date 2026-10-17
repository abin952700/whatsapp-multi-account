import sys
import os
import traceback
import datetime
import platform

# Chromium 参数必须在导入 Qt WebEngine 前设置。macOS 不需要 Linux 的 GPU 沙盒参数。
chromium_flags = ["--enable-logging", "--log-level=1"]
if platform.system() == "Linux":
    chromium_flags.append("--disable-gpu-sandbox")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", " ".join(chromium_flags))

# 关键：必须在 QApplication 创建之前导入
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from app.config import get_base_storage_dir, get_icon_path, load_accounts, load_settings

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
        if "--account-worker" in sys.argv:
            from PyQt6.QtWidgets import QMainWindow
            from app.account import WhatsAppAccount
            from app.process_account import WorkerCommandBridge
            from app.proxy_extension import apply_proxy_mode

            position = sys.argv.index("--account-worker")
            profile_name = sys.argv[position + 1]
            account_config = next(
                (item for item in load_accounts() if item.get("profile_name") == profile_name),
                None,
            )
            if account_config is None:
                raise ValueError(f"账号配置不存在: {profile_name}")
            proxy_mode = str(account_config.get("proxy_mode") or "none")
            custom_proxy = str(account_config.get("proxy_url") or "")
            global_proxy = str(load_settings().get("global_proxy_url") or "")
            effective_proxy = global_proxy if proxy_mode == "global" else (
                custom_proxy if proxy_mode == "custom" else ""
            )
            apply_proxy_mode(proxy_mode, effective_proxy)

            window = QMainWindow()
            label = str(account_config.get("phone") or account_config.get("label") or "WhatsApp")
            window.setWindowTitle(f"WhatsApp - {label}")
            window.resize(1200, 900)
            account = WhatsAppAccount(profile_name, proxy_url=effective_proxy)
            account.proxy_mode = proxy_mode
            account.phone_number = str(account_config.get("phone") or "")
            window.setCentralWidget(account)
            bridge = WorkerCommandBridge(profile_name, window, account)
            window._worker_bridge = bridge
            window.show()
            if "--hidden" in sys.argv:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, window.hide)
            account.request_load()
        else:
            # 主进程只管理账号；WebEngine 页面分别运行在独立子进程中。
            from app.window import MainWindow
            window = MainWindow()
            window.show()
        sys.exit(app.exec())
    except Exception as e:
        global_exception_handler(type(e), e, e.__traceback__)
