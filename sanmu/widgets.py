"""小型 Qt 组件。布局依赖真实可用宽度，操作区不会被列表挤出窗口。"""

from math import ceil

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QDate, QLocale, QEvent, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPalette, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QCalendarWidget, QDateEdit, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QStyle, QStyleOptionButton, QToolButton, QApplication,
                               QSplitter, QSplitterHandle, QSizePolicy)

from .theme import PALETTES


class PanelSplitter(QSplitter):
    """可拖动的收银台三栏；在首次可见时恢复比例，刷新内容不重置宽度。"""
    sizesCommitted = Signal(list)
    DEFAULT_SIZES = [270, 602, 360]

    def __init__(self, sizes=None):
        super().__init__(Qt.Horizontal)
        self.setObjectName("CashierSplitter")
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        self.setHandleWidth(16)
        valid = isinstance(sizes, list) and len(sizes) == 3 and all(type(v) is int and 0 < v <= 100000 for v in sizes)
        self.initial_sizes = sizes[:] if valid else self.DEFAULT_SIZES[:]
        self.restored = False

    def createHandle(self):
        return PanelHandle(self.orientation(), self)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.restored:
            self.setSizes(self.initial_sizes)
            self.restored = True

    def reset_sizes(self):
        self.setSizes(self.DEFAULT_SIZES)
        self.sizesCommitted.emit(self.sizes())


class PanelHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.hovered = self.dragging = False
        self.before_drag = []
        self.setCursor(Qt.SplitHCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("按住分隔线左右拖动；双击恢复默认布局")

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.before_drag = self.splitter().sizes()
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.update()
            if self.before_drag != self.splitter().sizes():
                self.splitter().sizesCommitted.emit(self.splitter().sizes())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.splitter().reset_sizes()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.moveSplitter(self.pos().x() + (20 if event.key() == Qt.Key_Right else -20))
            self.splitter().sizesCommitted.emit(self.splitter().sizes())
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        colors = PALETTES[QApplication.instance().property("sanmuTheme") or "light"]
        active = self.hovered or self.dragging or self.hasFocus()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if active:
            painter.fillRect(self.rect(), QColor(colors["soft"]))
        x = self.width() / 2
        painter.setPen(QPen(QColor(colors["accent"] if active else colors["line"]), 1))
        painter.drawLine(QPointF(x, 12), QPointF(x, self.height()-12))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors["accent"] if active else colors["muted"]))
        painter.drawRoundedRect(QRectF(x-2, self.height()/2-20, 4, 40), 2, 2)
        painter.end()


class ComboBox(QComboBox):
    """明确可见的下拉箭头，颜色随应用主题变化。"""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.Text), 1.6, Qt.SolidLine, Qt.RoundCap))
        x, y = self.width() - 15, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))
        painter.end()


class DateEdit(QDateEdit):
    """带中文日历弹层的日期选择器；日历入口在深浅主题中均清晰可见。"""
    def __init__(self, value=None):
        super().__init__(value or QDate.currentDate())
        self.setLocale(QLocale("zh_CN"))
        self.setDisplayFormat("yyyy-MM-dd")
        self.setDateRange(QDate(1900, 1, 1), QDate(9998, 12, 31))
        self.setCalendarPopup(True)
        self.setKeyboardTracking(False)
        self.setFixedWidth(168)
        self.setToolTip("点击右侧日历图标选择日期")
        calendar = self.calendarWidget()
        calendar.setLocale(self.locale())
        calendar.setFirstDayOfWeek(Qt.Monday)
        calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar.setMinimumSize(320, 282)
        self._update_calendar_theme()

    def _update_calendar_theme(self):
        calendar = self.calendarWidget()
        if calendar is None:
            return
        colors = PALETTES[QApplication.instance().property("sanmuTheme") or "light"]
        for name, direction in (("qt_calendar_prevmonth", "previous"), ("qt_calendar_nextmonth", "next")):
            button = calendar.findChild(QToolButton, name)
            if button:
                button.setArrowType(Qt.NoArrow)
                button.setIcon(line_icon(direction, colors["text"]))
                button.setIconSize(QSize(16, 16))
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(colors["danger"]))
        calendar.setWeekdayTextFormat(Qt.Saturday, weekend)
        calendar.setWeekdayTextFormat(Qt.Sunday, weekend)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange) and self.calendarPopup():
            self._update_calendar_theme()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.Text), 1.4, Qt.SolidLine, Qt.RoundCap))
        x, y = self.width() - 25, self.height() / 2 - 7
        painter.drawRoundedRect(QRectF(x, y, 14, 14), 2, 2)
        painter.drawLine(QPointF(x, y + 5), QPointF(x + 14, y + 5))
        for offset in (4, 10):
            painter.drawLine(QPointF(x + offset, y - 2), QPointF(x + offset, y + 2))
        painter.end()


class CheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        painter.setBrush(palette.color(QPalette.Highlight if self.isChecked() else QPalette.Base))
        painter.setPen(QPen(palette.color(QPalette.Highlight if self.isChecked() else QPalette.PlaceholderText), 1))
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self.isChecked():
            painter.setPen(QPen(QColor("#292213"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawLine(QPointF(x+w*.23, y+h*.5), QPointF(x+w*.43, y+h*.7))
            painter.drawLine(QPointF(x+w*.43, y+h*.7), QPointF(x+w*.78, y+h*.28))
        painter.end()


def text(value="", role="", name="", wrap=False):
    widget = QLabel(value)
    widget.setProperty("role", role)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def action(title, callback=None, variant="", width=None):
    widget = QPushButton(title)
    widget.setProperty("variant", variant)
    widget.setCursor(Qt.PointingHandCursor)
    if width:
        widget.setFixedWidth(width)
    if callback:
        widget.clicked.connect(lambda checked=False: callback())
    return widget


def panel(name="Panel"):
    widget = QFrame()
    widget.setObjectName(name)
    return widget


def vbox(parent=None, margin=0, spacing=12):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def hbox(parent=None, margin=0, spacing=12):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def divider():
    widget = panel("Divider")
    widget.setFixedHeight(1)
    return widget


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def data_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(56)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setFocusPolicy(Qt.StrongFocus)
    return table


def selected_id(table):
    row = table.currentRow()
    item = table.item(row, 0)
    return item.data(Qt.UserRole) if item else None


def fill_table(table, rows):
    selected = selected_id(table)
    table.blockSignals(True)
    table.setRowCount(len(rows))
    table.clearSelection()
    table.setCurrentItem(None)
    for row, (record_id, values) in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.UserRole, record_id)
            if column:
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            table.setItem(row, column, item)
        if record_id == selected:
            table.selectRow(row)
    table.blockSignals(False)


class CardGrid(QWidget):
    def __init__(self, card_width=166, card_height=130, max_columns=4):
        super().__init__()
        self.card_width, self.card_height, self.max_columns = card_width, card_height, max_columns
        self.cards = []
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop)

    def set_cards(self, cards):
        clear_layout(self.grid)
        self.cards = cards
        self.columns = 0
        self.reflow()

    def reflow(self):
        columns = max(1, min(self.max_columns, (self.width() + 10) // (self.card_width + 10)))
        if columns == self.columns:
            return
        for card in self.cards:
            self.grid.removeWidget(card)
        for column in range(max(self.columns, columns)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.columns = columns
        for index, card in enumerate(self.cards):
            card.setFixedHeight(self.card_height)
            self.grid.addWidget(card, index // columns, index % columns)
        rows = ceil(len(self.cards) / columns)
        self.setMinimumHeight(max(0, rows * (self.card_height + 10) - 10))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


def tile(title, subtitle, price, callback, selectable=False, badge=False):
    card = action("", callback, "tile")
    card.setAccessibleName(title)
    card.setAccessibleDescription(f"{subtitle} {price}")
    card.setCheckable(selectable)
    card.setProperty("occupied", bool(selectable and badge))
    content = vbox(card, 12 if selectable else 14, 7 if selectable else 6)
    title_label = text(title, name="TileTitle", wrap=True)
    title_label.setToolTip(title)
    title_label.setMaximumHeight(42)
    content.addWidget(title_label)
    if selectable:
        state = text(f"● {subtitle}" if badge else subtitle, name="TableState")
        state.setProperty("occupied", bool(badge))
        state.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        content.addWidget(state)
    else:
        content.addWidget(text(subtitle, "small"))
    content.addStretch()
    bottom = hbox(spacing=5)
    bottom.addWidget(text(price, "" if selectable else "price", name="TableAmount" if selectable else ""))
    bottom.addStretch()
    if not selectable:
        add = text("+", name="AddDot")
        add.setAlignment(Qt.AlignCenter)
        add.setFixedSize(28, 28)
        bottom.addWidget(add)
    content.addLayout(bottom)
    for child in card.findChildren(QLabel):
        child.setAttribute(Qt.WA_TransparentForMouseEvents)
    return card


def line_icon(kind, color="#ABB5C5"):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "tables":
        for x in (3, 14):
            for y in (3, 14):
                painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.5, 1.5)
    elif kind == "menu":
        painter.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
        for y in (8, 12, 16):
            painter.drawLine(9, y, 16, y)
    elif kind == "history":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawLine(12, 7, 12, 12)
        painter.drawLine(12, 12, 16, 14)
    elif kind == "revenue":
        painter.drawLine(3, 21, 21, 21)
        for x, top in ((5, 13), (11, 8), (17, 3)):
            painter.drawRoundedRect(QRectF(x, top, 3, 18 - top), 1, 1)
    elif kind in ("previous", "next"):
        edge, tip = (15, 8) if kind == "previous" else (9, 16)
        painter.drawLine(edge, 5, tip, 12)
        painter.drawLine(tip, 12, edge, 19)
    elif kind == "settings":
        for y, x in ((6, 9), (12, 16), (18, 7)):
            painter.drawLine(3, y, 21, y)
            painter.fillRect(x - 2, y - 2, 4, 4, QColor(color))
    else:
        painter.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
        painter.drawLine(3, 10, 21, 10)
        painter.drawLine(11, 10, 11, 19)
    painter.end()
    return QIcon(pixmap)
