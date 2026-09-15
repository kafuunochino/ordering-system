"""用独立示例账单渲染收入、筛选和日历，不读取店铺营业数据。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanmu.storage import Store
from sanmu.ui import App


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    qt = QApplication([])
    qt.setStyle("Fusion")
    qt.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "preview.sqlite3")
        store.rename_table(1, "靠窗 01")
        store.rename_table(2, "三木包厢")
        for month in (8, 9):
            for day in (3, 6, 9, 12, 15, 16):
                for index in range(1, 5):
                    with patch("sanmu.storage.timestamp", return_value=f"2026-{month:02d}-{day:02d} {12+index:02d}:25:30"):
                        table = index % 2 + 1
                        for product in store.products():
                            order_id = store.add_item(table, product["id"], str(index + 1))
                        if index == 3:
                            store.cancel_order(order_id)
                        else:
                            order = store.order(order_id)
                            store.checkout(order_id, str(36 * (index + 1)), "9.5", "", order["revision"])
        app = App(store)
        app.show()
        page = app.revenue_page
        for name, index in (("light", 0), ("dark", 1)):
            app.theme_combo.setCurrentIndex(index)
            app.resize(1440, 900)
            app.navigate(4)
            page.mode.setCurrentIndex(page.mode.findData("month"))
            page.year.setCurrentText("2026 年")
            page.month.setCurrentIndex(8)
            QTest.qWait(50)
            app.grab().save(str(args.out_dir / f"revenue-{name}.png"))
            page.mode.setCurrentIndex(page.mode.findData("year"))
            QTest.qWait(30)
            app.grab().save(str(args.out_dir / f"revenue-year-{name}.png"))
            app.navigate(3)
            history = app.history_page
            history.set_filters("2026-09-15", "2026-09-16")
            QTest.qWait(50)
            app.grab().save(str(args.out_dir / f"history-{name}.png"))
            QTest.mouseClick(history.date, Qt.LeftButton, pos=QPoint(history.date.width()-16, history.date.height()//2))
            QTest.qWait(30)
            history.date.calendarWidget().grab().save(str(args.out_dir / f"calendar-{name}.png"))
            QTest.keyClick(history.date.calendarWidget(), Qt.Key_Escape)
        app.navigate(4)
        app.resize(1100, 700)
        page.mode.setCurrentIndex(page.mode.findData("range"))
        page.date.setDate(QDate(2026, 9, 1))
        page.end_date.setDate(QDate(2026, 9, 16))
        QTest.qWait(50)
        app.grab().save(str(args.out_dir / "revenue-small.png"))
        app.close()


if __name__ == "__main__":
    main()
