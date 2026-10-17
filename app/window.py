import re
import os

from PyQt6.QtCore import QUrl, Qt, QTimer, QEvent
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QMessageBox,
    QMenu,
    QToolButton,
    QWidget,
    QHBoxLayout,
    QPushButton,
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)
from PyQt6.QtGui import QIcon, QDesktopServices, QAction

from app.config import (
    APP_VERSION,
    GITHUB_REPO,
    WHATSAPP_WEB_URL,
    INACTIVE_UNLOAD_MS,
    TOP_BAR_HEIGHT,
    ENABLE_LIFECYCLE_FREEZE,
    get_icon_path,
)
from app.account import WhatsAppAccount
from app.updater import UpdateChecker, start_update_check


class AddAccountDialog(QDialog):
    """自定义添加账号对话框，支持直接粘贴代理链接"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加账号")
        self.resize(350, 180)

        layout = QVBoxLayout(self)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：工作号 (必填)")
        layout.addWidget(QLabel("账号名称："))
        layout.addWidget(self.name_input)

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("例如: socks5://账号:密码@IP:端口")
        layout.addWidget(QLabel("代理链接 (留空则不走代理)："))
        layout.addWidget(self.proxy_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "proxy_url": self.proxy_input.text().strip(),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("WhatsApp Multi-Account")
        self.resize(1200, 900)

        self._set_app_icon()

        self._update_checker = None
        self._manual_update_check = False
        self._update_check_in_progress = False
        self._inactive_timers = {}
        self._suspended_tabs = set()
        self._drag_active = False
        self._drag_offset = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._setup_actions_menu()
        self._setup_top_bar_controls()
        self._balance_tab_resources(self.tabs.currentIndex())
        self._schedule_inactive_unload(self.tabs.currentIndex())
        self._check_for_updates()

    def _set_app_icon(self):
        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    # ---------- 账号管理 ----------

    def _create_account_tab(self, profile_name, label, proxy_url=None):
        account = WhatsAppAccount(profile_name, proxy_url=proxy_url)
        index = self.tabs.addTab(account, label)
        return index

    def _add_account(self):
        dialog = AddAccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        name = data["name"]
        if not name:
            QMessageBox.warning(self, "名称无效", "账号名称不能为空。")
            return

        profile_name = re.sub(r"[^\w\-]", "_", name)
        if not profile_name:
            QMessageBox.warning(self, "名称无效", "账号名称包含非法字符，请换一个。")
            return

        existing_labels = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        if name in existing_labels:
            QMessageBox.warning(self, "重复名称", f"已存在名为「{name}」的标签页。")
            return

        index = self._create_account_tab(profile_name, name, proxy_url=data["proxy_url"])
        self.tabs.setCurrentIndex(index)
        self._schedule_inactive_unload(index)
        self._balance_tab_resources(index)

    # ---------- 标签页右键菜单 ----------

    def _show_tab_context_menu(self, pos):
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(pos)
        if index < 0:
            return

        menu = QMenu(self)

        close_action = QAction("关闭此标签页", self)
        close_action.triggered.connect(lambda: self._close_tab(index))
        menu.addAction(close_action)

        close_others = QAction("关闭其他标签页", self)
        close_others.triggered.connect(lambda: self._close_other_tabs(index))
        menu.addAction(close_others)

        menu.exec(tab_bar.mapToGlobal(pos))

    def _close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget is None:
            return

        self.tabs.removeTab(index)

        timer = self._inactive_timers.pop(index, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        self._suspended_tabs.discard(index)

        self._rebuild_tab_indices()
        widget.deleteLater()

    def _close_other_tabs(self, keep_index):
        for i in range(self.tabs.count() - 1, -1, -1):
            if i != keep_index:
                self._close_tab(i)

    def _rebuild_tab_indices(self):
        """删除标签页后，按新索引重建不活跃定时器。"""
        for timer in self._inactive_timers.values():
            timer.stop()
            timer.deleteLater()
        self._inactive_timers = {}
        self._suspended_tabs = set()

        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if not isinstance(widget, WhatsAppAccount):
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda idx=i: self._suspend_tab(idx))
            self._inactive_timers[i] = timer

        self._schedule_inactive_unload(self.tabs.currentIndex())

    # ---------- 顶部栏 ----------

    def _setup_actions_menu(self):
        self._actions_menu = QMenu(self)

        add_account = QAction("添加账号", self)
        add_account.triggered.connect(self._add_account)
        self._actions_menu.addAction(add_account)

        self._actions_menu.addSeparator()

        clear_cache = QAction("清除缓存（当前标签页）", self)
        clear_cache.triggered.connect(self._clear_current_cache)
        self._actions_menu.addAction(clear_cache)

        open_downloads = QAction("打开下载文件夹", self)
        open_downloads.triggered.connect(self._open_downloads)
        self._actions_menu.addAction(open_downloads)

        check_updates = QAction("检查更新", self)
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
        settings_btn.setToolTip("菜单")
        settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_btn.setMenu(self._actions_menu)
        settings_btn.setFixedSize(32, button_height)
        settings_btn.setObjectName("title_control")
        layout.addWidget(settings_btn)

        min_btn = QPushButton("−", self._corner_controls)
        min_btn.setToolTip("最小化")
        min_btn.setFixedSize(32, button_height)
        min_btn.setAutoDefault(False)
        min_btn.setDefault(False)
        min_btn.setObjectName("title_control")
        min_btn.clicked.connect(self.showMinimized)
        layout.addWidget(min_btn)

        self._max_btn = QPushButton("□", self._corner_controls)
        self._max_btn.setToolTip("最大化")
        self._max_btn.setFixedSize(32, button_height)
        self._max_btn.setAutoDefault(False)
        self._max_btn.setDefault(False)
        self._max_btn.setObjectName("title_control")
        self._max_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self._max_btn)

        close_btn = QPushButton("×", self._corner_controls)
        close_btn.setToolTip("关闭")
        close_btn.setFixedSize(32, button_height)
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
        close_btn.setObjectName("title_control")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.tabs.setCornerWidget(self._corner_controls, Qt.Corner.TopRightCorner)
        self.tabs.tabBar().setDrawBase(False)

        # 标签栏右键菜单
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

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
            self._max_btn.setToolTip("最大化")
            return
        self.showMaximized()
        self._max_btn.setText("❐")
        self._max_btn.setToolTip("向下还原")

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

    # ---------- 标签页资源管理 ----------

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
        QMessageBox.information(self, "缓存已清除", "已清除当前标签页的缓存和 Cookie。")

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

        from PyQt6.QtWebEngineCore import QWebEnginePage

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

    # ---------- 更新检查 ----------

    def _check_for_updates(self, manual=False):
        if self._update_check_in_progress:
            if manual:
                QMessageBox.information(self, "检查更新", "更新检查正在进行中。")
            return

        self._manual_update_check = manual
        self._update_check_in_progress = True
        self._update_checker = UpdateChecker()
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.no_update.connect(self._on_no_update_available)
        self._update_checker.check_failed.connect(self._on_update_check_failed)
        start_update_check(self._update_checker)

    def _on_update_available(self, latest_tag):
        self._update_check_in_progress = False
        releases_url = f"https://github.com/{GITHUB_REPO}/releases"
        msg = QMessageBox(self)
        msg.setWindowTitle("发现更新")
        msg.setText(
            (
                f"发现新版本: {latest_tag}\n"
                f"当前版本: {APP_VERSION}\n\n"
                "是否打开下载页面？"
            )
        )
        open_btn = msg.addButton("打开下载页面", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(releases_url))

    def _on_no_update_available(self):
        self._update_check_in_progress = False
        if self._manual_update_check:
            QMessageBox.information(self, "无更新", f"当前已是最新版本 ({APP_VERSION})。")

    def _on_update_check_failed(self):
        self._update_check_in_progress = False
        if self._manual_update_check:
            QMessageBox.warning(self, "检查失败", "当前无法检查更新，请稍后再试。")