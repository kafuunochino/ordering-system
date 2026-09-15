from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from sanmu.branding import import_logo
from sanmu.money import ValidationError
from sanmu.receipts import display_width, format_receipt, receipt_text, legacy_receipt_style
from sanmu.storage import Store
from tests.receipt_cases import sample_logo, sample_receipt


class ReceiptContentTests(unittest.TestCase):
    def test_centered_heading_and_four_columns_hide_full_price_and_parentheses(self):
        for width in ("58", "80"):
            payload = sample_receipt(width)
            output = format_receipt(payload["order"], payload["style"])
            columns = 32 if width == "58" else 48
            first = output.splitlines()[0]
            left = len(first) - len(first.lstrip())
            right = columns - display_width(first)
            self.assertLessEqual(abs(left-right), 1)
            self.assertIn("餐品", output)
            self.assertIn("数量", output)
            self.assertIn("单价", output)
            self.assertIn("金额", output)
            self.assertNotIn("折扣", output)
            self.assertNotIn("原价", output)
            self.assertNotIn("微辣", output)
            self.assertNotIn("大份", output)
            self.assertTrue(all(display_width(line) <= columns for line in output.splitlines()))
            rice = next(line for line in output.splitlines() if line.startswith("米饭"))
            self.assertRegex(rice, r"米饭\s+3\s+2\.00\s+6\.00$")

    def test_real_discount_and_adjustments_keep_correct_amount_without_explanation(self):
        payload = sample_receipt(discount="8.5")
        output = format_receipt(payload["order"], payload["style"])
        self.assertRegex(output, r"折扣：\s*8\.5 折")
        self.assertRegex(output, r"最终实收：\s*￥85\.00")
        self.assertNotIn("（", output)
        self.assertNotIn("(", output)
        self.assertEqual(receipt_text("鸡肉（大份(加辣)）饭 (加料)"), "鸡肉饭")
        self.assertEqual(payload["order"]["items"][0]["product_name"], "宫保鸡丁（微辣）")

    def test_legacy_shop_footer_width_are_recovered_from_saved_receipt(self):
        old = "旧店名\n结 算 单\n" + "-"*32 + "\n账单内容\n" + "-"*32 + "\n旧页脚\n"
        style = legacy_receipt_style(old, dict(shop_name="新店名", receipt_footer="新页脚", logo_id="current"))
        self.assertEqual((style["shop_name"], style["receipt_footer"], style["paper_width"], style["logo_id"]),
                         ("旧店名", "旧页脚", "58", "current"))


class BrandingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "store.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_logo_import_survives_original_file_removal_restart_and_backup(self):
        filename = Path(self.temp.name) / "original.png"
        filename.write_bytes(sample_logo())
        png = import_logo(filename)
        asset = self.store.save_logo(png)
        self.assertEqual(self.store.save_logo(png), asset)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM branding_assets").fetchone()[0], 1)
        filename.unlink()
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.logo(), png)
        backup_path = Path(self.temp.name) / "backup.sqlite3"
        self.store.backup(backup_path)
        backup = Store(backup_path)
        try:
            self.assertEqual(backup.logo(), png)
        finally:
            backup.close()

    def test_replacing_or_removing_logo_preserves_paid_receipt_snapshot(self):
        logo = sample_logo()
        self.store.save_logo(logo)
        self.store.save_settings(dict(self.store.settings(), shop_name="成交时店名"))
        order_id = self.store.add_item(1, self.store.products()[0]["id"])
        order = self.store.order(order_id)
        self.store.checkout(order_id, "2", "10", "", order["revision"])
        original = self.store.receipt(order_id)
        self.store.save_logo(sample_logo(Qt.red))
        self.store.save_settings(dict(self.store.settings(), shop_name="新店名", paper_width="58"))
        self.store.remove_logo()
        self.assertEqual(self.store.logo(), b"")
        self.assertEqual(self.store.receipt(order_id), original)
        self.assertEqual(original["style"]["shop_name"], "成交时店名")
        self.assertEqual(original["logo_png"], logo)

    def test_corrupt_images_rejected_and_large_image_resized(self):
        invalid = Path(self.temp.name) / "broken.png"
        invalid.write_bytes(b"not an image")
        with self.assertRaises(ValidationError):
            import_logo(invalid)
        with self.assertRaises(ValidationError):
            self.store.save_logo(b"not an image")
        image = QImage(1600, 800, QImage.Format_ARGB32)
        image.fill(Qt.black)
        path = Path(self.temp.name) / "large.png"
        image.save(str(path))
        resized = QImage.fromData(import_logo(path))
        self.assertEqual((resized.width(), resized.height()), (512, 256))

    def test_v2_upgrade_keeps_order_and_original_receipt_and_makes_backup(self):
        self.store.close()
        path = Path(self.temp.name) / "old.sqlite3"
        with closing(sqlite3.connect(path)) as old:
            old.executescript((Path(__file__).parent / "fixtures" / "v2.sql").read_text(encoding="utf-8"))
            original = old.execute("SELECT receipt_text FROM orders WHERE id=1").fetchone()[0]
        self.store = Store(path)
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(self.store.order(1)["receipt_text"], original)
        self.assertEqual(self.store.order(1)["final_cents"], 8501)
        self.assertIsNotNone(self.store.open_order(2))
        self.assertEqual(self.store.receipt(1)["style"]["shop_name"], "升级测试店")
        logo = sample_logo()
        self.store.save_logo(logo)
        self.assertEqual(self.store.receipt(1)["logo_png"], logo)
        backups = list(path.parent.glob("old.before-v3-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(self.store.db.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
