"""Qt 离屏集成检查，不触碰用户桌面、店铺数据或打印设备。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sanmu.storage import Store
from sanmu.ui import App, ReceiptDialog


class DesktopSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setStyle("Fusion")
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.unexpected_dialog = patch("sanmu.ui.notify", side_effect=AssertionError("Unexpected notification"))
        self.unexpected_dialog.start()
        self.app = App(Store(Path(self.temporary.name) / "ui.sqlite3"))
        self.app.show()
        QTest.qWait(20)

    def tearDown(self):
        self.app.close()
        self.qt.processEvents()
        self.unexpected_dialog.stop()
        self.temporary.cleanup()

    def test_complete_order_checkout_and_receipt_flow(self):
        app = self.app
        QTest.mouseClick(app.product_grid.cards[0], Qt.LeftButton)
        self.assertEqual(len(app.current_order["items"]), 1)
        item = app.current_order["items"][0]
        app.change_quantity(item["id"], 2)
        self.assertEqual(app.current_order["items"][0]["quantity"], 2)
        app.open_checkout()
        self.qt.processEvents()
        dialog = app.checkout_dialog
        dialog.base.setText("100.01")
        dialog.discount.setText("8.5")
        self.assertEqual(dialog.final.text(), "￥85.01")
        dialog.discount.setText("invalid")
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.discount.setText("8.5")
        with patch("sanmu.ui.confirm", return_value=True):
            dialog.submit()
        self.assertIsNone(app.current_order)
        paid = app.store.history()[0]
        self.assertEqual(paid["final_cents"], 8501)
        receipt = ReceiptDialog(app, app.store.order(paid["id"]))
        self.assertIn("85.01", receipt.view.toPlainText())
        receipt.close()

    def test_deletion_has_no_confirmation_and_menu_delete_can_be_undone(self):
        app = self.app
        product = app.store.products()[0]
        app.add_item(product["id"])
        item_id = app.current_order["items"][0]["id"]
        with patch("sanmu.ui.confirm", side_effect=AssertionError("Deletion must not confirm")):
            app.remove_item(item_id)
            self.assertIsNone(app.current_order)
            app.products_page.view.selectRow(0)
            app.products_page.select()
            app.products_page.delete()
        self.assertEqual(len(app.store.products()), 2)
        app.undo_delete()
        self.assertEqual(len(app.store.products()), 3)

    def test_theme_resize_and_unsaved_input_are_preserved(self):
        app = self.app
        app.add_item(app.store.products()[0]["id"])
        order_id = app.current_order["id"]
        app.products_page.name.setText("未保存的餐品")
        for theme in (1, 0):
            app.theme_combo.setCurrentIndex(theme)
            self.assertEqual(app.theme, "dark" if theme else "light")
            for width, height in ((1440, 900), (1100, 700)):
                app.resize(width, height)
                QTest.qWait(25)
                self.assertLessEqual(app.width(), width)
                bottom = app.checkout_button.mapTo(app, QPoint(0, app.checkout_button.height()))
                self.assertTrue(app.rect().contains(bottom), (app.size(), bottom))
            self.assertEqual(app.current_order["id"], order_id)
            self.assertEqual(app.products_page.name.text(), "未保存的餐品")
        self.assertEqual(app.store.settings()["theme"], "light")

    def test_category_creation_table_rename_and_history_filter(self):
        app = self.app
        products = app.products_page
        products.clear()
        products.name.setText("新餐品")
        products.category.setEditText("新分类")
        products.price.setText("12.34")
        products.save()
        self.assertEqual(len(app.store.products()), 4)
        self.assertIn("新分类", [products.category.itemText(i) for i in range(products.category.count())])
        tables = app.tables_page
        tables.select_table(1)
        tables.name.setText("靠窗 A1")
        tables.rename()
        self.assertEqual(app.cart_title.text(), "靠窗 A1")
        self.assertEqual(app.table_grid.cards[0].findChildren(type(app.cart_title))[0].text(), "靠窗 A1")
        app.history_page.date.setText("unfinished date")
        app.refresh()
        for page in range(5):
            app.navigate(page)
            self.qt.processEvents()


if __name__ == "__main__":
    unittest.main()
