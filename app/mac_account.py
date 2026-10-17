import json
import os
import platform
import sys
import uuid

from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.account import WhatsAppAccount
from app.config import get_base_storage_dir, get_instance_name
from app.proxy_extension import apply_proxy_mode, parse_proxy_url


def ipc_path(profile):
    directory = os.path.join(get_base_storage_dir(), "ipc", profile)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "state.json")


class _ProfileName:
    def __init__(self, name):
        self.name = name

    def storageName(self):
        return self.name


class MacAccountRuntime(QWidget):
    """当前账号原生内嵌显示，其余账号由隐藏进程持续运行。"""

    unread_count_changed = pyqtSignal(int)
    browser_notification = pyqtSignal(str, str)
    phone_number_changed = pyqtSignal(str)

    def __init__(self, profile_name, proxy_url="", parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.profile = _ProfileName(profile_name)
        self.proxy_url = proxy_url or ""
        self.proxy_mode = "custom"
        self.custom_proxy_url = ""
        self.proxy_config = parse_proxy_url(self.proxy_url)
        self.phone_number = ""
        self._embedded = None
        self._active = False
        self._restart_background = False
        self._last_state = None
        self._last_notification_id = ""
        self._worker_token = ""

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("账号正在后台运行")
        self.layout.addWidget(self.label)

        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")
        self.process.setProcessEnvironment(environment)
        self.process.finished.connect(self._process_finished)
        self.timer = QTimer(self)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self._poll_state)
        self.timer.start()
        QTimer.singleShot(0, self.start_background)

    def _worker_args(self):
        return [
            "--background-account-worker", self.profile_name,
            "--instance", get_instance_name(),
            "--worker-token", self._worker_token,
        ]

    def start_background(self):
        if self._active or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            os.unlink(ipc_path(self.profile_name))
        except OSError:
            pass
        self._last_state = None
        self._last_notification_id = ""
        self._worker_token = uuid.uuid4().hex
        if getattr(sys, "frozen", False):
            self.process.start(sys.executable, self._worker_args())
        else:
            main = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
            self.process.start(sys.executable, [main] + self._worker_args())

    def request_load(self):
        if self._active and self._embedded is not None:
            return
        self._active = True
        self._stop_background()
        apply_proxy_mode(self.proxy_mode, self.proxy_url)
        account = WhatsAppAccount(self.profile_name, proxy_url=self.proxy_url)
        account.phone_number = self.phone_number
        account.unread_count_changed.connect(self.unread_count_changed)
        account.browser_notification.connect(self.browser_notification)
        account.phone_number_changed.connect(self._phone_changed)
        self._embedded = account
        self.layout.replaceWidget(self.label, account)
        self.label.hide()
        account.show()
        account.request_load()

    def deactivate(self):
        if not self._active:
            return
        self._active = False
        account = self._embedded
        self._embedded = None
        if account is not None:
            account.cancel_pending_load()
            account.stop()
            self.layout.replaceWidget(account, self.label)
            account.deleteLater()
        self.label.setText("账号正在后台运行")
        self.label.show()
        # 等待 WebEngineProfile 释放磁盘锁后再让后台进程接管。
        QTimer.singleShot(1200, self.start_background)

    def restart(self):
        if self._active:
            self.deactivate()
            self._active = True
            QTimer.singleShot(1400, self.request_load)
            return
        self._restart_background = True
        self._stop_background()

    def terminate(self):
        self._active = False
        if self._embedded is not None:
            self._embedded.cancel_pending_load()
            self._embedded.stop()
            self._embedded.deleteLater()
            self._embedded = None
        self._restart_background = False
        self._stop_background()

    def cancel_pending_load(self):
        if self._embedded is not None:
            self._embedded.cancel_pending_load()

    def stop(self):
        if self._embedded is not None:
            self._embedded.stop()

    def setUrl(self, url):
        if self._embedded is not None:
            self._embedded.setUrl(url)

    def _stop_background(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(5000):
            self.process.kill()
            self.process.waitForFinished(1500)

    def _process_finished(self):
        if self._restart_background and not self._active:
            self._restart_background = False
            QTimer.singleShot(400, self.start_background)

    def _phone_changed(self, phone):
        self.phone_number = str(phone or "")
        self.phone_number_changed.emit(self.phone_number)

    def _poll_state(self):
        if self._active or self.process.state() == QProcess.ProcessState.NotRunning:
            return
        try:
            with open(ipc_path(self.profile_name), encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, ValueError):
            return
        if platform.system() == "Windows":
            if str(state.get("worker_token") or "") != self._worker_token:
                return
        elif int(state.get("pid") or 0) != int(self.process.processId()):
            return
        if state == self._last_state:
            return
        self._last_state = state
        phone = str(state.get("phone") or "")
        if phone and phone != self.phone_number:
            self.phone_number = phone
            self.phone_number_changed.emit(phone)
        self.unread_count_changed.emit(int(state.get("unread") or 0))
        note = str(state.get("notification") or "")
        notification_id = str(state.get("notification_id") or "")
        if note and notification_id and notification_id != self._last_notification_id:
            self._last_notification_id = notification_id
            self.browser_notification.emit("WhatsApp", note)
