"""Qt 桌面收银台；桌面布局与业务事务分离。"""
from datetime import datetime
from pathlib import Path
import logging
import queue
import sqlite3
import threading

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QAbstractSpinBox, QButtonGroup, QDialog,
    QFileDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QSpinBox, QStackedWidget, QWidget)

from . import APP_NAME, __version__
from .money import ValidationError, discounted_cents, money, to_cents
from .printing import available_printers, print_receipt
from .storage import Store
from .theme import apply_theme, apply_window_theme
from .widgets import ComboBox as QComboBox, CheckBox as QCheckBox
from .widgets import (CardGrid, action, clear_layout, data_table, divider, fill_table,
    hbox, line_icon, panel, scroll, selected_id, text, tile, vbox)


def notify(parent, title, message, error=False):
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setIcon(QMessageBox.Warning if error else QMessageBox.Information)
    dialog.setText(message)
    dialog.addButton("知道了", QMessageBox.AcceptRole)
    apply_window_theme(dialog)
    dialog.exec()
    dialog.deleteLater()


def confirm(parent, title, message):
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    yes = dialog.addButton("确认", QMessageBox.AcceptRole)
    dialog.addButton("返回", QMessageBox.RejectRole)
    apply_window_theme(dialog)
    dialog.exec()
    result = dialog.clickedButton() is yes
    dialog.deleteLater()
    return result


class ThemedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_theme(self)


def save_file(parent, title, suggested_name, file_filter):
    dialog = QFileDialog(parent, title)
    dialog.setOption(QFileDialog.DontUseNativeDialog)
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setNameFilter(file_filter)
    dialog.setDefaultSuffix("sqlite3" if "sqlite3" in file_filter else "txt")
    dialog.selectFile(suggested_name)
    apply_window_theme(dialog)
    result = dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted else ""
    dialog.deleteLater()
    return result


def input_field(placeholder="", value=""):
    widget = QLineEdit(value)
    widget.setPlaceholderText(placeholder)
    widget.setClearButtonEnabled(True)
    return widget


def field(layout, title, widget):
    label = text(title, "muted")
    label.setBuddy(widget)
    widget.setAccessibleName(title)
    layout.addWidget(label)
    layout.addWidget(widget)


def update_combo(combo, values, current=None):
    current = combo.currentText() if current is None else current
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(values)
    if combo.isEditable():
        combo.setEditText(current)
    elif current in values:
        combo.setCurrentText(current)
    combo.blockSignals(False)


class App(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        # The offscreen Qt platform has no system font database on Windows.
        # Register installed fonts for previews; nothing is bundled or downloaded.
        if not QFontDatabase.families():
            import os
            for filename in ("msyh.ttc", "msyhbd.ttc"):
                font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
                if font_path.exists():
                    QFontDatabase.addApplicationFont(str(font_path))
        QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))
        self.store = store
        self.table_id = 1
        self.current_order = None
        self.table_filter = "all"
        self.print_queue = queue.Queue()
        self.printing_ids = set()
        self.checkout_dialog = None
        self.last_deleted = None
        self.closed = False
        self.setWindowTitle(f"{APP_NAME} · {__version__}")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)
        self.theme_preference = store.settings()["theme"]
        self._build()
        self.apply_current_theme()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_print)
        self.timer.start(150)

    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        shell = hbox(root, spacing=0)
        rail = panel("Rail")
        rail.setFixedWidth(144)
        rail_layout = vbox(rail, 14, 9)
        logo = text("木", name="Logo")
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignCenter)
        rail_layout.addWidget(logo, alignment=Qt.AlignHCenter)
        brand = text("三木点餐", name="RailBrand")
        brand.setAlignment(Qt.AlignCenter)
        rail_layout.addWidget(brand)
        rail_layout.addSpacing(27)
        self.nav_buttons = []
        self.nav_group = QButtonGroup(self)
        for index, (name, icon) in enumerate((("点餐收银", "tables"), ("餐品管理", "menu"),
                ("桌台管理", "desk"), ("历史订单", "history"), ("系统设置", "settings"))):
            btn = action(name, lambda i=index: self.navigate(i), "nav")
            btn.setCheckable(True)
            btn.setIconSize(QSize(19, 19))
            self.nav_group.addButton(btn)
            self.nav_buttons.append((btn, icon))
            rail_layout.addWidget(btn)
        rail_layout.addStretch()
        rail_layout.addWidget(text("SANMU POS", name="RailNote"), alignment=Qt.AlignHCenter)
        rail_layout.addWidget(text(f"v{__version__}", name="RailNote"), alignment=Qt.AlignHCenter)
        shell.addWidget(rail)
        body = vbox(spacing=0)
        shell.addLayout(body, 1)
        header = panel("Header")
        header.setFixedHeight(80)
        header_layout = hbox(header, 22, 20)
        self.page_title = text("点餐收银", "heading")
        header_layout.addWidget(self.page_title)
        self.shop_label = text(self.store.settings()["shop_name"], "muted")
        header_layout.addWidget(self.shop_label)
        header_layout.addStretch()
        self.summary = text("", "muted")
        header_layout.addWidget(self.summary)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["浅色模式", "深色模式", "跟随系统"])
        self.theme_combo.setCurrentIndex(["light", "dark", "system"].index(self.theme_preference))
        self.theme_combo.setFixedWidth(126)
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        header_layout.addWidget(self.theme_combo)
        body.addWidget(header)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.order_page = QWidget()
        self.order_page.setObjectName("Page")
        self._build_order()
        self.products_page = ProductsPage(self)
        self.tables_page = TablesPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        for page in (self.order_page, self.products_page, self.tables_page, self.history_page, self.settings_page):
            self.stack.addWidget(page)
        footer = QWidget()
        footer.setFixedHeight(39)
        footer_layout = hbox(footer, 0, 12)
        footer_layout.setContentsMargins(22, 0, 22, 0)
        self.status = text("● 本地数据已保存", "small")
        footer_layout.addWidget(self.status)
        self.undo_button = action("撤销删除", self.undo_delete, "quiet")
        self.undo_button.setFixedHeight(30)
        self.undo_button.hide()
        footer_layout.addWidget(self.undo_button)
        footer_layout.addStretch()
        footer_layout.addWidget(text("桌台点餐 · 自动保存", "small"))
        body.addWidget(footer)
        self.navigate(0)

    def _build_order(self):
        outer = hbox(self.order_page, 18, 16)
        table_panel = panel()
        table_panel.setMinimumWidth(210)
        table_panel.setMaximumWidth(282)
        table_layout = vbox(table_panel, 16, 12)
        row = hbox(spacing=8)
        row.addWidget(text("桌台", "heading"))
        row.addStretch()
        row.addWidget(action("管理", lambda: self.navigate(2), "quiet"))
        table_layout.addLayout(row)
        self.table_summary = text("", "small")
        table_layout.addWidget(self.table_summary)
        self.table_search = input_field("搜索桌台名称")
        self.table_search.textChanged.connect(self._refresh_tables)
        table_layout.addWidget(self.table_search)
        filters = hbox(spacing=4)
        self.table_filter_group = QButtonGroup(self)
        for key, title in (("all", "全部"), ("free", "空闲"), ("busy", "用餐中")):
            btn = action(title, lambda value=key: self.filter_tables(value), "chip")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            self.table_filter_group.addButton(btn)
            filters.addWidget(btn)
        table_layout.addLayout(filters)
        self.table_grid = CardGrid(96, 122, 2)
        table_layout.addWidget(scroll(self.table_grid), 1)
        outer.addWidget(table_panel, 2)
        menu_panel = QWidget()
        menu_panel.setMinimumWidth(240)
        menu_layout = vbox(menu_panel, 0, 15)
        top = hbox()
        top.addWidget(text("选择餐品", "heading"))
        top.addStretch()
        self.menu_count = text("", "small")
        top.addWidget(self.menu_count)
        menu_layout.addLayout(top)
        self.search = input_field("搜索餐品名称…")
        self.search.textChanged.connect(self._refresh_menu)
        menu_layout.addWidget(self.search)
        menu_filters = hbox()
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(120)
        self.category_combo.currentTextChanged.connect(self._refresh_menu)
        menu_filters.addWidget(self.category_combo, 1)
        menu_filters.addWidget(text("数量", "muted"))
        self.add_quantity = QSpinBox()
        self.add_quantity.setRange(1, 999)
        self.add_quantity.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.add_quantity.setFixedWidth(86)
        menu_filters.addWidget(self.add_quantity)
        menu_layout.addLayout(menu_filters)
        self.product_grid = CardGrid(164, 151, 4)
        self.product_area = scroll(self.product_grid)
        menu_layout.addWidget(self.product_area, 1)
        self.menu_empty = text("暂无餐品，前往餐品管理新增。", "muted", wrap=True)
        self.menu_empty.hide()
        menu_layout.addWidget(self.menu_empty)
        menu_layout.addWidget(text("点击餐品卡片，直接加入本桌账单", "small"))
        outer.addWidget(menu_panel, 4)
        cart_panel = panel()
        cart_panel.setMinimumWidth(302)
        cart_panel.setMaximumWidth(380)
        cart_layout = vbox(cart_panel, 20, 13)
        row = hbox()
        row.addWidget(text("当前账单", "heading"))
        row.addStretch()
        self.cart_badge = text("空闲", name="Badge")
        row.addWidget(self.cart_badge)
        cart_layout.addLayout(row)
        self.cart_title = text("", "title", wrap=True)
        cart_layout.addWidget(self.cart_title)
        self.order_hint = text("", "small")
        cart_layout.addWidget(self.order_hint)
        cart_layout.addWidget(divider())
        self.cart_container = QWidget()
        self.cart_items = vbox(self.cart_container, 0, 0)
        self.cart_scroll = scroll(self.cart_container)
        cart_layout.addWidget(self.cart_scroll, 1)
        self.empty_cart = QWidget()
        empty_layout = vbox(self.empty_cart, 0, 10)
        empty_layout.addStretch()
        empty_title = text("还没有添加餐品", "heading")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        hint = text("选择左侧餐品，开始为本桌点餐", "small")
        hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(hint)
        empty_layout.addStretch()
        cart_layout.addWidget(self.empty_cart, 1)
        cart_layout.addWidget(divider())
        totals = hbox()
        self.item_count = text("共 0 份餐品", "muted")
        totals.addWidget(self.item_count)
        totals.addStretch()
        totals.addWidget(text("餐品合计", "muted"))
        cart_layout.addLayout(totals)
        self.cart_total = text("￥0.00", "amount")
        self.cart_total.setAlignment(Qt.AlignRight)
        cart_layout.addWidget(self.cart_total)
        self.checkout_button = action("去结算  →", self.open_checkout, "primary")
        self.checkout_button.setFixedHeight(54)
        cart_layout.addWidget(self.checkout_button)
        cart_layout.addWidget(action("取消本桌订单", self.cancel_order, "quiet"))
        outer.addWidget(cart_panel, 3)

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        self.page_title.setText(["点餐收银", "餐品管理", "桌台管理", "历史订单", "系统设置"][index])
        self.nav_buttons[index][0].setChecked(True)
        self._nav_icons()

    def _nav_icons(self):
        for button, icon in self.nav_buttons:
            button.setIcon(line_icon(icon, "#292213" if button.isChecked() else "#ABB5C5"))

    def _system_theme_changed(self, scheme):
        if self.theme_preference == "system":
            self.apply_current_theme()

    def apply_current_theme(self):
        mode = self.theme_preference
        if mode == "system":
            mode = "dark" if QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        self.theme = mode
        self.colors = apply_theme(QApplication.instance(), mode)
        self._nav_icons()
        apply_window_theme(self)

    def change_theme(self, index):
        preference = ["light", "dark", "system"][index]
        def change():
            self.store.set_theme(preference)
            self.theme_preference = preference
            self.apply_current_theme()
            self.status.setText("● 外观设置已保存")
        self.run_action(change)

    def run_action(self, callback):
        try:
            return callback()
        except (ValidationError, sqlite3.Error, OSError) as error:
            logging.exception("操作失败")
            notify(self, "操作未完成", str(error), True)
            return None

    def refresh(self):
        tables = self.store.tables()
        if self.table_id not in {table["id"] for table in tables}:
            self.table_id = tables[0]["id"]
        self._refresh_tables()
        self._refresh_menu()
        self._refresh_cart()
        self.products_page.refresh()
        self.tables_page.refresh()
        self.history_page.refresh()
        summary = self.store.today_summary()
        self.summary.setText(f"今日实收  ￥{money(summary['total_cents'])}   ·   {summary['count']} 单")
        self.shop_label.setText(self.store.settings()["shop_name"])

    def filter_tables(self, value):
        self.table_filter = value
        self._refresh_tables()

    def _refresh_tables(self, *args):
        tables = self.store.tables()
        busy = sum(table["order_id"] is not None for table in tables)
        self.table_summary.setText(f"{len(tables)} 桌  ·  空闲 {len(tables) - busy}  ·  用餐中 {busy}")
        query = self.table_search.text().strip().casefold()
        cards = []
        for table in tables:
            occupied = table["order_id"] is not None
            if query not in table["name"].casefold() or (self.table_filter == "free" and occupied) or (self.table_filter == "busy" and not occupied):
                continue
            card = tile(table["name"], "用餐中" if occupied else "空闲",
                        f"￥{money(table['total_cents'])}" if occupied else "点击点餐",
                        lambda tid=table["id"]: self.select_table(tid), True, occupied)
            card.setChecked(table["id"] == self.table_id)
            card.setContextMenuPolicy(Qt.CustomContextMenu)
            card.customContextMenuRequested.connect(lambda point, c=card, t=table: self.table_context(c, point, t))
            cards.append(card)
        self.table_grid.set_cards(cards)

    def table_context(self, card, point, table):
        menu = QMenu(self)
        rename = menu.addAction("修改桌台名称")
        chosen = menu.exec(card.mapToGlobal(point))
        menu.deleteLater()
        if chosen == rename:
            self.navigate(2)
            self.tables_page.select_table(table["id"])
            self.tables_page.name.setFocus()
            self.tables_page.name.selectAll()

    def _refresh_menu(self, *args):
        products = self.store.products()
        categories = ["全部分类"] + sorted({product["category"] for product in products})
        update_combo(self.category_combo, categories)
        category = self.category_combo.currentText()
        query = self.search.text().strip().casefold()
        filtered = [product for product in products if query in product["name"].casefold()
                    and category in ("全部分类", product["category"])]
        cards = [tile(product["name"], product["category"], f"￥{money(product['price_cents'])}",
                      lambda pid=product["id"]: self.add_item(pid)) for product in filtered]
        self.product_grid.set_cards(cards)
        self.menu_count.setText(f"{len(filtered)} 道可选餐品")
        self.menu_empty.setVisible(not filtered)

    def _refresh_cart(self):
        self.current_order = self.store.open_order(self.table_id)
        table = next(table for table in self.store.tables() if table["id"] == self.table_id)
        order = self.current_order
        self.cart_title.setText(table["name"])
        self.cart_badge.setText("用餐中" if order else "空闲")
        self.order_hint.setText(f"SM{order['id']:08d}  ·  {order['opened_at'][11:16]} 开单" if order else "添加餐品后自动开单")
        clear_layout(self.cart_items)
        for item in order["items"] if order else []:
            line = panel("CartLine")
            layout = vbox(line, 0, 7)
            layout.setContentsMargins(0, 12, 0, 12)
            row = hbox(spacing=5)
            row.addWidget(text(item["product_name"], wrap=True), 1)
            row.addWidget(text(f"￥{money(item['unit_cents'] * item['quantity'])}"))
            layout.addLayout(row)
            row = hbox(spacing=4)
            row.addWidget(text(f"￥{money(item['unit_cents'])} / 份", "small"))
            row.addStretch()
            minus = action("−", lambda data=item: self.change_quantity(data["id"], data["quantity"] - 1), width=32)
            plus = action("+", lambda data=item: self.change_quantity(data["id"], data["quantity"] + 1), width=32)
            for btn in (minus, plus):
                btn.setFixedSize(32, 30)
                btn.setStyleSheet("padding: 0;")
            row.addWidget(minus)
            number = action(str(item["quantity"]), lambda iid=item["id"]: self.edit_quantity(iid), "quiet", width=28)
            number.setFixedHeight(30)
            number.setStyleSheet("padding: 0;")
            number.setToolTip("点击输入数量")
            row.addWidget(number)
            row.addWidget(plus)
            remove = action("删除", lambda iid=item["id"]: self.remove_item(iid), "quiet")
            remove.setFixedHeight(30)
            remove.setStyleSheet("padding: 3px 7px;")
            row.addWidget(remove)
            layout.addLayout(row)
            self.cart_items.addWidget(line)
        self.cart_items.addStretch()
        has_items = bool(order and order["items"])
        self.cart_scroll.setVisible(has_items)
        self.empty_cart.setVisible(not has_items)
        self.item_count.setText(f"共 {sum(item['quantity'] for item in order['items']) if order else 0} 份餐品")
        self.cart_total.setText(f"￥{money(order['total_cents'] if order else 0)}")
        self.checkout_button.setEnabled(has_items)

    def select_table(self, table_id):
        self.table_id = table_id
        self._refresh_tables()
        self._refresh_cart()

    def add_item(self, product_id):
        def add():
            self.store.add_item(self.table_id, product_id, str(self.add_quantity.value()))
            self.add_quantity.setValue(1)
            self._refresh_tables()
            self._refresh_cart()
            self.status.setText("● 已加入本桌账单")
        self.run_action(add)

    def change_quantity(self, item_id, quantity):
        if quantity < 1:
            self.remove_item(item_id)
            return
        def change():
            self.store.set_quantity(self.current_order["id"], item_id, str(quantity))
            self._refresh_tables()
            self._refresh_cart()
            self.status.setText("● 餐品数量已保存")
        self.run_action(change)

    def remove_item(self, item_id):
        def remove():
            self.store.remove_item(self.current_order["id"], item_id)
            self.refresh()
            self.status.setText("● 已从本桌账单删除餐品")
        self.run_action(remove)

    def edit_quantity(self, item_id):
        item = next(item for item in self.current_order["items"] if item["id"] == item_id)
        dialog = ThemedDialog(self)
        dialog.setWindowTitle("修改数量")
        dialog.setMinimumWidth(340)
        layout = vbox(dialog, 24, 16)
        layout.addWidget(text(item["product_name"], "heading", wrap=True))
        quantity = QSpinBox()
        quantity.setRange(1, 999)
        quantity.setValue(item["quantity"])
        quantity.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addWidget(quantity)
        row = hbox()
        row.addWidget(action("返回", dialog.reject))
        def save():
            self.change_quantity(item_id, quantity.value())
            dialog.accept()
        row.addWidget(action("保存数量", save, "primary"))
        layout.addLayout(row)
        self.quantity_dialog = dialog
        dialog.open()
        quantity.setFocus()
        quantity.selectAll()

    def cancel_order(self):
        if self.current_order and confirm(self, "取消本桌订单", "确认取消本桌全部餐品？取消记录会保留。"):
            def cancel():
                self.store.cancel_order(self.current_order["id"])
                self.refresh()
                self.status.setText("● 本桌订单已取消")
            self.run_action(cancel)

    def open_checkout(self):
        self._refresh_cart()
        if self.current_order and self.current_order["items"]:
            self.checkout_dialog = CheckoutDialog(self, self.current_order)
            self.checkout_dialog.open()

    def undo_delete(self):
        if self.last_deleted:
            product_id, active = self.last_deleted
            def undo():
                self.store.restore_product(product_id, active)
                self.last_deleted = None
                self.undo_button.hide()
                self.refresh()
                self.status.setText("● 已恢复餐品")
            self.run_action(undo)

    def enqueue_print(self, order):
        printer = self.store.settings()["printer_name"]
        if not printer:
            notify(self, "未选择打印机", "结算记录已保存。请先在系统设置选择打印机，再通过历史订单补打。")
            return
        if order["id"] in self.printing_ids:
            self.status.setText("该账单正在提交打印，请稍候")
            return
        self.printing_ids.add(order["id"])
        self.status.setText(f"SM{order['id']:08d} · 正在提交打印…")
        def worker():
            try:
                job = print_receipt(printer, order["receipt_text"], f"三木结算单 SM{order['id']:08d}")
                self.print_queue.put((order["id"], "", job))
            except Exception as error:
                logging.exception("打印失败")
                self.print_queue.put((order["id"], str(error), None))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_print(self):
        try:
            while True:
                order_id, error, job = self.print_queue.get_nowait()
                self.printing_ids.discard(order_id)
                self.run_action(lambda: self.store.record_print(order_id, error))
                if error:
                    self.status.setText("打印失败，账单已保存，可在历史订单补打")
                    notify(self, "打印未完成", f"结算记录已保存，无需再次结算。\n\n{error}", True)
                else:
                    self.status.setText(f"SM{order_id:08d} 已提交 Windows 打印队列（任务 {job}）")
                self.history_page.refresh()
        except queue.Empty:
            pass

    def closeEvent(self, event):
        if self.printing_ids:
            notify(self, "打印进行中", "请等待打印任务提交完成后再退出。")
            event.ignore()
            return
        if not self.closed:
            self.timer.stop()
            self.store.close()
            self.closed = True
        event.accept()


class ProductsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.product_id = app, None
        self.setObjectName("Page")
        outer = hbox(self, 22, 20)
        left = panel()
        left_layout = vbox(left, 20, 16)
        top = hbox()
        top.addWidget(text("餐品列表", "heading"))
        self.counter = text("", "muted")
        top.addWidget(self.counter)
        top.addStretch()
        top.addWidget(action("＋ 新增餐品", self.clear, "primary"))
        left_layout.addLayout(top)
        self.search = input_field("按餐品名称搜索")
        self.search.textChanged.connect(self.refresh)
        left_layout.addWidget(self.search)
        self.view = data_table(["餐品名称", "分类", "单价 / 元", "状态"])
        self.view.itemSelectionChanged.connect(self.select)
        left_layout.addWidget(self.view, 1)
        left_layout.addWidget(text("点击一行编辑餐品；下架后不参与点餐，删除后从菜单移除。", "small", wrap=True))
        outer.addWidget(left, 3)
        form = panel()
        form.setFixedWidth(320)
        layout = vbox(form, 22, 13)
        self.form_title = text("新增餐品", "heading")
        layout.addWidget(self.form_title)
        layout.addWidget(text("维护店内菜单和销售价格", "small"))
        layout.addSpacing(9)
        self.name = input_field("输入餐品名称")
        self.name.setMaxLength(40)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.setInsertPolicy(QComboBox.NoInsert)
        self.category.lineEdit().setPlaceholderText("选择已有分类，或输入新分类")
        self.category.lineEdit().setMaxLength(20)
        self.price = input_field("例如 28.00")
        field(layout, "餐品名称", self.name)
        field(layout, "餐品分类", self.category)
        layout.addWidget(text("同名分类自动复用，留空归为未分类。", "small", wrap=True))
        field(layout, "售价（元）", self.price)
        self.active = QCheckBox("上架，可在点餐页选择")
        self.active.setChecked(True)
        layout.addWidget(self.active)
        layout.addWidget(action("保存餐品", self.save, "primary"))
        layout.addWidget(action("清空并新增", self.clear))
        self.delete_button = action("删除餐品", self.delete, "danger")
        self.delete_button.setEnabled(False)
        layout.addWidget(self.delete_button)
        layout.addStretch()
        layout.addWidget(text("首次使用默认 3 道示例餐品。\n请按实际菜单调整。", "small", wrap=True))
        outer.addWidget(form)

    def refresh(self, *args):
        products = self.app.store.products(True)
        query = self.search.text().strip().casefold()
        fill_table(self.view, [(product["id"], (product["name"], product["category"], money(product["price_cents"]),
                    "上架" if product["active"] else "下架")) for product in products if query in product["name"].casefold()])
        self.counter.setText(f"{len(products)} 道餐品")
        update_combo(self.category, self.app.store.categories())

    def select(self):
        selected = selected_id(self.view)
        if selected is None:
            return
        product = next((product for product in self.app.store.products(True) if product["id"] == selected), None)
        if not product:
            return
        self.product_id = selected
        self.form_title.setText("编辑餐品")
        self.name.setText(product["name"])
        self.category.setEditText(product["category"])
        self.price.setText(money(product["price_cents"]))
        self.active.setChecked(bool(product["active"]))
        self.delete_button.setEnabled(True)

    def clear(self):
        self.view.clearSelection()
        self.view.setCurrentItem(None)
        self.product_id = None
        self.form_title.setText("新增餐品")
        self.name.clear()
        self.category.setEditText("")
        self.price.clear()
        self.active.setChecked(True)
        self.delete_button.setEnabled(False)
        self.name.setFocus()

    def save(self):
        def save():
            record_id = self.app.store.save_product(self.name.text(), self.category.currentText(), self.price.text(),
                                                     self.active.isChecked(), self.product_id)
            self.product_id = record_id
            self.form_title.setText("编辑餐品")
            self.delete_button.setEnabled(True)
            self.app.refresh()
            for row in range(self.view.rowCount()):
                if self.view.item(row, 0).data(Qt.UserRole) == record_id:
                    self.view.selectRow(row)
                    break
            self.app.status.setText("● 餐品已保存")
        self.app.run_action(save)

    def delete(self):
        if self.product_id is None:
            return
        def remove():
            product = next(p for p in self.app.store.products(True) if p["id"] == self.product_id)
            self.app.store.delete_product(self.product_id)
            self.app.last_deleted = (self.product_id, bool(product["active"]))
            self.clear()
            self.app.refresh()
            self.app.status.setText(f"已删除“{product['name']}”")
            self.app.undo_button.show()
        self.app.run_action(remove)


class TablesPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self.table_id = app, None
        self.setObjectName("Page")
        outer = hbox(self, 22, 20)
        left = panel()
        layout = vbox(left, 20, 16)
        layout.addWidget(text("桌台列表", "heading"))
        layout.addWidget(text("可自定义名称，例如：靠窗 01、露台、大包厢。", "muted", wrap=True))
        self.view = data_table(["编号", "桌台名称", "当前状态", "当前金额"])
        self.view.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.view, 1)
        outer.addWidget(left, 3)
        right = panel()
        right.setFixedWidth(320)
        layout = vbox(right, 22, 13)
        layout.addWidget(text("修改桌台名称", "heading"))
        self.selected_label = text("请在左侧选择桌台", "muted")
        layout.addWidget(self.selected_label)
        self.name = input_field("例如：靠窗 01")
        self.name.setMaxLength(20)
        field(layout, "桌台名称", self.name)
        self.rename_button = action("保存名称", self.rename, "primary")
        self.rename_button.setEnabled(False)
        layout.addWidget(self.rename_button)
        layout.addWidget(text("当前订单同步更新名称，历史账单保持不变。", "small", wrap=True))
        layout.addSpacing(18)
        layout.addWidget(divider())
        layout.addSpacing(8)
        layout.addWidget(text("桌台数量", "heading"))
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addWidget(self.count)
        layout.addWidget(action("保存桌数", self.save_count))
        layout.addWidget(text("减少桌数时从最后的编号开始停用。\n有未结算订单的桌台不能停用。", "small", wrap=True))
        layout.addStretch()
        outer.addWidget(right)

    def refresh(self):
        tables = self.app.store.tables()
        self.count.setValue(len(tables))
        fill_table(self.view, [(t["id"], (f"{t['id']:02d}", t["name"], "用餐中" if t["order_id"] else "空闲",
                                         f"￥{money(t['total_cents'])}")) for t in tables])
        if self.table_id not in {table["id"] for table in tables}:
            self.table_id = None
            self.name.clear()
            self.selected_label.setText("请在左侧选择桌台")
            self.rename_button.setEnabled(False)

    def select_table(self, table_id):
        for row in range(self.view.rowCount()):
            if self.view.item(row, 0).data(Qt.UserRole) == table_id:
                self.view.selectRow(row)
                self.select()
                break

    def select(self):
        table_id = selected_id(self.view)
        if table_id is None:
            return
        table = next((t for t in self.app.store.tables() if t["id"] == table_id), None)
        if table:
            self.table_id = table_id
            self.selected_label.setText(f"正在编辑编号 {table_id:02d} 的桌台")
            self.name.setText(table["name"])
            self.rename_button.setEnabled(True)

    def rename(self):
        if self.table_id is not None:
            def rename():
                self.app.store.rename_table(self.table_id, self.name.text())
                self.app.refresh()
                self.app.status.setText("● 桌台名称已保存")
            self.app.run_action(rename)

    def save_count(self):
        def save():
            self.app.store.set_table_count(str(self.count.value()))
            self.app.refresh()
            self.app.status.setText("● 桌台数量已保存")
        self.app.run_action(save)


class CheckoutDialog(ThemedDialog):
    def __init__(self, app, order):
        super().__init__(app)
        self.app, self.order = app, order
        self.setWindowTitle("确认结算")
        self.setMinimumWidth(470)
        self.resize(510, 640)
        layout = vbox(self, 28, 12)
        layout.addWidget(text("确认结算", "title"))
        layout.addWidget(text(f"{order['table_name']}  ·  SM{order['id']:08d}", "muted"))
        layout.addWidget(divider())
        subtotal = hbox()
        subtotal.addWidget(text("餐品合计", "muted"))
        subtotal.addStretch()
        subtotal.addWidget(text(f"￥{money(order['total_cents'])}", "price"))
        layout.addLayout(subtotal)
        self.base = input_field(value=money(order["total_cents"]))
        self.discount = input_field("10 不打折，8.5 八五折", "10")
        self.note = input_field("选填，例如：抹零或优惠说明")
        self.note.setMaxLength(200)
        field(layout, "结算金额（元，可修改）", self.base)
        field(layout, "折扣（折）", self.discount)
        layout.addWidget(text("10 = 原价   ·   8.5 = 八五折   ·   0 = 免单", "small"))
        field(layout, "结算备注", self.note)
        total = panel("SubPanel")
        total_layout = vbox(total, 18, 5)
        total_layout.addWidget(text("最终实收", "muted"))
        self.final = text("", "amount")
        self.final.setAlignment(Qt.AlignRight)
        total_layout.addWidget(self.final)
        layout.addWidget(total)
        self.error = text("", "error", wrap=True)
        layout.addWidget(self.error)
        self.print_after = QCheckBox("结算后打印小票")
        self.print_after.setChecked(app.store.settings()["auto_print"])
        layout.addWidget(self.print_after)
        layout.addStretch()
        row = hbox()
        row.addWidget(action("返回核对", self.reject))
        self.confirm_button = action("确认收款并结算", self.submit, "primary")
        row.addWidget(self.confirm_button, 1)
        layout.addLayout(row)
        self.base.textChanged.connect(self.recalculate)
        self.discount.textChanged.connect(self.recalculate)
        self.recalculate()

    def recalculate(self, *args):
        try:
            final = discounted_cents(to_cents(self.base.text(), "结算金额"), self.discount.text())
            self.final.setText(f"￥{money(final)}")
            self.error.hide()
            self.confirm_button.setEnabled(True)
        except ValidationError as error:
            self.final.setText("—")
            self.error.setText(str(error))
            self.error.show()
            self.confirm_button.setEnabled(False)

    def submit(self):
        if not confirm(self, "确认已收款", f"{self.order['table_name']} 最终实收 {self.final.text()}\n确认已收款并完成结算？"):
            return
        self.confirm_button.setEnabled(False)
        try:
            paid = self.app.store.checkout(self.order["id"], self.base.text(), self.discount.text(),
                                           self.note.text(), self.order["revision"])
        except (ValidationError, sqlite3.Error) as error:
            notify(self, "结算未完成", str(error), True)
            self.recalculate()
            return
        self.app.refresh()
        self.app.status.setText(f"● SM{paid['id']:08d} 已结算 · 实收 ￥{money(paid['final_cents'])}")
        print_after = self.print_after.isChecked()
        self.accept()
        if print_after:
            self.app.enqueue_print(paid)


class HistoryPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.preview_dialog = None
        self.setObjectName("Page")
        outer = vbox(self, 22)
        content = panel()
        layout = vbox(content, 22, 16)
        top = hbox()
        top.addWidget(text("历史账单", "heading"))
        top.addStretch()
        self.date = input_field("YYYY-MM-DD", datetime.now().strftime("%Y-%m-%d"))
        self.date.setFixedWidth(170)
        self.filter_date = self.date.text()
        top.addWidget(self.date)
        top.addWidget(action("查询", lambda: app.run_action(self.search)))
        top.addWidget(action("全部记录", self.show_all))
        top.addWidget(action("查看小票 / 补打", self.preview, "primary"))
        layout.addLayout(top)
        self.view = data_table(["单号", "桌台", "结算 / 取消时间", "状态", "餐品合计", "实收 / 元", "打印状态"])
        self.view.itemDoubleClicked.connect(lambda *args: self.preview())
        layout.addWidget(self.view, 1)
        self.summary = text("", "muted")
        layout.addWidget(self.summary)
        outer.addWidget(content)

    def refresh(self):
        orders = self.app.store.history(self.filter_date)
        fill_table(self.view, [(order["id"], (f"SM{order['id']:08d}", order["table_name"], order["closed_at"],
                    "已结算" if order["status"] == "paid" else "已取消",
                    money(order["subtotal_cents"]) if order["status"] == "paid" else "—",
                    money(order["final_cents"]) if order["status"] == "paid" else "—",
                    order["print_status"] if order["status"] == "paid" else "—")) for order in orders])
        paid = [order for order in orders if order["status"] == "paid"]
        self.summary.setText(f"已结算 {len(paid)} 单    ·    实收 ￥{money(sum(order['final_cents'] for order in paid))}    ·    已取消 {len(orders)-len(paid)} 单")

    def search(self):
        selected_date = self.date.text().strip()
        self.app.store.history(selected_date)
        self.filter_date = selected_date
        self.refresh()

    def show_all(self):
        self.date.clear()
        self.filter_date = ""
        self.refresh()

    def preview(self):
        order_id = selected_id(self.view)
        if order_id is None:
            self.app.status.setText("请先选择一笔历史订单")
            return
        self.preview_dialog = ReceiptDialog(self.app, self.app.store.order(order_id))
        self.preview_dialog.open()


class ReceiptDialog(ThemedDialog):
    def __init__(self, app, order):
        super().__init__(app)
        self.setWindowTitle(f"SM{order['id']:08d} · 订单详情")
        self.resize(590, 740)
        self.setMinimumSize(460, 520)
        layout = vbox(self, 24, 16)
        layout.addWidget(text("结算小票" if order["status"] == "paid" else "取消记录", "heading"))
        paid = order["status"] == "paid"
        self.receipt = order["receipt_text"] if paid else (
            f"已取消订单 SM{order['id']:08d}\n桌台：{order['table_name']}\n取消时间：{order['closed_at']}\n\n" +
            "\n".join(f"{item['product_name']} × {item['quantity']}  ￥{money(item['unit_cents'] * item['quantity'])}" for item in order["items"]))
        self.view = QPlainTextEdit(self.receipt)
        self.view.setReadOnly(True)
        layout.addWidget(self.view, 1)
        row = hbox()
        def export():
            filename = save_file(self, "导出文本小票", f"SM{order['id']:08d}.txt", "文本小票 (*.txt)")
            if filename:
                app.run_action(lambda: Path(filename).write_text(self.receipt, encoding="utf-8"))
        row.addWidget(action("导出文本", export))
        row.addStretch()
        row.addWidget(action("关闭", self.reject))
        if paid:
            row.addWidget(action("打印 / 补打", lambda: app.enqueue_print(order), "primary"))
        layout.addLayout(row)


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("Page")
        outer = hbox(self, 22, 20)
        left = panel()
        layout = vbox(left, 24, 12)
        settings = app.store.settings()
        layout.addWidget(text("店铺与小票", "heading"))
        layout.addWidget(text("收款确认后，可自动打印本桌结算单。", "muted", wrap=True))
        layout.addSpacing(8)
        self.shop = input_field(value=settings["shop_name"])
        self.shop.setMaxLength(40)
        self.footer = input_field(value=settings["receipt_footer"])
        self.footer.setMaxLength(80)
        field(layout, "小票店名", self.shop)
        field(layout, "小票页脚", self.footer)
        layout.addWidget(text("Windows 打印机", "muted"))
        row = hbox()
        self.printer = QComboBox()
        self.printer.addItems([""] + ([settings["printer_name"]] if settings["printer_name"] else []))
        self.printer.setCurrentText(settings["printer_name"])
        row.addWidget(self.printer, 1)
        row.addWidget(action("刷新列表", self.load_printers))
        layout.addLayout(row)
        self.width = QComboBox()
        self.width.addItems(["58", "80"])
        self.width.setCurrentText(settings["paper_width"])
        field(layout, "小票纸宽（毫米）", self.width)
        self.auto = QCheckBox("结算时默认勾选打印小票")
        self.auto.setChecked(settings["auto_print"])
        layout.addWidget(self.auto)
        layout.addWidget(action("保存设置", self.save, "primary"))
        layout.addStretch()
        outer.addWidget(left, 1)
        right = panel()
        layout = vbox(right, 24, 16)
        layout.addWidget(text("打印与数据", "heading"))
        layout.addWidget(text("美团打印机", "heading"))
        layout.addWidget(text("支持提供 Windows 驱动的机型。安装对应驱动后，先在 Windows 打印测试页，再回到这里选择设备。\n\n纸张尺寸和切纸由驱动设置。仅支持美团云打印的设备仍需按具体型号接入。",
                              "muted", wrap=True))
        layout.addSpacing(8)
        layout.addWidget(divider())
        layout.addWidget(text("本地数据", "heading"))
        self.data_path = input_field(value=str(app.store.path))
        self.data_path.setReadOnly(True)
        layout.addWidget(self.data_path)
        layout.addWidget(action("备份数据库…", self.backup))
        layout.addWidget(text("桌台、餐品、未结算订单和历史账单自动保存。建议定期备份到另一块磁盘。", "muted", wrap=True))
        layout.addStretch()
        layout.addWidget(text("外观可在右上角切换：浅色、深色或跟随系统。", "small", wrap=True))
        outer.addWidget(right, 1)

    def load_printers(self):
        def load():
            printers = available_printers()
            update_combo(self.printer, [""] + printers)
            self.app.status.setText(f"检测到 {len(printers)} 台 Windows 打印机")
        self.app.run_action(load)

    def save(self):
        def save():
            self.app.store.save_settings(dict(shop_name=self.shop.text(), receipt_footer=self.footer.text(),
                printer_name=self.printer.currentText(), paper_width=self.width.currentText(), auto_print=self.auto.isChecked()))
            self.app.refresh()
            self.app.status.setText("● 店铺与打印设置已保存")
        self.app.run_action(save)

    def backup(self):
        filename = save_file(self, "备份数据库", f"sanmu-backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3", "SQLite 数据库 (*.sqlite3)")
        if filename:
            def save():
                self.app.store.backup(filename)
                self.app.status.setText(f"数据库已备份到 {filename}")
            self.app.run_action(save)
