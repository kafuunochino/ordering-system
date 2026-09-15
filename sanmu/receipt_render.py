"""小票图形排版。预览与 Windows 打印共用相同坐标，按实际字宽对齐。"""

from dataclasses import dataclass
from math import ceil

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

from .branding import logo_image
from .money import ValidationError, money
from .receipts import receipt_text, summary_rows


def font(size, bold=False):
    result = QFont("Microsoft YaHei")
    result.setPixelSize(size)
    result.setBold(bold)
    return result


def wrapped(value, width, size, bold=False):
    metrics = QFontMetricsF(font(size, bold))
    lines, line = [], ""
    for character in receipt_text(value):
        if line and metrics.horizontalAdvance(line + character) > width:
            lines.append(line)
            line = ""
        line += character
    lines.append(line)
    return lines


@dataclass
class Block:
    height: float
    # Commands: (kind, QRectF, content, font size, alignment, bold)
    commands: list


@dataclass
class Page:
    height: int
    commands: list


class ReceiptLayout:
    def __init__(self, payload):
        self.payload = payload
        self.width = 464 if payload["style"]["paper_width"] == "58" else 640
        self.margin = 16
        self.inner = self.width - 2 * self.margin
        self.blocks = []
        self._build()

    def _line(self, value, size=21, align=Qt.AlignLeft, bold=False, gap=3):
        height = ceil(QFontMetricsF(font(size, bold)).height()) + 5
        for line in wrapped(value, self.inner, size, bold):
            self.blocks.append(Block(height + gap, [("text", QRectF(self.margin, 0, self.inner, height),
                                                      line, size, align, bold)]))

    def _space(self, height=8):
        self.blocks.append(Block(height, []))

    def _rule(self):
        self.blocks.append(Block(19, [("rule", QRectF(self.margin, 9, self.inner, 0), None, 0, 0, False)]))

    def _pair(self, label, value, size=21, bold=False):
        metrics = QFontMetricsF(font(size, bold))
        label_width = metrics.horizontalAdvance(label) + 16
        height = ceil(metrics.height()) + 7
        lines = wrapped(value, self.inner - label_width, size, bold)
        commands = [("text", QRectF(self.margin, 0, label_width, height), label, size, Qt.AlignLeft, bold)]
        commands.extend(("text", QRectF(self.margin + label_width, index * height,
                         self.inner - label_width, height), line, size, Qt.AlignRight, bold)
                        for index, line in enumerate(lines))
        self.blocks.append(Block(height * len(lines) + 4, commands))

    def _build(self):
        order, style = self.payload["order"], self.payload["style"]
        if self.payload.get("logo_png"):
            image = logo_image(self.payload["logo_png"])
            # 热敏小票以白底黑白图呈现，软件品牌图保留原始颜色和透明度。
            white = QImage(image.size(), QImage.Format_RGB32)
            white.fill(Qt.white)
            painter = QPainter(white)
            painter.drawImage(0, 0, image)
            painter.end()
            image = white.convertToFormat(QImage.Format_Grayscale8)
            ratio = min(self.inner * .5 / image.width(), 136 / image.height())
            width, height = image.width() * ratio, image.height() * ratio
            self.blocks.append(Block(height + 14, [("image", QRectF((self.width-width)/2, 0, width, height),
                                                     image, 0, 0, False)]))
        self._line(style["shop_name"], 30, Qt.AlignHCenter, True, 5)
        self._line("结 算 单", 23, Qt.AlignHCenter, gap=7)
        self._rule()
        self._pair("单号", f"SM{order['id']:08d}", 19)
        self._pair("桌台", receipt_text(order["table_name"]), 19)
        self._pair("开单", order["opened_at"], 19)
        self._pair("结算", order["closed_at"], 19)
        self._rule()
        size = 19 if self.width == 464 else 21
        metrics = QFontMetricsF(font(size))
        labels = ("数量", "单价", "金额")
        numeric = [(str(item["quantity"]), money(item["unit_cents"]), money(item["unit_cents"] * item["quantity"]))
                   for item in order["items"]]
        widths = [max(QFontMetricsF(font(size, True)).horizontalAdvance(label),
                      max((metrics.horizontalAdvance(values[index]) for values in numeric), default=0)) + 6
                  for index, label in enumerate(labels)]
        gap = 14
        name_width = self.inner - sum(widths) - gap * 3
        x = [self.margin, self.margin + name_width + gap]
        x.extend((x[1] + widths[0] + gap, x[1] + widths[0] + widths[1] + 2 * gap))
        widths = [name_width, *widths]
        row_height = ceil(metrics.height()) + 7
        header = [("text", QRectF(x[index], 0, widths[index], row_height), label,
                    size, Qt.AlignLeft if index == 0 else Qt.AlignRight, True)
                  for index, label in enumerate(("餐品", *labels))]
        self.blocks.append(Block(row_height + 10, header))
        for item, values in zip(order["items"], numeric):
            names = wrapped(item["product_name"], name_width, size)
            commands = [("text", QRectF(x[0], index * row_height, name_width, row_height),
                          name, size, Qt.AlignLeft, False) for index, name in enumerate(names)]
            commands.extend(("text", QRectF(x[index+1], 0, widths[index+1], row_height), value,
                              size, Qt.AlignRight, False) for index, value in enumerate(values))
            self.blocks.append(Block(len(names) * row_height + 10, commands))
        self._rule()
        for label, value in summary_rows(order):
            final = label == "最终实收"
            if final:
                self._space(5)
            self._pair(label, value, 27 if final else 21, final)
        note = receipt_text(order.get("note", ""))
        if note:
            self._space()
            self._line(f"备注：{note}", 19)
        self._rule()
        self._line(style["receipt_footer"], 20, Qt.AlignHCenter, gap=4)

    def pages(self, max_height=2400) -> list[Page]:
        result, commands, y = [], [], self.margin
        for block in self.blocks:
            if block.height + 2 * self.margin > max_height:
                raise ValidationError("打印纸长度过短，无法容纳一行餐品或 Logo，请调整驱动纸张长度。")
            if y + block.height > max_height - self.margin and commands:
                result.append(Page(ceil(y + self.margin), commands))
                commands, y = [], self.margin
            for kind, rect, value, size, align, bold in block.commands:
                rect = rect.translated(0, y)
                commands.append((kind, rect, value, size, align, bold))
            y += block.height
        if commands:
            result.append(Page(ceil(y + self.margin), commands))
        return result

    def render(self, page: Page, pixel_width=None, dpi_ratio=1.0) -> QImage:
        pixel_width = pixel_width or self.width
        scale = pixel_width / self.width
        image = QImage(pixel_width, ceil(page.height * scale * dpi_ratio), QImage.Format_RGB32)
        if image.isNull():
            raise ValidationError("打印图像尺寸过大，请降低驱动分辨率。")
        image.fill(Qt.white)
        painter = QPainter(image)
        try:
            painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            painter.scale(scale, scale * dpi_ratio)
            for kind, rect, value, size, align, bold in page.commands:
                if kind == "text":
                    painter.setPen(Qt.black)
                    painter.setFont(font(size, bold))
                    painter.drawText(rect, align | Qt.AlignVCenter, value)
                elif kind == "image":
                    painter.drawImage(rect, value)
                else:
                    painter.setPen(QPen(QColor("#333333"), 1, Qt.DashLine))
                    painter.drawLine(rect.topLeft(), rect.topRight())
        finally:
            painter.end()
        return image
