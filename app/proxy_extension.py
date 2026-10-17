from dataclasses import dataclass
import base64
import select
import socket
import socketserver
import ssl
import threading
from urllib.parse import unquote, urlsplit

from PyQt6.QtCore import QUrl
from PyQt6.QtNetwork import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery


@dataclass(frozen=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""


_gateway_lock = threading.Lock()
_gateway = None


def parse_proxy_url(value):
    """Parse and validate an HTTP/HTTPS/SOCKS5 proxy URL."""
    value = (value or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "socks5"}:
        raise ValueError("仅支持 http、https 和 socks5 代理")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理端口无效") from exc
    if port is None:
        port = 1080 if scheme == "socks5" else 443 if scheme == "https" else 80

    return ProxyConfig(
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def apply_application_proxy(value):
    """让 Chromium 连接本地网关，由网关使用账号自己的上游代理。"""
    config = parse_proxy_url(value)
    if config is None:
        _stop_gateway()
        QNetworkProxy.setApplicationProxy(
            QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)
        )
        return None

    gateway = _start_gateway(config)
    proxy = QNetworkProxy(
        QNetworkProxy.ProxyType.HttpProxy, "127.0.0.1", gateway.server_address[1]
    )
    QNetworkProxy.setApplicationProxy(proxy)
    return config


def apply_proxy_mode(mode, value=None):
    """按账号配置应用直连、系统代理或指定代理。"""
    if mode == "system":
        _stop_gateway()
        QNetworkProxyFactory.setUseSystemConfiguration(True)
        proxies = QNetworkProxyFactory.systemProxyForQuery(
            QNetworkProxyQuery(QUrl("https://web.whatsapp.com"))
        )
        proxy = proxies[0] if proxies else QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)
        QNetworkProxy.setApplicationProxy(proxy)
        return proxy

    QNetworkProxyFactory.setUseSystemConfiguration(False)
    if mode == "none":
        return apply_application_proxy(None)
    return apply_application_proxy(value)


class _ThreadingProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, upstream):
        self.upstream = upstream
        self.connections = set()
        self.connections_lock = threading.Lock()
        super().__init__(address, _LocalProxyHandler)

    def track(self, connection):
        with self.connections_lock:
            self.connections.add(connection)

    def untrack(self, connection):
        with self.connections_lock:
            self.connections.discard(connection)

    def close_connections(self):
        with self.connections_lock:
            connections = list(self.connections)
            self.connections.clear()
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass


class _LocalProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        self.server.track(self.request)
        try:
            header = _recv_headers(self.request)
            first_line = header.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            parts = first_line.split(" ", 2)
            if len(parts) != 3 or parts[0].upper() != "CONNECT":
                self.request.sendall(
                    b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n"
                )
                return
            host, port = _split_connect_target(parts[1])
            upstream = _open_upstream_tunnel(self.server.upstream, host, port)
            self.server.track(upstream)
            self.request.sendall(
                b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: WhatsAppClient\r\n\r\n"
            )
            _relay(self.request, upstream)
        except (OSError, ValueError):
            try:
                self.request.sendall(
                    b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
        finally:
            self.server.untrack(self.request)
            if upstream is not None:
                self.server.untrack(upstream)
                try:
                    upstream.close()
                except OSError:
                    pass


def _start_gateway(config):
    global _gateway
    with _gateway_lock:
        if _gateway is not None:
            _stop_gateway_locked()
        server = _ThreadingProxyServer(("127.0.0.1", 0), config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        server._thread = thread
        _gateway = server
        return server


def _stop_gateway():
    with _gateway_lock:
        _stop_gateway_locked()


def _stop_gateway_locked():
    global _gateway
    if _gateway is None:
        return
    server = _gateway
    _gateway = None
    server.close_connections()
    server.shutdown()
    server.server_close()


def _recv_headers(connection, limit=65536):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise OSError("连接提前关闭")
        data.extend(chunk)
        if len(data) > limit:
            raise OSError("代理请求头过大")
    return bytes(data)


def _split_connect_target(target):
    parsed = urlsplit("//" + target)
    if not parsed.hostname:
        raise ValueError("CONNECT 目标无效")
    return parsed.hostname, parsed.port or 443


def _resolved_target(host, port):
    addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not addresses:
        raise OSError(f"无法解析 {host}")
    return addresses[0][4][0], port


def _open_upstream_tunnel(config, host, port):
    target_ip, target_port = _resolved_target(host, port)
    connection = socket.create_connection((config.host, config.port), timeout=15)
    connection.settimeout(30)
    try:
        if config.scheme == "https":
            context = ssl.create_default_context()
            connection = context.wrap_socket(connection, server_hostname=config.host)
        if config.scheme == "socks5":
            _socks5_connect(connection, config, target_ip, target_port)
        else:
            _http_connect(connection, config, target_ip, target_port, host)
        connection.settimeout(None)
        return connection
    except Exception:
        connection.close()
        raise


def open_proxy_tunnel(value, host, port=443):
    """通过指定账号代理建立 TCP 隧道，供出口 IP/国家检测复用。"""
    config = parse_proxy_url(value)
    if config is None:
        raise ValueError("代理地址为空")
    return _open_upstream_tunnel(config, host, port)


def _socks5_connect(connection, config, target_ip, target_port):
    methods = b"\x00\x02" if config.username else b"\x00"
    connection.sendall(bytes((5, len(methods))) + methods)
    version, method = _recv_exact(connection, 2)
    if version != 5 or method == 0xFF:
        raise OSError("SOCKS5 认证方式被拒绝")
    if method == 2:
        username = config.username.encode("utf-8")
        password = config.password.encode("utf-8")
        if len(username) > 255 or len(password) > 255:
            raise ValueError("SOCKS5 用户名或密码过长")
        connection.sendall(
            bytes((1, len(username))) + username + bytes((len(password),)) + password
        )
        if _recv_exact(connection, 2) != b"\x01\x00":
            raise OSError("SOCKS5 用户名或密码错误")
    connection.sendall(
        b"\x05\x01\x00\x01" + socket.inet_aton(target_ip) + target_port.to_bytes(2, "big")
    )
    version, status, _reserved, address_type = _recv_exact(connection, 4)
    if version != 5 or status != 0:
        raise OSError(f"SOCKS5 上游拒绝连接：0x{status:02x}")
    address_size = {1: 4, 4: 16}.get(address_type)
    if address_type == 3:
        address_size = _recv_exact(connection, 1)[0]
    if address_size is None:
        raise OSError("SOCKS5 返回地址无效")
    _recv_exact(connection, address_size + 2)


def _http_connect(connection, config, target_ip, target_port, original_host):
    headers = [
        f"CONNECT {target_ip}:{target_port} HTTP/1.1",
        f"Host: {original_host}:{target_port}",
        "Proxy-Connection: Keep-Alive",
    ]
    if config.username:
        credentials = base64.b64encode(
            f"{config.username}:{config.password}".encode("utf-8")
        ).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {credentials}")
    connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1"))
    response = _recv_headers(connection)
    status_line = response.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or parts[1] != "200":
        raise OSError(f"HTTP 上游拒绝连接：{status_line}")


def _relay(left, right):
    sockets = (left, right)
    while True:
        readable, _, exceptional = select.select(sockets, (), sockets, 60)
        if exceptional:
            return
        if not readable:
            continue
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            (right if source is left else left).sendall(data)


def test_proxy_connection(value, target_host="web.whatsapp.com", target_port=443, timeout=10):
    """通过代理建立到目标站点的隧道，返回 (成功, 中文说明)。"""
    config = parse_proxy_url(value)
    if config is None:
        return True, "直连"

    try:
        connection = socket.create_connection((config.host, config.port), timeout=timeout)
        connection.settimeout(timeout)
        if config.scheme == "https":
            context = ssl.create_default_context()
            connection = context.wrap_socket(connection, server_hostname=config.host)

        with connection:
            if config.scheme == "socks5":
                return _test_socks5(connection, config, target_host, target_port)
            return _test_http_proxy(connection, config, target_host, target_port)
    except socket.timeout:
        return False, "连接代理服务器超时"
    except socket.gaierror:
        return False, "无法解析代理服务器地址"
    except ssl.SSLError as exc:
        return False, f"HTTPS 代理证书或 TLS 错误：{exc}"
    except OSError as exc:
        return False, f"无法连接代理服务器：{exc}"


def _recv_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise OSError("代理服务器提前断开连接")
        data.extend(chunk)
    return bytes(data)


def _test_socks5(connection, config, target_host, target_port):
    methods = b"\x00\x02" if config.username else b"\x00"
    connection.sendall(bytes((5, len(methods))) + methods)
    version, method = _recv_exact(connection, 2)
    if version != 5 or method == 0xFF:
        return False, "SOCKS5 代理不接受可用的认证方式"
    if method == 2:
        username = config.username.encode("utf-8")
        password = config.password.encode("utf-8")
        if len(username) > 255 or len(password) > 255:
            return False, "SOCKS5 用户名或密码过长"
        connection.sendall(bytes((1, len(username))) + username + bytes((len(password),)) + password)
        auth_version, status = _recv_exact(connection, 2)
        if auth_version != 1 or status != 0:
            return False, "SOCKS5 用户名或密码错误"

    try:
        target_ip = socket.gethostbyname(target_host)
    except socket.gaierror:
        return False, f"本机无法解析 {target_host}"
    connection.sendall(
        b"\x05\x01\x00\x01"
        + socket.inet_aton(target_ip)
        + target_port.to_bytes(2, "big")
    )
    version, status, _reserved, address_type = _recv_exact(connection, 4)
    if version != 5 or status != 0:
        known = {
            1: "代理服务器内部错误", 2: "代理规则不允许此连接",
            3: "代理无法到达目标网络", 4: "代理无法到达目标主机",
            5: "目标站点拒绝连接", 6: "代理连接已过期",
            7: "代理不支持 CONNECT", 8: "代理不支持该地址类型",
        }
        reason = known.get(status, f"代理商返回拒绝码 0x{status:02x}")
        return False, f"代理认证成功，但无法连接 {target_host}:{target_port}\n{reason}"

    address_size = {1: 4, 4: 16}.get(address_type)
    if address_type == 3:
        address_size = _recv_exact(connection, 1)[0]
    if address_size is None:
        return False, "SOCKS5 代理返回了无效地址"
    _recv_exact(connection, address_size + 2)
    return True, "代理连接正常"


def _test_http_proxy(connection, config, target_host, target_port):
    headers = [
        f"CONNECT {target_host}:{target_port} HTTP/1.1",
        f"Host: {target_host}:{target_port}",
        "Proxy-Connection: Keep-Alive",
    ]
    if config.username:
        credentials = base64.b64encode(
            f"{config.username}:{config.password}".encode("utf-8")
        ).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {credentials}")
    connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
    response = bytearray()
    while b"\r\n" not in response and len(response) < 4096:
        response.extend(connection.recv(512))
    status_line = bytes(response).split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return False, "HTTP 代理返回了无效响应"
    status = int(parts[1])
    if status == 200:
        return True, "代理连接正常"
    if status == 407:
        return False, "HTTP 代理用户名或密码错误"
    return False, f"代理认证成功，但无法连接 {target_host}:{target_port}\nHTTP 状态码 {status}"
