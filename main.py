import sys
import os
import platform
import json
import re
import threading
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PyQt6.QtCore import QUrl, QObject, pyqtSignal, Qt, QTimer, QEvent
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QMessageBox,
    QMenu,
    QToolButton,
    QWidget,
    QHBoxLayout,
    QPushButton,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtGui import QIcon, QDesktopServices, QAction

APP_VERSION = "1.0.1"
GITHUB_REPO = "sejanH/whatsapp-multi-account"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
WHATSAPP_WEB_URL = "https://web.whatsapp.com"
INACTIVE_UNLOAD_MS = 3 * 60 * 1000
TOP_BAR_HEIGHT = 32
ENABLE_LIFECYCLE_FREEZE = False


class WhatsAppWebPage(QWebEnginePage):
    external_url_requested = pyqtSignal(QUrl)

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        # List of WhatsApp domains allowed in-app
        self.allowed_domains = [
            'web.whatsapp.com',
            'whatsapp.com',
            'faq.whatsapp.com',
            'status.whatsapp.com',
            'whatsapp.net'
        ]
    
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # Allow internal non-http(s) schemes used by WebEngine
        if self._is_internal_scheme(url):
            return True

        # Open external links in system browser (only on user link clicks)
        if not self._is_whatsapp_domain(url):
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                self.external_url_requested.emit(url)
                return False

        # Allow navigation for WhatsApp pages
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)
    
    def _is_whatsapp_domain(self, url):
        """Check if URL belongs to WhatsApp domain."""
        domain = url.host()
        return any(
            domain == domain_item
            or domain.endswith(f".{domain_item}")
            for domain_item in self.allowed_domains
        )

    def _is_internal_scheme(self, url):
        scheme = url.scheme().lower()
        return scheme in {"about", "blob", "data"}

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
        # If WhatsApp tries to open a new window, keep it in the same view.
        self.setUrl(url)
        page.deleteLater()

def _version_tuple(value):
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
            if _version_tuple(latest_tag) > _version_tuple(APP_VERSION):
                self.update_available.emit(latest_tag)
                return

            self.no_update.emit()
        except (URLError, HTTPError, ValueError, TimeoutError):
            self.check_failed.emit()

class WhatsAppAccount(QWebEngineView):
    def __init__(self, profile_name):
        super().__init__()
        # 1. Create a unique profile for each account
        storage_path = os.path.expanduser(f"~/.config/whatsapp-pyqt/{profile_name}")
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)

        # Create the profile and set storage
        icon_path = os.path.join(os.path.dirname(__file__), 'whatsapp_icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.profile = QWebEngineProfile(profile_name, self)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        self.profile.downloadRequested.connect(self._on_download_requested)
        
        # Set User-Agent to modern Chrome
        user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        if platform.system() == "Darwin":
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        self.profile.setHttpUserAgent(user_agent)

        # 2. Assign the profile to the page
        page = WhatsAppWebPage(self.profile, self)
        page.external_url_requested.connect(self._open_external_url)
        self.setPage(page)
        
        self.setUrl(QUrl(WHATSAPP_WEB_URL))

    def _open_external_url(self, url):
        QDesktopServices.openUrl(url)

    def _on_download_requested(self, download):
        downloads_path = os.path.expanduser("~/Downloads/WhatsApp")
        os.makedirs(downloads_path, exist_ok=True)

        filename = download.downloadFileName() or "whatsapp-download"
        download.setDownloadDirectory(downloads_path)
        download.setDownloadFileName(filename)
        download.accept()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("WhatsApp Multi-Account")
        self.resize(1200, 900)

        self._update_checker = None
        self._manual_update_check = False
        self._update_check_in_progress = False
        self._inactive_timers = {}
        self._suspended_tabs = set()
        self._drag_active = False
        self._drag_offset = None

        # Create tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        # Add Account 1
        self.account1 = WhatsAppAccount("account_1")
        self.tabs.addTab(self.account1, "Personal")

        # Add Account 2
        self.account2 = WhatsAppAccount("account_2")
        self.tabs.addTab(self.account2, "Work / Business")

        self._setup_actions_menu()
        self._setup_top_bar_controls()
        self._balance_tab_resources(self.tabs.currentIndex())
        self._schedule_inactive_unload(self.tabs.currentIndex())
        self._check_for_updates()

    def _setup_actions_menu(self):
        self._actions_menu = QMenu(self)

        clear_cache = QAction("Clear Cache (Current Tab)", self)
        clear_cache.triggered.connect(self._clear_current_cache)
        self._actions_menu.addAction(clear_cache)

        open_downloads = QAction("Open Downloads Folder", self)
        open_downloads.triggered.connect(self._open_downloads)
        self._actions_menu.addAction(open_downloads)

        check_updates = QAction("Check for Updates", self)
        check_updates.triggered.connect(lambda: self._check_for_updates(manual=True))
        self._actions_menu.addAction(check_updates)

    def _setup_top_bar_controls(self):
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().installEventFilter(self)
        tab_height = TOP_BAR_HEIGHT
        button_height = tab_height
        self.tabs.tabBar().setFixedHeight(tab_height)

        self._corner_controls = QWidget(self.tabs)
        self._corner_controls.setObjectName("corner_controls")
        layout = QHBoxLayout(self._corner_controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._corner_controls.installEventFilter(self)
        self._corner_controls.setFixedHeight(tab_height)

        layout.addStretch()

        settings_btn = QToolButton(self._corner_controls)
        settings_btn.setText("⚙")
        settings_btn.setToolTip("Actions")
        settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_btn.setMenu(self._actions_menu)
        settings_btn.setFixedSize(32, button_height)
        settings_btn.setObjectName("title_control")
        layout.addWidget(settings_btn)

        min_btn = QPushButton("−", self._corner_controls)
        min_btn.setToolTip("Minimize")
        min_btn.setFixedSize(32, button_height)
        min_btn.setAutoDefault(False)
        min_btn.setDefault(False)
        min_btn.setObjectName("title_control")
        min_btn.clicked.connect(self.showMinimized)
        layout.addWidget(min_btn)

        self._max_btn = QPushButton("□", self._corner_controls)
        self._max_btn.setToolTip("Maximize")
        self._max_btn.setFixedSize(32, button_height)
        self._max_btn.setAutoDefault(False)
        self._max_btn.setDefault(False)
        self._max_btn.setObjectName("title_control")
        self._max_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self._max_btn)

        close_btn = QPushButton("×", self._corner_controls)
        close_btn.setToolTip("Close")
        close_btn.setFixedSize(32, button_height)
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
        close_btn.setObjectName("title_control")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.tabs.setCornerWidget(self._corner_controls, Qt.Corner.TopRightCorner)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                min-height: {tab_height}px;
                max-height: {tab_height}px;
                padding: 0px 12px;
                background: #2b2f36;
                color: #c0c5cc;
                border: none;
            }}
            QTabBar::tab:selected {{
                background: #1f6feb;
                color: #ffffff;
            }}
            QTabBar::tab:hover:!selected {{
                background: #363b44;
                color: #ffffff;
            }}
            """
        )
        self._corner_controls.setStyleSheet(
            """
            QWidget#corner_controls {
                border: none;
                background: transparent;
            }
            QToolButton, QPushButton {
                border: none;
                padding: 0px;
                border-radius: 0px;
                color: #c0c5cc;
                font-weight: 600;
                font-size:15px;
                outline: none;
            }
            QToolButton:hover, QPushButton:hover { background: #363b44; color: #ffffff; }
            QToolButton:pressed, QPushButton:pressed { background: #1f6feb; color: #ffffff; }
            QToolButton::menu-indicator { image: none; width: 0px; }
            """
        )

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self._max_btn.setText("□")
            self._max_btn.setToolTip("Maximize")
            return
        self.showMaximized()
        self._max_btn.setText("❐")
        self._max_btn.setToolTip("Restore")

    def eventFilter(self, obj, event):
        tab_bar = self.tabs.tabBar()
        draggable_sources = {
            tab_bar,
            getattr(self, "_corner_controls", None),
        }
        if obj in draggable_sources:
            child = None
            clicked_on_tab = False
            if hasattr(event, "position"):
                pos = event.position().toPoint()
                child = obj.childAt(pos)
                if obj is tab_bar and tab_bar.tabAt(pos) >= 0:
                    clicked_on_tab = True

            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                if clicked_on_tab:
                    return super().eventFilter(obj, event)
                if child and child.objectName() == "title_control":
                    return super().eventFilter(obj, event)
                self._toggle_maximize()
                return True

            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if clicked_on_tab:
                    return super().eventFilter(obj, event)
                if child and child.objectName() == "title_control":
                    return super().eventFilter(obj, event)

                # Prefer native WM drag so behavior matches standard title bars.
                handle = self.windowHandle()
                if handle is not None and handle.startSystemMove():
                    self._drag_active = False
                    self._drag_offset = None
                    return True

                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True

            if event.type() == QEvent.Type.MouseMove and self._drag_active and self._drag_offset is not None:
                if not self.isMaximized():
                    self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True

            if event.type() == QEvent.Type.MouseButtonRelease:
                if not self._drag_active:
                    return super().eventFilter(obj, event)
                self._drag_active = False
                self._drag_offset = None
                return True

        return super().eventFilter(obj, event)

    def _current_account(self):
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, WhatsAppAccount) else None

    def _clear_current_cache(self):
        account = self._current_account()
        if not account:
            return
        profile = account.page().profile()
        profile.clearHttpCache()
        profile.cookieStore().deleteAllCookies()
        profile.clearAllVisitedLinks()
        QMessageBox.information(self, "Cache Cleared", "Cleared cache and cookies for current tab.")

    def _open_downloads(self):
        downloads_path = os.path.expanduser("~/Downloads/WhatsApp")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~/Downloads")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~")
        QDesktopServices.openUrl(QUrl.fromLocalFile(downloads_path))

    def _on_tab_changed(self, index):
        self._resume_tab_if_suspended(index)
        self._schedule_inactive_unload(index)
        self._balance_tab_resources(index)
        widget = self.tabs.widget(index)
        if isinstance(widget, WhatsAppAccount):
            widget.setFocus(Qt.FocusReason.TabFocusReason)

    def _schedule_inactive_unload(self, active_index):
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if not isinstance(widget, WhatsAppAccount):
                continue

            timer = self._inactive_timers.get(i)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda idx=i: self._suspend_tab(idx))
                self._inactive_timers[i] = timer

            if i == active_index:
                timer.stop()
            else:
                timer.start(INACTIVE_UNLOAD_MS)

    def _suspend_tab(self, index):
        if index == self.tabs.currentIndex():
            return

        widget = self.tabs.widget(index)
        if not isinstance(widget, WhatsAppAccount):
            return
        if index in self._suspended_tabs:
            return

        widget.stop()
        widget.setUrl(QUrl("about:blank"))
        self._suspended_tabs.add(index)

    def _resume_tab_if_suspended(self, index):
        if index not in self._suspended_tabs:
            return
        widget = self.tabs.widget(index)
        if not isinstance(widget, WhatsAppAccount):
            return
        self._suspended_tabs.discard(index)
        widget.setUrl(QUrl(WHATSAPP_WEB_URL))

    def _balance_tab_resources(self, active_index):
        if not ENABLE_LIFECYCLE_FREEZE:
            return

        lifecycle_enum = getattr(QWebEnginePage, "LifecycleState", None)
        if lifecycle_enum is None:
            return

        active_state = getattr(lifecycle_enum, "Active", None)
        frozen_state = getattr(lifecycle_enum, "Frozen", None)
        if active_state is None or frozen_state is None:
            return

        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if not isinstance(widget, WhatsAppAccount):
                continue
            page = widget.page()
            target_state = active_state if i == active_index else frozen_state
            if page.lifecycleState() != target_state:
                page.setLifecycleState(target_state)

    def _check_for_updates(self, manual=False):
        if self._update_check_in_progress:
            if manual:
                QMessageBox.information(self, "Update Check", "An update check is already in progress.")
            return

        self._manual_update_check = manual
        self._update_check_in_progress = True
        self._update_checker = UpdateChecker()
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.no_update.connect(self._on_no_update_available)
        self._update_checker.check_failed.connect(self._on_update_check_failed)
        thread = threading.Thread(target=self._update_checker.run, daemon=True)
        thread.start()

    def _on_update_available(self, latest_tag):
        self._update_check_in_progress = False
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        msg = QMessageBox(self)
        msg.setWindowTitle("Update Available")
        msg.setText(
            (
                f"A new version is available: {latest_tag}\n"
                f"Current version: {APP_VERSION}\n\n"
                "Open releases page?"
            )
        )
        open_btn = msg.addButton("Open releases page", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(releases_url))

    def _on_no_update_available(self):
        self._update_check_in_progress = False
        if self._manual_update_check:
            QMessageBox.information(self, "No Updates", f"You are up to date ({APP_VERSION}).")

    def _on_update_check_failed(self):
        self._update_check_in_progress = False
        if self._manual_update_check:
            QMessageBox.warning(self, "Update Check Failed", "Could not check for updates right now.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    sys.exit(app.exec())
