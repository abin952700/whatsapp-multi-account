import os
import platform

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtNetwork import QNetworkProxy

from app.config import WHATSAPP_WEB_URL, get_base_storage_dir, get_icon_path

ALLOWED_DOMAINS = [
    "web.whatsapp.com",
    "whatsapp.com",
    "faq.whatsapp.com",
    "status.whatsapp.com",
    "whatsapp.net",
]


class WhatsAppWebPage(QWebEnginePage):
    external_url_requested = pyqtSignal(QUrl)

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if self._is_internal_scheme(url):
            return True

        if not self._is_whatsapp_domain(url):
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                self.external_url_requested.emit(url)
                return False

        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def _is_whatsapp_domain(self, url):
        domain = url.host()
        return any(
            domain == item or domain.endswith(f".{item}")
            for item in ALLOWED_DOMAINS
        )

    def _is_internal_scheme(self, url):
        return url.scheme().lower() in {"about", "blob", "data"}

    def createWindow(self, _type):
        page = QWebEnginePage(self.profile(), self)
        page.urlChanged.connect(lambda url, p=page: self._handle_new_window_url(p, url))
        return page

    def _handle_new_window_url(self, page, url):
        if self._is_internal_scheme(url):
            return
        if not self._is_whatsapp_domain(url):
            self.external_url_requested.emit(url)
            page.deleteLater()
            return
        self.setUrl(url)
        page.deleteLater()


def build_user_agent():
    if platform.system() == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
    if platform.system() == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )


class WhatsAppAccount(QWebEngineView):
    def __init__(self, profile_name, proxy_url=None):
        super().__init__()

        # 保存代理信息，供持久化 JSON 使用
        self.proxy_url = proxy_url

        # 1. 在创建 Profile 之前，先设置全局代理
        if proxy_url:
            self._apply_global_proxy(proxy_url)
        else:
            # 如果不需要代理，清理可能残留的全局代理
            QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))

        # 2. 配置存储路径
        storage_path = os.path.join(get_base_storage_dir(), profile_name)
        os.makedirs(storage_path, exist_ok=True)

        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 3. 创建并配置 Profile
        self.profile = QWebEngineProfile(profile_name, self)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        self.profile.downloadRequested.connect(self._on_download_requested)
        self.profile.setHttpUserAgent(build_user_agent())

        # 4. 创建 Page
        page = WhatsAppWebPage(self.profile, self)
        page.external_url_requested.connect(self._open_external_url)
        page.permissionRequested.connect(self._handle_permission)
        
        # 必须等 Page 创建后，再绑定代理认证信号
        page.proxyAuthenticationRequired.connect(self._handle_proxy_auth)
        
        self.setPage(page)
        self.setUrl(QUrl(WHATSAPP_WEB_URL))

    def _apply_global_proxy(self, proxy_url_str):
        """解析代理链接并设置为应用级代理"""
        if "://" not in proxy_url_str:
            proxy_url_str = "http://" + proxy_url_str

        proxy_url = QUrl(proxy_url_str)
        proxy = QNetworkProxy()

        scheme = proxy_url.scheme().lower()
        if scheme == "socks5":
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
        else:
            proxy.setType(QNetworkProxy.ProxyType.HttpProxy)

        proxy.setHostName(proxy_url.host())
        proxy.setPort(proxy_url.port())

        # 解析认证信息
        if "@" in proxy_url_str:
            auth_part = proxy_url_str.split("://")[-1].split("@")[0]
            if ":" in auth_part:
                user, pwd = auth_part.split(":", 1)
                proxy.setUser(user)
                proxy.setPassword(pwd)
        elif proxy_url.userName():
            proxy.setUser(proxy_url.userName())
            proxy.setPassword(proxy_url.password())

        # 设置为全局代理
        QNetworkProxy.setApplicationProxy(proxy)

    def _handle_proxy_auth(self, url, authenticator, proxy):
        """处理代理服务器的密码验证"""
        app_proxy = QNetworkProxy.applicationProxy()
        if app_proxy.user():
            authenticator.setUser(app_proxy.user())
            authenticator.setPassword(app_proxy.password())

    def _handle_permission(self, permission):
        """自动允许麦克风/摄像头，其他权限拒绝。"""
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePermission
            ptype = permission.permissionType()
            allow_types = {
                QWebEnginePermission.PermissionType.MediaAudioCapture,
                QWebEnginePermission.PermissionType.MediaVideoCapture,
                QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
            }
            if ptype in allow_types:
                permission.grant()
            else:
                permission.deny()
        except Exception:
            try:
                permission.grant()
            except Exception:
                pass

    def _open_external_url(self, url):
        QDesktopServices.openUrl(url)

    def _on_download_requested(self, download):
        downloads_path = os.path.expanduser("~/Downloads/WhatsApp")
        os.makedirs(downloads_path, exist_ok=True)
        filename = download.downloadFileName() or "whatsapp-download"
        download.setDownloadDirectory(downloads_path)
        download.setDownloadFileName(filename)
        download.accept()