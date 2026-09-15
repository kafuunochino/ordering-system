"""小型 Qt 组件。布局依赖真实可用宽度，操作区不会被列表挤出窗口。"""

from math import ceil

from PySide6.QtCore import Qt, QSize, QRectF, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QStyle, QStyleOptionButton)


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
    content = vbox(card, 14, 6)
    title_label = text(title, name="TileTitle", wrap=True)
    title_label.setToolTip(title)
    title_label.setMaximumHeight(42)
    content.addWidget(title_label)
    content.addWidget(text(subtitle, "success" if badge else "small"))
    content.addStretch()
    bottom = hbox(spacing=5)
    bottom.addWidget(text(price, "" if selectable else "price"))
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
