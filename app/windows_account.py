import json
import os
import sys
import time
import uuid
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from app.config import get_base_storage_dir, get_instance_name


def remove_window_from_taskbar(hwnd):
    """隐藏账号工作窗口的任务栏入口，不改变父窗口或渲染位置。"""
    if sys.platform != "win32" or not hwnd:
        return
    user32 = ctypes.windll.user32
    hwnd_type = wintypes.HWND
    user32.GetWindowLongPtrW.argtypes = [hwnd_type, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [hwnd_type, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        hwnd_type, hwnd_type, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    gwl_exstyle = -20
    ws_ex_appwindow = 0x00040000
    ws_ex_toolwindow = 0x00000080
    swp_flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
    style = int(user32.GetWindowLongPtrW(hwnd, gwl_exstyle))
    style = (style & ~ws_ex_appwindow) | ws_ex_toolwindow
    user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)


def ipc_path(profile, name):
    directory = os.path.join(get_base_storage_dir(), "ipc", profile)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name)


def write_state(profile, data):
    path = ipc_path(profile, "state.json")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)
    os.replace(temporary, path)


class _ProfileName:
    def __init__(self, name): self.name = name
    def storageName(self): return self.name


class WindowsAccountProcess(QWidget):
    unread_count_changed = pyqtSignal(int)
    browser_notification = pyqtSignal(str, str)
    phone_number_changed = pyqtSignal(str)

    def __init__(self, profile_name, proxy_url="", parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.profile = _ProfileName(profile_name)
        self.proxy_url = proxy_url
        self.phone_number = ""
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._restart = False
        self._foreign = None
        self._container = None
        self._last_state = None
        self._last_notification_id = ""
        self._worker_token = ""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.label = QLabel("正在启动账号进程…")
        self.label.setStyleSheet(
            "background:#f7f8fa;color:#52606d;padding:8px 12px;font-size:13px;"
        )
        self.layout.addWidget(self.label)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFixedHeight(24)
        self.progress.setStyleSheet(
            "QProgressBar{border:0;background:#e6e9ec;color:#172b32;"
            "font-size:12px;font-weight:600;text-align:center;}"
            "QProgressBar::chunk{background:#25d366;}"
        )
        self.layout.addWidget(self.progress)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        # Windows 每个账号都有独立进程，启动后全部保持运行。
        QTimer.singleShot(0, self.request_load)

    def request_load(self):
        if self.process.state() != QProcess.ProcessState.NotRunning: return
        self._worker_token = uuid.uuid4().hex
        self._last_state = None
        self._last_notification_id = ""
        try:
            os.unlink(ipc_path(self.profile_name, "state.json"))
        except OSError:
            pass
        args = [
            "--windows-account-worker", self.profile_name,
            "--instance", get_instance_name(),
            "--worker-token", self._worker_token,
        ]
        if getattr(sys, "frozen", False):
            self.process.start(sys.executable, args)
        else:
            main = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
            self.process.start(sys.executable, [main] + args)

    def restart(self):
        self._restart = True
        self.terminate()

    def terminate(self):
        if self.process.state() == QProcess.ProcessState.NotRunning: return
        self.process.terminate()
        if not self.process.waitForFinished(3000):
            self.process.kill(); self.process.waitForFinished(1000)

    def cancel_pending_load(self): pass
    def stop(self): pass
    def setUrl(self, _url): pass

    def _finished(self):
        if self._container:
            self._container.deleteLater(); self._container = None
        self._foreign = None
        if self._restart:
            self._restart = False
            QTimer.singleShot(300, self.request_load)
        else:
            self.label.setText("账号进程已退出，请点击刷新当前")
            self.label.show()
            self.progress.setValue(0)
            self.progress.show()

    def _process_error(self, _error):
        self.label.setText("账号进程启动失败，请点击刷新当前")
        self.label.show()
        self.progress.setValue(0)
        self.progress.show()

    def _poll(self):
        try:
            with open(ipc_path(self.profile_name, "state.json"), encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, ValueError): return
        # 忽略旧进程残留状态。单文件 PyInstaller 存在启动器和应用两个
        # PID，因此使用显式令牌而不是 PID 判断进程归属。
        if str(state.get("worker_token") or "") != self._worker_token:
            return
        if state == self._last_state: return
        self._last_state = state
        hwnd = int(state.get("hwnd") or 0)
        if hwnd and self._container is None:
            # 保持最初已验证可用的 Qt 外部窗口嵌入方式。工作窗口必须先
            # 正常创建并显示，Qt WebEngine 才能建立可渲染的原生表面。
            self._foreign = QWindow.fromWinId(hwnd)
            self._container = QWidget.createWindowContainer(self._foreign, self)
            self._container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            # 页面占据上方主体区域，加载状态与进度条固定显示在下方。
            self.layout.insertWidget(0, self._container, 1)
            self._container.show()
        status = str(state.get("load_status") or "正在启动账号进程…")
        progress = max(0, min(100, int(state.get("load_progress") or 0)))
        loaded = bool(state.get("loaded"))
        self.label.setText(status)
        self.progress.setValue(progress)
        self.label.setVisible(not loaded)
        self.progress.setVisible(not loaded)
        phone = str(state.get("phone") or "")
        if phone and phone != self.phone_number:
            self.phone_number = phone; self.phone_number_changed.emit(phone)
        self.unread_count_changed.emit(int(state.get("unread") or 0))
        note = str(state.get("notification") or "")
        notification_id = str(state.get("notification_id") or "")
        if note and notification_id and notification_id != self._last_notification_id:
            self._last_notification_id = notification_id
            self.browser_notification.emit("WhatsApp", note)


class WindowsWorkerState:
    def __init__(self, profile, window, account, worker_token=""):
        self.profile, self.window = profile, window
        self.state = {
            "pid": os.getpid(),
            "worker_token": worker_token,
            "hwnd": int(window.winId()),
            "phone": "",
            "unread": 0,
            "notification": "",
            "notification_id": "",
            "load_status": "正在启动账号进程…",
            "load_progress": 0,
            "loaded": False,
        }
        account.phone_number_changed.connect(self.phone)
        account.unread_count_changed.connect(self.unread)
        account.browser_notification.connect(self.notification)
        account.load_status_changed.connect(self.load_status)
        self.save()
    def save(self):
        self.state["updated_at"] = time.time(); write_state(self.profile, self.state)
    def phone(self, value): self.state["phone"] = value; self.save()
    def unread(self, value): self.state["unread"] = value; self.save()
    def notification(self, title, message):
        self.state["notification"] = message or title
        self.state["notification_id"] = uuid.uuid4().hex
        self.save()
    def load_status(self, text, progress, loaded):
        self.state["load_status"] = text
        self.state["load_progress"] = int(progress)
        self.state["loaded"] = bool(loaded)
        self.save()
