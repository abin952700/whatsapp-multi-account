import json
import os
import sys
import time

from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.config import get_base_storage_dir


def _ipc_dir(profile_name):
    path = os.path.join(get_base_storage_dir(), "ipc", profile_name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def state_path(profile_name):
    return os.path.join(_ipc_dir(profile_name), "state.json")


def command_path(profile_name):
    return os.path.join(_ipc_dir(profile_name), "command.json")


def write_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False)
    os.replace(temporary, path)


class AccountProcessPanel(QWidget):
    state_changed = pyqtSignal(str, dict)

    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self._last_state = None
        self._restart_pending = False
        self._restart_visible = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._drain_output)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label = QLabel("账号进程尚未启动")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        self.open_button = QPushButton("打开账号窗口")
        self.open_button.clicked.connect(self.show_account)
        layout.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self._poll_state)
        self.poll_timer.start()

    def start(self, hidden=True):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        # 覆盖上一个进程留下的 quit/hide 命令，避免新进程启动后立即退出。
        write_json(
            command_path(self.profile_name),
            {"command": "boot", "time": time.time_ns()},
        )
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = ["--account-worker", self.profile_name]
        else:
            program = sys.executable
            main_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
            arguments = [main_path, "--account-worker", self.profile_name]
        if hidden:
            arguments.append("--hidden")
        self.status_label.setText("正在启动独立账号进程…")
        self.process.start(program, arguments)

    def show_account(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.start(hidden=False)
            return
        write_json(command_path(self.profile_name), {"command": "show", "time": time.time_ns()})

    def hide_account(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            write_json(command_path(self.profile_name), {"command": "hide", "time": time.time_ns()})

    def restart(self):
        self._restart_pending = True
        self._restart_visible = True
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._restart_pending = False
            self.start(hidden=False)
            return
        self._stop_process()

    def terminate(self):
        self._restart_pending = False
        self._restart_visible = False
        self._stop_process()

    def _stop_process(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        write_json(command_path(self.profile_name), {"command": "quit", "time": time.time_ns()})
        self.process.waitForFinished(1500)
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            self.process.waitForFinished(1500)
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1500)

    def _poll_state(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        try:
            with open(state_path(self.profile_name), "r", encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, ValueError):
            return
        if state == self._last_state:
            return
        self._last_state = state
        status = str(state.get("status") or "运行中")
        self.status_label.setText(f"独立账号进程：{status}\n点击下方按钮打开窗口")
        self.state_changed.emit(self.profile_name, state)

    def _on_finished(self):
        self.status_label.setText("账号进程已退出，点击按钮重新打开")
        if self._restart_pending:
            visible = self._restart_visible
            self._restart_pending = False
            self._restart_visible = False
            QTimer.singleShot(300, lambda: self.start(hidden=not visible))

    def _drain_output(self):
        data = bytes(self.process.readAllStandardOutput())
        if not data:
            return
        path = os.path.join(_ipc_dir(self.profile_name), "worker.log")
        try:
            with open(path, "ab") as file:
                file.write(data)
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _on_process_error(self, error):
        self.status_label.setText(f"账号进程启动失败：{error.name}")


class WorkerCommandBridge:
    def __init__(self, profile_name, window, account):
        self.profile_name = profile_name
        self.window = window
        self.account = account
        self._last_command_time = 0
        self.state = {"status": "正在加载", "phone": "", "unread": 0, "notification": ""}
        account.phone_number_changed.connect(self._phone_changed)
        account.unread_count_changed.connect(self._unread_changed)
        account.browser_notification.connect(self._notification)
        account.loadFinished.connect(self._loaded)
        self.timer = QTimer(window)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._poll_command)
        self.timer.start()
        self._write_state()

    def _write_state(self):
        self.state["updated_at"] = time.time()
        write_json(state_path(self.profile_name), self.state)

    def _phone_changed(self, phone):
        self.state["phone"] = phone
        self._write_state()

    def _unread_changed(self, count):
        self.state["unread"] = count
        self._write_state()

    def _notification(self, title, message):
        self.state["notification"] = message or title
        self._write_state()

    def _loaded(self, success):
        self.state["status"] = "在线" if success else "加载失败"
        self._write_state()

    def _poll_command(self):
        try:
            with open(command_path(self.profile_name), "r", encoding="utf-8") as file:
                command = json.load(file)
        except (OSError, ValueError):
            return
        command_time = int(command.get("time") or 0)
        if command_time <= self._last_command_time:
            return
        self._last_command_time = command_time
        action = command.get("command")
        if action == "show":
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        elif action == "hide":
            self.window.hide()
        elif action == "quit":
            self.window.close()
