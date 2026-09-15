"""离屏生成示例小票和品牌设置预览，不访问打印机或真实店铺数据。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
from pathlib import Path
import tempfile

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanmu.receipt_render import ReceiptLayout
from sanmu.storage import Store
from sanmu.ui import App, ReceiptDialog
from tests.receipt_cases import sample_logo, sample_receipt


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
        store.save_logo(sample_logo())
        store.save_settings(dict(store.settings(), shop_name="三木餐厅"))
        app = App(store)
        app.show()
        for width in ("58", "80"):
            for discount in ("10", "8.5"):
                layout = ReceiptLayout(sample_receipt(width, discount=discount))
                layout.render(layout.pages()[0]).save(str(args.out_dir / f"receipt-{width}-{discount}.png"))
        for theme, index in (("light", 0), ("dark", 1)):
            app.theme_combo.setCurrentIndex(index)
            app.navigate(5)
            app.resize(1440, 900)
            QTest.qWait(50)
            app.grab().save(str(args.out_dir / f"branding-{theme}.png"))
            payload = sample_receipt()
            dialog = ReceiptDialog(app, payload["order"], payload, sample=True)
            dialog.open()
            QTest.qWait(50)
            dialog.grab().save(str(args.out_dir / f"receipt-dialog-{theme}.png"))
            dialog.close()
        app.resize(1100, 700)
        QTest.qWait(50)
        app.grab().save(str(args.out_dir / "branding-small.png"))
        app.close()


if __name__ == "__main__":
    main()
