import json
from http.client import HTTPResponse
import ssl
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from app.proxy_extension import open_proxy_tunnel


class CountryResolver(QObject):
    resolved = pyqtSignal(str, str, str)

    def lookup(self, account_id, proxy_url):
        threading.Thread(
            target=self._resolve,
            args=(account_id, proxy_url),
            daemon=True,
        ).start()

    def _resolve(self, account_id, proxy_url):
        try:
            connection = open_proxy_tunnel(proxy_url, "ipwho.is", 443)
            try:
                context = ssl.create_default_context()
                tls = context.wrap_socket(connection, server_hostname="ipwho.is")
                tls.sendall(
                    b"GET / HTTP/1.1\r\n"
                    b"Host: ipwho.is\r\n"
                    b"User-Agent: WhatsAppClient/1.0\r\n"
                    b"Accept: application/json\r\n"
                    b"Connection: close\r\n\r\n"
                )
                response = HTTPResponse(tls)
                response.begin()
                if response.status != 200:
                    raise OSError(f"IP 查询返回 HTTP {response.status}")
                data = json.loads(response.read().decode("utf-8"))
                tls.close()
            finally:
                connection.close()
            if not data.get("success", True):
                raise ValueError(data.get("message", "lookup failed"))
            code = str(data.get("country_code") or "").upper()
            country = str(data.get("country") or code or "未知")
            self.resolved.emit(account_id, code or "--", country)
        except (OSError, ValueError, ssl.SSLError, json.JSONDecodeError):
            self.resolved.emit(account_id, "--", "国家未知")


def country_flag(code):
    code = (code or "").upper()
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code)
