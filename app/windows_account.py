import ctypes
from ctypes import wintypes
import json
import os
import sys
import time
import uuid

from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from app.config import get_base_storage_dir, get_instance_name


def _windows_user32():
    """返回已声明 64 位安全签名的 user32 API。"""
    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND
    user32.GetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetParent.argtypes = [hwnd, hwnd]
    user32.SetParent.restype = hwnd
    user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [hwnd]
    user32.SetFocus.restype = hwnd
    return user32


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


class WindowsNativeHost(QWidget):
    """使用 Win32 API 将另一个进程的顶层 HWND 嵌入此控件。"""

    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_CLIPCHILDREN = 0x02000000
    WS_CLIPSIBLINGS = 0x04000000
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    SW_SHOWNA = 8
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020

    def __init__(self, hwnd, parent=None):
        super().__init__(parent)
        self.hwnd = int(hwnd)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._attach()

    def _attach(self):
        if sys.platform != "win32" or not self.hwnd:
            return
        user32 = _windows_user32()
        host_hwnd = int(self.winId())
        get_style = user32.GetWindowLongPtrW
        set_style = user32.SetWindowLongPtrW
        style = int(get_style(self.hwnd, self.GWL_STYLE))
        style &= ~(self.WS_POPUP | self.WS_CAPTION | self.WS_THICKFRAME)
        style |= self.WS_CHILD | self.WS_VISIBLE | self.WS_CLIPCHILDREN | self.WS_CLIPSIBLINGS
        set_style(self.hwnd, self.GWL_STYLE, style)
        exstyle = int(get_style(self.hwnd, self.GWL_EXSTYLE))
        exstyle = (exstyle & ~self.WS_EX_APPWINDOW) | self.WS_EX_TOOLWINDOW
        set_style(self.hwnd, self.GWL_EXSTYLE, exstyle)
        user32.SetParent(self.hwnd, host_hwnd)
        user32.ShowWindow(self.hwnd, self.SW_SHOWNA)
        self._fit_window()

    def _fit_window(self):
        if sys.platform != "win32" or not self.hwnd:
            return
        _windows_user32().SetWindowPos(
            self.hwnd,
            0,
            0,
            0,
            max(1, self.width()),
            max(1, self.height()),
            self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_window()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_window()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if sys.platform == "win32" and self.hwnd:
            _windows_user32().SetFocus(self.hwnd)


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
        self._container = None
        self._last_state = None
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
            self._container = WindowsNativeHost(hwnd, self)
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
        if note: self.browser_notification.emit("WhatsApp", note)


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
    def notification(self, title, message): self.state["notification"] = message or title; self.save()
    def load_status(self, text, progress, loaded):
        self.state["load_status"] = text
        self.state["load_progress"] = int(progress)
        self.state["loaded"] = bool(loaded)
        self.save()
