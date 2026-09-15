"""离屏生成可调收银台的两种主题预览，使用独立示例数据。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
from pathlib import Path
import tempfile

from PySide6.QtCore import QPoint, Qt
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
        for table_id, name in ((1, "靠窗 01"), (2, "靠窗 02"), (3, "露台 01"),
                               (4, "露台 02"), (7, "三木包厢")):
            store.rename_table(table_id, name)
        for product in store.products():
            store.add_item(1, product["id"], "2" if product["name"] == "米饭" else "1")
        store.add_item(3, store.products()[1]["id"], "2")
        store.add_item(5, store.products()[0]["id"], "3")
        app = App(store)
        app.show()
        QTest.qWait(30)
        for index, distance in ((1, 140), (2, -60)):
            handle = app.order_splitter.handle(index)
            start = handle.rect().center()
            destination = handle.mapToGlobal(start) + QPoint(distance, 0)
            QTest.mousePress(handle, Qt.LeftButton, pos=start)
            QTest.mouseMove(handle, handle.mapFromGlobal(destination), delay=20)
            QTest.mouseRelease(handle, Qt.LeftButton, pos=handle.mapFromGlobal(destination))
        for index, mode in ((0, "light"), (1, "dark")):
            app.theme_combo.setCurrentIndex(index)
            handle = app.order_splitter.handle(1)
            QTest.mouseMove(handle, handle.rect().center())
            QTest.qWait(50)
            app.grab().save(str(args.out_dir / f"sanmu-panels-{mode}.png"))
        app.close()


if __name__ == "__main__":
    main()
