import ipaddress
import json
import socket
import threading
from urllib.parse import quote
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, pyqtSignal


class CountryResolver(QObject):
    resolved = pyqtSignal(str, str, str)

    def lookup(self, account_id, host):
        threading.Thread(
            target=self._resolve,
            args=(account_id, host),
            daemon=True,
        ).start()

    def _resolve(self, account_id, host):
        try:
            ip = self._resolve_ip(host)
            parsed = ipaddress.ip_address(ip)
            if parsed.is_private or parsed.is_loopback:
                self.resolved.emit(account_id, "LAN", "本地网络")
                return

            request = Request(
                f"https://ipwho.is/{quote(ip, safe=':')}",
                headers={"User-Agent": "WhatsAppClient/1.0"},
            )
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not data.get("success", True):
                raise ValueError(data.get("message", "lookup failed"))
            code = str(data.get("country_code") or "").upper()
            country = str(data.get("country") or code or "未知")
            self.resolved.emit(account_id, code or "--", country)
        except (OSError, ValueError, json.JSONDecodeError):
            self.resolved.emit(account_id, "--", "国家未知")

    @staticmethod
    def _resolve_ip(host):
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if not results:
                raise OSError("DNS lookup failed")
            return results[0][4][0]


def country_flag(code):
    code = (code or "").upper()
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code)
