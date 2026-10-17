import os
import re
import threading

from PyQt6.QtCore import QUrl, pyqtSignal, Qt, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEnginePage,
    QWebEnginePermission,
    qWebEngineChromiumVersion,
)
from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.config import WHATSAPP_WEB_URL, get_base_storage_dir, get_icon_path
from app.proxy_extension import parse_proxy_url, test_proxy_connection

ALLOWED_DOMAINS = [
    "web.whatsapp.com",
    "whatsapp.com",
    "faq.whatsapp.com",
    "status.whatsapp.com",
    "whatsapp.net",
]


def chrome_user_agent():
    """使用内置 Chromium 的真实版本，隐藏 Qt WebEngine 专用标识。"""
    chromium_version = qWebEngineChromiumVersion() or "134.0.0.0"
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chromium_version} Safari/537.36"
    )


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


class WhatsAppAccount(QWebEngineView):
    proxy_check_finished = pyqtSignal(int, bool, str)
    load_status_changed = pyqtSignal(str, int, bool)
    unread_count_changed = pyqtSignal(int)
    browser_notification = pyqtSignal(str, str)
    phone_number_changed = pyqtSignal(str)

    def __init__(self, profile_name, proxy_url=None):
        super().__init__()

        # 保存代理信息，供持久化 JSON 使用
        self.proxy_url = proxy_url

        self.proxy_config = parse_proxy_url(proxy_url)

        # 配置存储路径
        storage_path = os.path.join(get_base_storage_dir(), profile_name)
        os.makedirs(storage_path, exist_ok=True)
        cache_path = os.path.join(storage_path, "cache")
        os.makedirs(cache_path, exist_ok=True)
        self.storage_path = storage_path

        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 每个账号使用独立 Profile，持久化 Cookie 和站点数据。
        self.profile = QWebEngineProfile(profile_name, self)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setCachePath(cache_path)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk
        )
        notification_permission = self.profile.queryPermission(
            QUrl(WHATSAPP_WEB_URL),
            QWebEnginePermission.PermissionType.Notifications,
        )
        if notification_permission.state() == QWebEnginePermission.State.Denied:
            notification_permission.reset()
        self.profile.setHttpUserAgent(chrome_user_agent())
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        self.profile.downloadRequested.connect(self._on_download_requested)
        self.profile.setNotificationPresenter(self._present_notification)
        self._notifications = []

        # 创建 Page
        page = WhatsAppWebPage(self.profile, self)
        page.external_url_requested.connect(self._open_external_url)
        page.permissionRequested.connect(self._handle_permission)
        page.proxyAuthenticationRequired.connect(self._handle_proxy_auth)
        page.titleChanged.connect(self._on_title_changed)
        
        self.setPage(page)
        self._setup_loading_overlay()
        self.loadStarted.connect(self._on_load_started)
        self.loadProgress.connect(self._on_load_progress)
        self.loadFinished.connect(self._on_load_finished)
        self.proxy_check_finished.connect(self._on_proxy_check_finished)
        self._proxy_check_token = 0
        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.setInterval(45_000)
        self._load_timeout.timeout.connect(self._on_load_timeout)
        self._timed_out = False
        self._page_loaded = False
        self._proxy_warning = ""
        self.phone_number = ""
        self._phone_timer = QTimer(self)
        self._phone_timer.setInterval(15_000)
        self._phone_timer.timeout.connect(self._detect_phone_number)
        self._loading_label.setText("选择账号后加载 WhatsApp")

    def _setup_loading_overlay(self):
        self._loading_overlay = QFrame(self)
        self._loading_overlay.setObjectName("loading_overlay")
        layout = QVBoxLayout(self._loading_overlay)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._loading_label = QLabel("正在加载 WhatsApp…")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setObjectName("loading_label")
        layout.addWidget(self._loading_label)

        self._retry_button = QPushButton("重新加载")
        self._retry_button.setFixedWidth(120)
        self._retry_button.clicked.connect(self._retry_load)
        self._retry_button.hide()
        layout.addWidget(self._retry_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self._loading_overlay.setStyleSheet(
            """
            QFrame#loading_overlay { background: #f7f8fa; }
            QLabel#loading_label { color: #52606d; font-size: 15px; }
            QPushButton { background: #25d366; color: white; border: none;
                          border-radius: 6px; padding: 8px 18px; }
            QPushButton:hover { background: #1ebe5d; }
            """
        )
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _retry_load(self):
        self.request_load()

    def request_load(self):
        """先确认代理能访问 WhatsApp，再交给 WebEngine 加载。"""
        self._proxy_check_token += 1
        token = self._proxy_check_token
        self._proxy_warning = ""
        self._retry_button.hide()
        self._loading_label.setText("正在检测代理与 WhatsApp 的连接…")
        self.load_status_changed.emit("正在检测代理与 WhatsApp 的连接…", 0, False)
        self._loading_overlay.show()
        self._loading_overlay.raise_()
        if not self.proxy_url:
            self.setUrl(QUrl(WHATSAPP_WEB_URL))
            return
        threading.Thread(
            target=self._run_proxy_check,
            args=(token, self.proxy_url),
            daemon=True,
        ).start()
        # 代理预检只用于诊断，不能阻断真实 WebEngine 请求。Windows、VPN
        # 或高延迟住宅代理可能让 socket 预检超时，但 Chromium 链路仍可用。
        self.setUrl(QUrl(WHATSAPP_WEB_URL))

    def cancel_pending_load(self):
        self._proxy_check_token += 1
        self._load_timeout.stop()
        self._phone_timer.stop()

    def _run_proxy_check(self, token, proxy_url):
        try:
            success, message = test_proxy_connection(proxy_url)
        except (ValueError, OSError) as exc:
            success, message = False, str(exc)
        self.proxy_check_finished.emit(token, success, message)

    def _on_proxy_check_finished(self, token, success, message):
        if token != self._proxy_check_token:
            return
        if success:
            return
        if self._page_loaded:
            return
        # 预检是辅助诊断，不能覆盖 Chromium 的真实加载状态和进度。
        # 部分代理会拒绝探测连接，但允许浏览器的后续连接。
        self._proxy_warning = message

    def _handle_proxy_auth(self, _url, authenticator, _proxy_host):
        if self.proxy_config and self.proxy_config.username:
            authenticator.setUser(self.proxy_config.username)
            authenticator.setPassword(self.proxy_config.password)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.setGeometry(self.rect())

    def _on_load_started(self):
        self._timed_out = False
        self._page_loaded = False
        self._load_timeout.start()
        self._loading_label.setText("正在加载 WhatsApp…")
        self.load_status_changed.emit("正在加载 WhatsApp…", 0, False)
        self._retry_button.hide()
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _on_load_progress(self, progress):
        self._loading_label.setText(f"正在加载 WhatsApp… {progress}%")
        self.load_status_changed.emit(f"正在加载 WhatsApp… {progress}%", progress, False)

    def _on_load_finished(self, success):
        self._load_timeout.stop()
        if self._timed_out:
            return
        if success:
            self._page_loaded = True
            self.load_status_changed.emit("WhatsApp 加载完成", 100, True)
            self._loading_overlay.hide()
            self._phone_timer.start()
            QTimer.singleShot(2_000, self._detect_phone_number)
            return
        detail = f"\n代理诊断：{self._proxy_warning}" if self._proxy_warning else ""
        self._loading_label.setText(
            f"WhatsApp 页面加载失败\n请检查网络或代理设置{detail}"
        )
        self.load_status_changed.emit(
            f"WhatsApp 页面加载失败，请检查网络或代理设置{detail}".replace("\n", " "),
            100,
            False,
        )
        self._retry_button.show()
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _detect_phone_number(self):
        script = r"""
        (() => {
            const values = [];
            for (const storage of [window.localStorage, window.sessionStorage]) {
                try {
                    for (const key of ["last-wid", "last-wid-md", "lastWid", "lastWidMd"]) {
                        const value = storage.getItem(key);
                        if (value) values.push(value);
                    }
                    for (let i = 0; i < storage.length; i++) {
                        const key = storage.key(i);
                        if (/(?:^|[-_])(last|my|self)?[-_]?(wid|user)(?:$|[-_])/i.test(key || "")) {
                            values.push(storage.getItem(key) || "");
                        }
                    }
                } catch (_) {}
            }
            for (const value of values) {
                const decoded = (() => { try { return decodeURIComponent(value); } catch (_) { return value; } })();
                const match = decoded.match(/(?:^|[^0-9])(\d{7,15})(?::\d+)?@(c\.us|s\.whatsapp\.net)/);
                if (match) return match[1];
            }
            return "";
        })()
        """
        self.page().runJavaScript(script, self._on_phone_detected)

    def _on_phone_detected(self, number):
        digits = re.sub(r"\D", "", str(number or ""))
        if not 7 <= len(digits) <= 15 or digits == self.phone_number:
            return
        self.phone_number = digits
        self.phone_number_changed.emit(digits)

    def _on_load_timeout(self):
        self._timed_out = True
        self.stop()
        detail = f"\n代理诊断：{self._proxy_warning}" if self._proxy_warning else ""
        self._loading_label.setText(
            "WhatsApp 加载超时\nWebEngine 未完成加载" + detail
        )
        self.load_status_changed.emit(
            ("WhatsApp 加载超时：WebEngine 未完成加载" + detail).replace("\n", " "),
            100,
            False,
        )
        self._retry_button.show()
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _handle_permission(self, permission):
        """自动允许麦克风/摄像头，其他权限拒绝。"""
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePermission
            ptype = permission.permissionType()
            allow_types = {
                QWebEnginePermission.PermissionType.MediaAudioCapture,
                QWebEnginePermission.PermissionType.MediaVideoCapture,
                QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
                QWebEnginePermission.PermissionType.Notifications,
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

    def _on_title_changed(self, title):
        match = re.match(r"^\((\d+)\)", title or "")
        self.unread_count_changed.emit(int(match.group(1)) if match else 0)

    def _present_notification(self, notification):
        """保留通知对象，并把摘要同步给账号列表。"""
        self._notifications.append(notification)
        title = str(notification.title() or "WhatsApp")
        message = str(notification.message() or "")
        self.browser_notification.emit(title, message)
        notification.closed.connect(
            lambda n=notification: self._remove_notification(n)
        )
        notification.show()

    def _remove_notification(self, notification):
        if notification in self._notifications:
            self._notifications.remove(notification)

    def _open_external_url(self, url):
        QDesktopServices.openUrl(url)

    def _on_download_requested(self, download):
        downloads_path = os.path.expanduser("~/Downloads/WhatsApp")
        os.makedirs(downloads_path, exist_ok=True)
        filename = download.downloadFileName() or "whatsapp-download"
        download.setDownloadDirectory(downloads_path)
        download.setDownloadFileName(filename)
        download.accept()
