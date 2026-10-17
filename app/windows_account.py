import json
import os
import sys
import time
import uuid

from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.config import get_base_storage_dir, get_instance_name


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
        self._worker_token = ""
        self.layout = QVBoxLayout(self)
        self.label = QLabel("正在启动账号进程…")
        self.layout.addWidget(self.label)
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
        self._foreign = None
        if self._restart:
            self._restart = False
            QTimer.singleShot(300, self.request_load)
        else:
            self.label.setText("账号进程已退出，请点击刷新当前")
            self.label.show()

    def _process_error(self, _error):
        self.label.setText("账号进程启动失败，请点击刷新当前")
        self.label.show()

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
            self._foreign = QWindow.fromWinId(hwnd)
            self._container = QWidget.createWindowContainer(self._foreign, self)
            self._container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.layout.replaceWidget(self.label, self._container)
            self.label.hide()
            self._container.show()
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
        }
        account.phone_number_changed.connect(self.phone)
        account.unread_count_changed.connect(self.unread)
        account.browser_notification.connect(self.notification)
        self.save()
    def save(self):
        self.state["updated_at"] = time.time(); write_state(self.profile, self.state)
    def phone(self, value): self.state["phone"] = value; self.save()
    def unread(self, value): self.state["unread"] = value; self.save()
    def notification(self, title, message): self.state["notification"] = message or title; self.save()
