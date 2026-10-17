import json
import re
import threading
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PyQt6.QtCore import QObject, pyqtSignal

from app.config import APP_VERSION, GITHUB_API_URL


def version_tuple(value):
    match = re.findall(r"\d+", value)
    return tuple(int(x) for x in match) if match else (0,)


class UpdateChecker(QObject):
    update_available = pyqtSignal(str)
    no_update = pyqtSignal()
    check_failed = pyqtSignal()

    def run(self):
        try:
            req = Request(GITHUB_API_URL, headers={"User-Agent": "WhatsAppClient"})
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("prerelease") or data.get("draft"):
                self.no_update.emit()
                return

            latest_tag = data.get("tag_name", "").strip()
            if not latest_tag:
                self.no_update.emit()
                return
            if version_tuple(latest_tag) > version_tuple(APP_VERSION):
                self.update_available.emit(latest_tag)
                return

            self.no_update.emit()
        except (URLError, HTTPError, ValueError, TimeoutError):
            self.check_failed.emit()


def start_update_check(checker):
    """在后台线程里启动更新检查。"""
    thread = threading.Thread(target=checker.run, daemon=True)
    thread.start()