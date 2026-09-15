"""Logo 展示与白纸小票预览。预览使用真实打印布局，独立于软件主题。"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from .branding import logo_image
from .receipt_render import ReceiptLayout
from .theme import PALETTES
from .widgets import action, hbox, text, vbox


class LogoBadge(QWidget):
    def __init__(self, size=38):
        super().__init__()
        self.png, self.image = None, None
        self.setFixedSize(size, size)
        self.setAccessibleName("店铺 Logo")

    def set_logo(self, data):
        if data != self.png:
            self.png = data
            self.image = logo_image(data) if data else None
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.image is not None:
            # 保留图片透明度，让透明区域直接透出所在界面的背景。
            size = self.image.size().scaled(self.size()-self.size()/5, Qt.KeepAspectRatio)
            painter.drawImage(QRectF((self.width()-size.width())/2, (self.height()-size.height())/2,
                                     size.width(), size.height()), self.image)
        else:
            palette = PALETTES[QApplication.instance().property("sanmuTheme") or "light"]
            painter.setPen(Qt.NoPen)
            painter.setBrush(palette["accent"])
            painter.drawRoundedRect(QRectF(self.rect()), 8, 8)
            painter.setPen(palette["text"] if palette is PALETTES["light"] else "#292213")
            letter = QFont("Microsoft YaHei")
            letter.setPixelSize(round(self.height() * .48))
            letter.setBold(True)
            painter.setFont(letter)
            painter.drawText(self.rect(), Qt.AlignCenter, "木")
        painter.end()


class ReceiptPreview(QWidget):
    def __init__(self, payload):
        super().__init__()
        self.receipt_layout = ReceiptLayout(payload)
        self.pages = self.receipt_layout.pages()
        self.page_index = 0
        layout = vbox(self, 0, 10)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.paper = QLabel()
        self.paper.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.paper.setContentsMargins(14, 14, 14, 14)
        self.paper.setAccessibleName("打印小票预览")
        self.area.setWidget(self.paper)
        layout.addWidget(self.area, 1)
        navigation = hbox()
        self.previous = action("上一页", lambda: self.change_page(-1))
        self.next = action("下一页", lambda: self.change_page(1))
        navigation.addWidget(self.previous)
        navigation.addStretch()
        self.page_label = text("", "small")
        navigation.addWidget(self.page_label)
        navigation.addStretch()
        navigation.addWidget(self.next)
        layout.addLayout(navigation)
        self.display_page()

    def change_page(self, delta):
        self.page_index = max(0, min(len(self.pages)-1, self.page_index+delta))
        self.display_page()
        self.area.verticalScrollBar().setValue(0)

    def display_page(self):
        self.image = self.receipt_layout.render(self.pages[self.page_index])
        self._fit()
        self.previous.setEnabled(self.page_index > 0)
        self.next.setEnabled(self.page_index < len(self.pages)-1)
        self.page_label.setText(f"{self.page_index+1} / {len(self.pages)} 页")

    def _fit(self):
        desired = 310 if self.receipt_layout.width == 464 else 410
        width = max(170, min(desired, self.area.viewport().width()-30))
        pixmap = QPixmap.fromImage(self.image).scaledToWidth(width, Qt.SmoothTransformation)
        self.paper.setPixmap(pixmap)
        self.paper.setMinimumHeight(pixmap.height()+28)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()
