import sys
import os
import traceback
import datetime

# 关键：必须在 QApplication 创建之前导入
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from app.config import get_icon_path

# 获取当前运行目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "crash.log")


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

# --- QtWebEngine 防崩溃/日志捕获设置 ---
# 禁用 GPU 沙盒，解决部分环境下的闪退，并把 JS console 里的错误隐藏，避免刷屏
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu-sandbox --enable-logging --log-level=1"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 注意：MainWindow 的导入可以留在这里，但上面那行 import 已经保证 WebEngine 被提前加载了
    from app.window import MainWindow
    
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        global_exception_handler(type(e), e, e.__traceback__)