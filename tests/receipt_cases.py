"""仅供测试和预览的示例数据，不包含营业数据或用户图片。"""
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter, QPen


def sample_logo(color=Qt.black):
    image = QImage(160, 120, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(color, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    # 三株几何小树，仅为功能测试图形。
    for x, top in ((40, 38), (80, 20), (120, 38)):
        painter.drawLine(x, top, x-22, top+37)
        painter.drawLine(x-22, top+37, x+22, top+37)
        painter.drawLine(x+22, top+37, x, top)
        painter.drawLine(x, top+37, x, 99)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def sample_receipt(width="80", logo=True, discount="10"):
    from sanmu.money import discounted_cents
    items = [dict(product_name="宫保鸡丁（微辣）", quantity=2, unit_cents=2800),
             dict(product_name="招牌香菇滑鸡煲仔饭(大份)", quantity=1, unit_cents=2600),
             dict(product_name="米饭", quantity=3, unit_cents=200),
             dict(product_name="酸梅汤", quantity=2, unit_cents=600)]
    total = sum(item["unit_cents"] * item["quantity"] for item in items)
    order = dict(id=18, status="paid", table_name="靠窗 01", opened_at="2026-09-16 12:06:30",
                 closed_at="2026-09-16 12:48:16", items=items, subtotal_cents=total,
                 base_cents=total, discount=discount, final_cents=discounted_cents(total, discount), note="")
    style = dict(version=1, shop_name="三木餐厅", receipt_footer="谢谢惠顾，欢迎再次光临！", paper_width=width, logo_id="")
    return dict(order=order, style=style, logo_png=sample_logo() if logo else b"")
