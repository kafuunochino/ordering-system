"""用独立示例数据离屏渲染界面，不捕获或控制用户桌面。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
from pathlib import Path
import tempfile

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
        store.rename_table(3, "露台 01")
        store.rename_table(4, "露台 02")
        store.rename_table(7, "三木包厢")
        for product in store.products():
            store.add_item(1, product["id"], "2" if product["name"] == "米饭" else "1")
        store.add_item(2, store.products()[1]["id"], "2")
        app = App(store)
        app.show()
        app.resize(1440, 900)
        for mode, index in (("light", 0), ("dark", 1)):
            app.theme_combo.setCurrentIndex(index)
            for page, label in ((0, "cashier"), (1, "products"), (2, "tables"), (5, "settings")):
                app.navigate(page)
                QTest.qWait(60)
                app.grab().save(str(args.out_dir / f"{label}-{mode}.png"))
            app.navigate(0)
            app.open_checkout()
            dialog = app.checkout_dialog
            dialog.base.setText("38")
            dialog.discount.setText("8.5")
            QTest.qWait(60)
            dialog.grab().save(str(args.out_dir / f"checkout-{mode}.png"))
            dialog.reject()
        app.navigate(0)
        app.resize(1100, 700)
        QTest.qWait(60)
        app.grab().save(str(args.out_dir / "cashier-dark-small.png"))
        app.close()


if __name__ == "__main__":
    main()
