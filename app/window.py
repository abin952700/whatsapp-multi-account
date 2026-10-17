import os
import platform
import uuid

from PyQt6.QtCore import QUrl, Qt, QTimer, QEvent, QSize
from PyQt6.QtWidgets import (
    QMainWindow,
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
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QFrame,
    QComboBox,
    QAbstractItemView,
)
from PyQt6.QtGui import QIcon, QDesktopServices, QAction

from app.config import (
    APP_VERSION,
    GITHUB_REPO,
    WHATSAPP_WEB_URL,
    INACTIVE_UNLOAD_MS,
    ENABLE_LIFECYCLE_FREEZE,
    get_icon_path,
    load_settings,
    save_settings,
    load_accounts as load_account_configs,
    save_accounts as save_account_configs,
)
from app.account import WhatsAppAccount
from app.windows_account import WindowsAccountProcess
from app.country import CountryResolver, country_flag
from app.proxy_extension import apply_proxy_mode, parse_proxy_url
from app.updater import UpdateChecker, start_update_check


class AddAccountDialog(QDialog):
    """自定义添加账号对话框，支持直接粘贴代理链接。"""
    def __init__(self, global_proxy="", parent=None, name="", proxy_mode="custom", proxy_url=""):
        super().__init__(parent)
        self.setWindowTitle("编辑账号" if name else "添加账号")
        self.resize(350, 180)

        layout = QVBoxLayout(self)

        self.proxy_mode = QComboBox()
        self.proxy_mode.addItem("无代理（直接连接）", "none")
        self.proxy_mode.addItem("使用系统代理 / VPN", "system")
        global_label = "使用全局代理" if global_proxy else "使用全局代理（未配置）"
        self.proxy_mode.addItem(global_label, "global")
        self.proxy_mode.addItem("自定义代理（账号独立）", "custom")
        selected_index = self.proxy_mode.findData(proxy_mode)
        if selected_index >= 0:
            self.proxy_mode.setCurrentIndex(selected_index)
        layout.addWidget(QLabel("代理方式："))
        layout.addWidget(self.proxy_mode)

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("例如: socks5://账号:密码@IP:端口")
        self.proxy_input.setText(proxy_url)
        self.proxy_label = QLabel("自定义代理地址：")
        layout.addWidget(self.proxy_label)
        layout.addWidget(self.proxy_input)
        self.proxy_mode.currentIndexChanged.connect(self._update_proxy_input)
        self._update_proxy_input()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "proxy_mode": self.proxy_mode.currentData(),
            "proxy_url": self.proxy_input.text().strip(),
        }

    def _update_proxy_input(self):
        custom = self.proxy_mode.currentData() == "custom"
        self.proxy_label.setVisible(custom)
        self.proxy_input.setVisible(custom)


class GlobalProxyDialog(QDialog):
    def __init__(self, proxy_url="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("全局代理")
        self.resize(440, 150)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("新账号可选择使用此全局代理；留空表示未配置。"))
        self.proxy_input = QLineEdit(proxy_url)
        self.proxy_input.setPlaceholderText("http://账号:密码@IP:端口")
        layout.addWidget(self.proxy_input)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def proxy_url(self):
        return self.proxy_input.text().strip()


class MainWindow(QMainWindow):
    LABEL_ROLE = Qt.ItemDataRole.UserRole
    PROFILE_ROLE = Qt.ItemDataRole.UserRole + 1
    PROXY_MODE_ROLE = Qt.ItemDataRole.UserRole + 2
    LOCATION_REQUEST_ROLE = Qt.ItemDataRole.UserRole + 3
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 4
    ICON_ROLE = Qt.ItemDataRole.UserRole + 5
    UNREAD_ROLE = Qt.ItemDataRole.UserRole + 6
    NOTIFICATION_ROLE = Qt.ItemDataRole.UserRole + 7
    PHONE_ROLE = Qt.ItemDataRole.UserRole + 8

    def __init__(self):
        super().__init__()
        if platform.system() != "Darwin":
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
        self._active_index = -1
        self.settings = load_settings()
        self.global_proxy_url = str(self.settings.get("global_proxy_url") or "").strip()
        self.country_resolver = CountryResolver(self)
        self.country_resolver.resolved.connect(self._on_country_resolved)

        self._setup_actions_menu()
        self._setup_contact_layout()

        # 启动时自动读取上次保存的账号
        self._load_accounts()
        self._update_empty_state()
        self._balance_tab_resources(self.account_list.currentRow())
        self._schedule_inactive_unload(self.account_list.currentRow())
        self._check_for_updates()

    def _set_app_icon(self):
        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    # ---------- 账号管理 ----------

    def _create_account_tab(self, profile_name, label, proxy_url=None, proxy_mode="global", phone=""):
        if phone:
            label = str(phone)
        effective_proxy = self.global_proxy_url if proxy_mode == "global" else (
            proxy_url or "" if proxy_mode == "custom" else ""
        )
        account_class = WindowsAccountProcess if platform.system() == "Windows" else WhatsAppAccount
        account = account_class(profile_name, proxy_url=effective_proxy)
        account.proxy_mode = proxy_mode
        account.custom_proxy_url = proxy_url or ""
        account.phone_number = str(phone or "")
        account.unread_count_changed.connect(
            lambda count, profile=profile_name: self._on_unread_count(profile, count)
        )
        account.browser_notification.connect(
            lambda title, message, profile=profile_name: self._on_browser_notification(
                profile, title, message
            )
        )
        account.phone_number_changed.connect(
            lambda number, profile=profile_name: self._on_phone_number(profile, number)
        )
        self.pages.addWidget(account)
        item = QListWidgetItem(label)
        item.setData(self.LABEL_ROLE, label)
        item.setData(self.PROFILE_ROLE, profile_name)
        item.setData(self.PROXY_MODE_ROLE, proxy_mode)
        item.setData(self.UNREAD_ROLE, 0)
        item.setData(self.NOTIFICATION_ROLE, "")
        item.setData(self.PHONE_ROLE, str(phone or ""))
        item.setToolTip(label)
        item.setSizeHint(QSize(0, 58))
        self.account_list.addItem(item)
        self._set_account_location_pending(item, effective_proxy, proxy_mode)
        self._update_empty_state()
        return self.account_list.count() - 1

    def _account_at(self, index):
        if index < 0 or index >= self.account_list.count():
            return None
        widget = self.pages.widget(index + 1)
        return widget if isinstance(widget, (WhatsAppAccount, WindowsAccountProcess)) else None

    def _account_label(self, index):
        item = self.account_list.item(index)
        return str(item.data(self.LABEL_ROLE) or "") if item else ""

    def _set_account_location_pending(self, item, proxy_url, proxy_mode):
        label = str(item.data(self.LABEL_ROLE) or "")
        request_id = uuid.uuid4().hex
        item.setData(self.LOCATION_REQUEST_ROLE, request_id)
        if proxy_mode == "system":
            item.setData(self.ICON_ROLE, "⚙️")
            item.setData(self.STATUS_ROLE, "系统代理")
            self._render_account_item(item)
            item.setToolTip(f"{label}\n跟随 macOS 系统代理设置")
            return
        if proxy_mode == "none":
            item.setData(self.ICON_ROLE, "🌐")
            item.setData(self.STATUS_ROLE, "无代理 · 直连")
            self._render_account_item(item)
            item.setToolTip(f"{label}\n不使用代理")
            return
        if not proxy_url:
            item.setData(self.ICON_ROLE, "🌐")
            item.setData(self.STATUS_ROLE, "直连")
            self._render_account_item(item)
            item.setToolTip(f"{label}\n未使用代理")
            return
        config = parse_proxy_url(proxy_url)
        mode_label = "全局代理" if proxy_mode == "global" else "自定义代理"
        item.setData(self.ICON_ROLE, "⏳")
        item.setData(self.STATUS_ROLE, f"{mode_label} · 检测国家…")
        self._render_account_item(item)
        item.setToolTip(f"{label}\n{mode_label}: {config.host}:{config.port}")
        self.country_resolver.lookup(request_id, proxy_url)

    def _on_country_resolved(self, request_id, code, country):
        for index in range(self.account_list.count()):
            item = self.account_list.item(index)
            if str(item.data(self.LOCATION_REQUEST_ROLE) or "") != request_id:
                continue
            label = str(item.data(self.LABEL_ROLE) or "")
            mode = str(item.data(self.PROXY_MODE_ROLE) or "global")
            mode_label = "全局" if mode == "global" else "自定义"
            item.setData(self.ICON_ROLE, country_flag(code))
            item.setData(self.STATUS_ROLE, f"{country} · {mode_label}")
            self._render_account_item(item)
            return

    def _render_account_item(self, item):
        icon = str(item.data(self.ICON_ROLE) or "🌐")
        label = str(item.data(self.LABEL_ROLE) or "")
        unread = int(item.data(self.UNREAD_ROLE) or 0)
        status = str(item.data(self.STATUS_ROLE) or "")
        notification = str(item.data(self.NOTIFICATION_ROLE) or "")
        badge = f"  🔴 {unread}" if unread else ""
        detail = notification or status
        item.setText(f"{icon}  {label}{badge}\n    {detail}")
        item.setSizeHint(QSize(0, 66 if notification else 58))

    def _item_for_profile(self, profile_name):
        for index in range(self.account_list.count()):
            item = self.account_list.item(index)
            if str(item.data(self.PROFILE_ROLE) or "") == profile_name:
                return item
        return None

    def _on_unread_count(self, profile_name, count):
        item = self._item_for_profile(profile_name)
        if item is None:
            return
        item.setData(self.UNREAD_ROLE, max(0, count))
        self._render_account_item(item)

    def _on_browser_notification(self, profile_name, title, message):
        item = self._item_for_profile(profile_name)
        if item is None:
            return
        summary = (message or title or "新消息").replace("\n", " ").strip()
        if len(summary) > 32:
            summary = summary[:31] + "…"
        item.setData(self.NOTIFICATION_ROLE, f"新消息：{summary}")
        self._render_account_item(item)

    def _on_phone_number(self, profile_name, number):
        item = self._item_for_profile(profile_name)
        if item is None:
            return
        item.setData(self.PHONE_ROLE, number)
        item.setData(self.LABEL_ROLE, number)
        self._render_account_item(item)
        self._save_accounts()

    def _add_account(self):
        dialog = AddAccountDialog(self.global_proxy_url, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        try:
            if data["proxy_mode"] == "global" and not self.global_proxy_url:
                raise ValueError("请先在菜单中配置全局代理，或选择自定义代理")
            if data["proxy_mode"] == "custom" and not data["proxy_url"]:
                raise ValueError("请填写自定义代理地址")
            if data["proxy_mode"] in {"global", "custom"}:
                parse_proxy_url(
                    self.global_proxy_url if data["proxy_mode"] == "global" else data["proxy_url"]
                )
        except ValueError as exc:
            QMessageBox.warning(self, "代理地址无效", str(exc))
            return

        # 登录完成前使用临时名称；检测到本人号码后会自动替换。
        profile_name = f"account_{uuid.uuid4().hex}"
        name = f"新账号 {self.account_list.count() + 1}"

        index = self._create_account_tab(
            profile_name,
            name,
            proxy_url=data["proxy_url"],
            proxy_mode=data["proxy_mode"],
        )
        self._save_accounts()
        self.account_list.setCurrentRow(index)
        self._schedule_inactive_unload(index)
        self._balance_tab_resources(index)
        

    def _edit_account(self, index):
        self._edit_accounts([index])

    def _on_account_current_changed(self, index):
        if index < 0:
            return
        item = self.account_list.item(index)
        if item is not None:
            self.settings["selected_profile"] = str(item.data(self.PROFILE_ROLE) or "")
            try:
                save_settings(self.settings)
            except OSError as exc:
                print(f"保存当前账号失败: {exc}")
        if index != self._active_index:
            self._on_tab_changed(index)

    def _edit_selected_accounts(self):
        index = self.account_list.currentRow()
        self._edit_accounts([index] if index >= 0 else [])

    def _edit_accounts(self, indices):
        indices = [index for index in indices if self._account_at(index) is not None]
        if not indices:
            return
        first = self._account_at(indices[0])
        title_hint = "批量编辑" if len(indices) > 1 else self._account_label(indices[0])
        dialog = AddAccountDialog(
            self.global_proxy_url,
            self,
            name=title_hint,
            proxy_mode=getattr(first, "proxy_mode", "global"),
            proxy_url=getattr(first, "custom_proxy_url", ""),
        )
        if len(indices) > 1:
            dialog.setWindowTitle(f"批量修改代理（{len(indices)} 个账号）")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        try:
            if data["proxy_mode"] == "global" and not self.global_proxy_url:
                raise ValueError("请先配置全局代理，或选择其他代理方式")
            if data["proxy_mode"] == "custom" and not data["proxy_url"]:
                raise ValueError("请填写自定义代理地址")
            if data["proxy_mode"] in {"global", "custom"}:
                parse_proxy_url(
                    self.global_proxy_url if data["proxy_mode"] == "global" else data["proxy_url"]
                )
        except ValueError as exc:
            QMessageBox.warning(self, "代理地址无效", str(exc))
            return

        effective_proxy = self.global_proxy_url if data["proxy_mode"] == "global" else (
            data["proxy_url"] if data["proxy_mode"] == "custom" else ""
        )
        accounts = []
        for index in indices:
            account = self._account_at(index)
            item = self.account_list.item(index)
            if account is None or item is None:
                continue
            item.setData(self.PROXY_MODE_ROLE, data["proxy_mode"])
            account.proxy_mode = data["proxy_mode"]
            account.custom_proxy_url = data["proxy_url"] if data["proxy_mode"] == "custom" else ""
            account.proxy_url = effective_proxy
            account.proxy_config = parse_proxy_url(effective_proxy)
            self._set_account_location_pending(item, effective_proxy, data["proxy_mode"])
            accounts.append(account)
        self._save_accounts()
        if platform.system() == "Windows":
            for account in accounts:
                account.restart()
            return
        current = self.account_list.currentRow()
        if current in indices and current == self._active_index:
            self._reload_embedded_account(current)

    def _delete_selected_accounts(self):
        index = self.account_list.currentRow()
        if index < 0:
            return
        answer = QMessageBox.question(
            self,
            "删除账号",
            f"确定删除账号“{self._account_label(index)}”吗？\n登录数据目录会保留。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._close_tab(index)

    def _save_accounts(self):
        """把当前所有打开的标签页账号信息保存到 JSON"""
        accounts = []
        for i in range(self.account_list.count()):
            widget = self._account_at(i)
            if isinstance(widget, (WhatsAppAccount, WindowsAccountProcess)):
                accounts.append({
                    "label": self._account_label(i),
                    "profile_name": widget.profile.storageName(),
                    "proxy_mode": getattr(widget, "proxy_mode", "global"),
                    "proxy_url": getattr(widget, "custom_proxy_url", ""),
                    "phone": getattr(widget, "phone_number", ""),
                })
                
        try:
            save_account_configs(accounts)
        except OSError as e:
            print(f"保存账号失败: {e}")

    def _load_accounts(self):
        """启动时从 JSON 加载账号并恢复标签页"""
        try:
            accounts = load_account_configs()
            for acc in accounts:
                label = acc.get("label")
                profile_name = acc.get("profile_name")
                proxy_url = acc.get("proxy_url", "")
                proxy_mode = acc.get("proxy_mode")
                phone = str(acc.get("phone") or "")
                if proxy_mode not in {"none", "system", "global", "custom"}:
                    proxy_mode = "custom" if proxy_url else "global"
                
                if label and profile_name:
                    self._create_account_tab(
                        profile_name,
                        label,
                        proxy_url=proxy_url,
                        proxy_mode=proxy_mode,
                        phone=phone,
                    )
            if self.account_list.count():
                selected_profile = str(self.settings.get("selected_profile") or "")
                selected_row = 0
                for row in range(self.account_list.count()):
                    if str(self.account_list.item(row).data(self.PROFILE_ROLE)) == selected_profile:
                        selected_row = row
                        break
                self.account_list.setCurrentRow(selected_row)
        except Exception as e:
            print(f"加载账号失败: {e}")

    # ---------- 标签页右键菜单 ----------

    def _show_tab_context_menu(self, pos):
        item = self.account_list.itemAt(pos)
        index = self.account_list.row(item) if item else -1
        if index < 0:
            return

        menu = QMenu(self)

        edit_action = QAction("编辑账号", self)
        edit_action.triggered.connect(lambda: self._edit_account(index))
        menu.addAction(edit_action)

        menu.addSeparator()

        close_action = QAction("关闭此标签页", self)
        close_action.triggered.connect(lambda: self._close_tab(index))
        menu.addAction(close_action)

        close_others = QAction("关闭其他标签页", self)
        close_others.triggered.connect(lambda: self._close_other_tabs(index))
        menu.addAction(close_others)

        menu.exec(self.account_list.viewport().mapToGlobal(pos))

    def _close_tab(self, index):
        widget = self._account_at(index)
        if widget is None:
            return

        self.account_list.takeItem(index)
        self.pages.removeWidget(widget)

        timer = self._inactive_timers.pop(index, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        self._suspended_tabs.discard(index)

        self._rebuild_tab_indices()
        widget.deleteLater()
        self._update_empty_state()
        self._save_accounts()  # 新增：保存配置

    def _close_other_tabs(self, keep_index):
        for i in range(self.account_list.count() - 1, -1, -1):
            if i != keep_index:
                self._close_tab(i)

    def _rebuild_tab_indices(self):
        """删除标签页后，按新索引重建不活跃定时器。"""
        for timer in self._inactive_timers.values():
            timer.stop()
            timer.deleteLater()
        self._inactive_timers = {}
        self._suspended_tabs = set()
        self._active_index = -1

        for i in range(self.account_list.count()):
            widget = self._account_at(i)
            if not isinstance(widget, (WhatsAppAccount, WindowsAccountProcess)):
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda idx=i: self._suspend_tab(idx))
            self._inactive_timers[i] = timer

        current_row = self.account_list.currentRow()
        self._schedule_inactive_unload(current_row)
        if current_row >= 0:
            self._on_account_current_changed(current_row)

    # ---------- 顶部栏与样式 ----------

    def _setup_actions_menu(self):
        self._actions_menu = QMenu(self)

        global_proxy = QAction("全局代理设置", self)
        global_proxy.triggered.connect(self._configure_global_proxy)
        self._actions_menu.addAction(global_proxy)

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

    def _configure_global_proxy(self):
        dialog = GlobalProxyDialog(self.global_proxy_url, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        proxy_url = dialog.proxy_url()
        try:
            parse_proxy_url(proxy_url)
        except ValueError as exc:
            QMessageBox.warning(self, "代理地址无效", str(exc))
            return

        if proxy_url == self.global_proxy_url:
            return
        self.global_proxy_url = proxy_url
        self.settings["global_proxy_url"] = proxy_url
        try:
            save_settings(self.settings)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return

        for row in range(self.account_list.count()):
            item = self.account_list.item(row)
            if item.data(self.PROXY_MODE_ROLE) != "global":
                continue
            account = self._account_at(row)
            if account is not None:
                account.proxy_url = proxy_url
                account.proxy_config = parse_proxy_url(proxy_url)
                if isinstance(account, WindowsAccountProcess):
                    account.restart()
            self._set_account_location_pending(item, proxy_url, "global")

        message = "全局代理已保存。"
        current_row = self.account_list.currentRow()
        current_item = self.account_list.item(current_row)
        if (current_item is not None
                and current_item.data(self.PROXY_MODE_ROLE) == "global"
                and current_row == self._active_index
                and platform.system() != "Windows"):
            account = self._account_at(current_row)
            if account is not None:
                self._reload_embedded_account(current_row)
            message += "\n当前账号已重新连接。"
        QMessageBox.information(self, "全局代理", message)

    def _setup_contact_layout(self):
        central = QWidget(self)
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self._toolbar = QFrame(central)
        self._toolbar.setObjectName("toolbar")
        self._toolbar.setFixedHeight(48)
        self._toolbar.installEventFilter(self)
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(18, 0, 8, 0)
        toolbar_layout.setSpacing(6)

        title = QLabel("WhatsApp Multi-Account", self._toolbar)
        title.setObjectName("app_title")
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch()

        refresh_btn = QPushButton("刷新当前", self._toolbar)
        refresh_btn.setObjectName("toolbar_action")
        refresh_btn.setToolTip("重新连接代理并完整加载当前 WhatsApp 页面")
        refresh_btn.clicked.connect(self._refresh_current_account)
        toolbar_layout.addWidget(refresh_btn)

        edit_btn = QPushButton("修改代理", self._toolbar)
        edit_btn.setObjectName("toolbar_action")
        edit_btn.clicked.connect(self._edit_selected_accounts)
        toolbar_layout.addWidget(edit_btn)

        delete_btn = QPushButton("删除账号", self._toolbar)
        delete_btn.setObjectName("toolbar_danger")
        delete_btn.clicked.connect(self._delete_selected_accounts)
        toolbar_layout.addWidget(delete_btn)

        add_btn = QPushButton("＋  添加账号", self._toolbar)
        add_btn.setObjectName("add_account")
        add_btn.clicked.connect(self._add_account)
        toolbar_layout.addWidget(add_btn)

        settings_btn = QToolButton(self._toolbar)
        settings_btn.setText("⋯")
        settings_btn.setToolTip("菜单")
        settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_btn.setMenu(self._actions_menu)
        settings_btn.setObjectName("toolbar_button")
        settings_btn.setFixedSize(38, 32)
        toolbar_layout.addWidget(settings_btn)

        if platform.system() != "Darwin":
            min_btn = QPushButton("−", self._toolbar)
            min_btn.setObjectName("window_button")
            min_btn.clicked.connect(self.showMinimized)
            toolbar_layout.addWidget(min_btn)

            self._max_btn = QPushButton("□", self._toolbar)
            self._max_btn.setObjectName("window_button")
            self._max_btn.clicked.connect(self._toggle_maximize)
            toolbar_layout.addWidget(self._max_btn)

            close_btn = QPushButton("×", self._toolbar)
            close_btn.setObjectName("close_button")
            close_btn.clicked.connect(self.close)
            toolbar_layout.addWidget(close_btn)

        root.addWidget(self._toolbar)

        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar = QFrame(body)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(10)

        contacts_title = QLabel("账号", sidebar)
        contacts_title.setObjectName("section_title")
        sidebar_layout.addWidget(contacts_title)

        self.account_list = QListWidget(sidebar)
        self.account_list.setObjectName("account_list")
        self.account_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.account_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.account_list.currentRowChanged.connect(self._on_account_current_changed)
        sidebar_layout.addWidget(self.account_list, 1)

        body_layout.addWidget(sidebar)

        self.pages = QStackedWidget(body)
        self.pages.setObjectName("pages")
        empty = QWidget(self.pages)
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("还没有 WhatsApp 账号", empty)
        empty_title.setObjectName("empty_title")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel("添加一个账号后，在左侧像通讯录一样快速切换", empty)
        empty_hint.setObjectName("empty_hint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        empty_add = QPushButton("添加第一个账号", empty)
        empty_add.setObjectName("empty_add")
        empty_add.clicked.connect(self._add_account)
        empty_layout.addWidget(empty_add, alignment=Qt.AlignmentFlag.AlignCenter)
        self.pages.addWidget(empty)
        body_layout.addWidget(self.pages, 1)
        root.addWidget(body, 1)

        self.setStyleSheet(
            """
            QWidget#central, QStackedWidget#pages { background: #f7f8fa; }
            QFrame#toolbar { background: #202c33; border-bottom: 1px solid #111b21; }
            QLabel#app_title { color: white; font-size: 15px; font-weight: 600; }
            QPushButton#add_account, QPushButton#sidebar_add, QPushButton#empty_add {
                background: #25d366; color: white; border: none; border-radius: 7px;
                padding: 8px 14px; font-weight: 600;
            }
            QPushButton#add_account:hover, QPushButton#sidebar_add:hover,
            QPushButton#empty_add:hover { background: #1ebe5d; }
            QPushButton#toolbar_action, QPushButton#toolbar_danger {
                color: #d1d7db; background: #2f3d44; border: none;
                border-radius: 6px; padding: 7px 11px;
            }
            QPushButton#toolbar_action:hover { background: #3f515a; color: white; }
            QPushButton#toolbar_danger:hover { background: #b33a3a; color: white; }
            QToolButton#toolbar_button, QPushButton#window_button, QPushButton#close_button {
                color: #d1d7db; background: transparent; border: none;
                min-width: 34px; min-height: 30px; font-size: 18px;
            }
            QToolButton#toolbar_button:hover, QPushButton#window_button:hover {
                background: #374248; border-radius: 5px;
            }
            QPushButton#close_button:hover { background: #d9534f; color: white; }
            QToolButton::menu-indicator { image: none; width: 0px; }
            QFrame#sidebar { background: #ffffff; border-right: 1px solid #e4e7eb; }
            QLabel#section_title { color: #667781; font-size: 12px; font-weight: 700; }
            QListWidget#account_list { border: none; background: transparent; outline: none; }
            QListWidget#account_list::item {
                color: #263238; border: none; border-radius: 8px; padding: 0 14px;
                margin: 2px 0; font-size: 14px;
            }
            QListWidget#account_list::item:hover { background: #f0f2f5; }
            QListWidget#account_list::item:selected {
                background: #d9fdd3; color: #111b21; font-weight: 600;
            }
            QLabel#empty_title { color: #263238; font-size: 22px; font-weight: 600; }
            QLabel#empty_hint { color: #667781; font-size: 14px; margin: 6px 0 18px 0; }
            """
        )

    def _update_empty_state(self):
        if self.account_list.count() == 0:
            self.pages.setCurrentIndex(0)
            return
        row = self.account_list.currentRow()
        if row < 0:
            self.account_list.setCurrentRow(0)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            if hasattr(self, "_max_btn"):
                self._max_btn.setText("□")
                self._max_btn.setToolTip("最大化")
            return
        self.showMaximized()
        if hasattr(self, "_max_btn"):
            self._max_btn.setText("❐")
            self._max_btn.setToolTip("向下还原")

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_toolbar", None):
            child = None
            if hasattr(event, "position"):
                pos = event.position().toPoint()
                child = obj.childAt(pos)

            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                if child and child.objectName() in {"add_account", "toolbar_action", "toolbar_danger", "toolbar_button", "window_button", "close_button"}:
                    return super().eventFilter(obj, event)
                self._toggle_maximize()
                return True

            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if child and child.objectName() in {"add_account", "toolbar_action", "toolbar_danger", "toolbar_button", "window_button", "close_button"}:
                    return super().eventFilter(obj, event)

                if platform.system() == "Darwin":
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
        return self._account_at(self.account_list.currentRow())

    def _clear_current_cache(self):
        account = self._current_account()
        if not account:
            return
        if isinstance(account, WindowsAccountProcess):
            QMessageBox.information(self, "缓存", "请先删除账号后再手动清理其数据目录。")
            return
        account.page().profile().clearHttpCache()
        QMessageBox.information(self, "缓存已清除", "当前账号的网页缓存已清除，登录数据已保留。")

    def _open_downloads(self):
        downloads_path = os.path.expanduser("~/Downloads/WhatsApp")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~/Downloads")
        if not os.path.isdir(downloads_path):
            downloads_path = os.path.expanduser("~")
        QDesktopServices.openUrl(QUrl.fromLocalFile(downloads_path))

    def _on_tab_changed(self, index):
        if index < 0:
            self.pages.setCurrentIndex(0)
            return

        previous_index = self._active_index
        if previous_index >= 0 and previous_index != index:
            previous = self._account_at(previous_index)
            if previous is not None and not isinstance(previous, WindowsAccountProcess):
                previous.cancel_pending_load()
                previous.stop()
                previous.setUrl(QUrl("about:blank"))

        widget = self._account_at(index)
        if widget is None:
            return
        if not isinstance(widget, WindowsAccountProcess):
            try:
                apply_proxy_mode(getattr(widget, "proxy_mode", "none"), widget.proxy_url)
            except ValueError as exc:
                QMessageBox.warning(self, "代理地址无效", str(exc))
                return
        self._active_index = index
        self.pages.setCurrentIndex(index + 1)
        item = self.account_list.item(index)
        if item is not None:
            self.settings["selected_profile"] = str(item.data(self.PROFILE_ROLE) or "")
            try:
                save_settings(self.settings)
            except OSError as exc:
                print(f"保存当前账号失败: {exc}")
        widget.request_load()

    def _reload_embedded_account(self, index):
        account = self._account_at(index)
        if account is None:
            return
        if isinstance(account, WindowsAccountProcess):
            account.restart()
            return
        account.cancel_pending_load()
        account.stop()
        account.setUrl(QUrl("about:blank"))
        self._active_index = -1
        self._on_tab_changed(index)

    def _refresh_current_account(self):
        """完整重建当前账号的网络连接并刷新页面。"""
        index = self.account_list.currentRow()
        if index < 0:
            QMessageBox.information(self, "刷新", "请先选择一个账号。")
            return
        self._reload_embedded_account(index)

    def _schedule_inactive_unload(self, active_index):
        return

    def _suspend_tab(self, index):
        return

    def _resume_tab_if_suspended(self, index):
        return

    def _balance_tab_resources(self, active_index):
        return

    def closeEvent(self, event):
        """退出前保存账号清单、代理选择和当前账号。"""
        self._save_accounts()
        if platform.system() == "Windows":
            for index in range(self.account_list.count()):
                account = self._account_at(index)
                if isinstance(account, WindowsAccountProcess):
                    account.terminate()
        current = self.account_list.currentItem()
        if current is not None:
            self.settings["selected_profile"] = str(
                current.data(self.PROFILE_ROLE) or ""
            )
        try:
            save_settings(self.settings)
        except OSError as exc:
            print(f"保存应用设置失败: {exc}")
        super().closeEvent(event)

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
