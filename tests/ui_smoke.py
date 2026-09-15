"""Qt 离屏集成检查，不触碰用户桌面、店铺数据或打印设备。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateEdit, QAbstractItemView

from sanmu.storage import Store
from sanmu.ui import App, ReceiptDialog
from sanmu.receipt_render import ReceiptLayout, font
from sanmu.printing import print_receipt
from tests.receipt_cases import sample_logo, sample_receipt
from PySide6.QtGui import QFontMetricsF


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
        self.assertIn("85.01", receipt.receipt)
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
        app.history_page.date.setDate(QDate(2024, 2, 29))
        app.refresh()
        for page in range(app.stack.count()):
            app.navigate(page)
            self.qt.processEvents()

    def make_report_order(self, timestamp, status="paid", base="100.01", discount="8.5"):
        with patch("sanmu.storage.timestamp", return_value=timestamp):
            order_id = self.app.store.add_item(1, self.app.store.products()[0]["id"])
            if status == "paid":
                self.app.store.checkout(order_id, base, discount, "", self.app.store.order(order_id)["revision"])
            else:
                self.app.store.cancel_order(order_id)
        return order_id

    def test_history_status_calendar_and_combined_range(self):
        self.make_report_order("2024-02-28 12:00:00")
        self.make_report_order("2024-02-29 23:59:59", "cancelled")
        self.make_report_order("2024-03-01 00:00:00")
        page = self.app.history_page
        self.app.navigate(3)
        self.assertIsInstance(page.date, QDateEdit)
        self.assertTrue(page.date.calendarPopup())
        page.set_filters("2024-02-28", "2024-02-29")
        self.assertEqual(page.view.rowCount(), 2)
        page.status_combo.setCurrentIndex(page.status_combo.findData("paid"))
        self.assertEqual(page.view.rowCount(), 1)
        self.assertEqual(page.view.item(0, 3).text(), "已结算")
        page.status_combo.setCurrentIndex(page.status_combo.findData("cancelled"))
        self.assertEqual(page.view.item(0, 3).text(), "已取消")
        page.date_mode.setCurrentIndex(page.date_mode.findData("day"))
        self.assertEqual(page.view.rowCount(), 0)
        page.date.setDate(QDate(2024, 2, 29))
        self.assertEqual(page.view.rowCount(), 1)
        page.show_all()
        self.assertEqual(page.status_combo.currentData(), "all")
        self.assertEqual(page.view.rowCount(), 3)
        self.assertFalse(page.date.isVisible())

    def test_revenue_modes_totals_drilldown_and_new_checkout_refresh(self):
        self.make_report_order("2024-02-28 12:00:00")
        self.make_report_order("2024-02-29 23:59:59", base="10", discount="10")
        self.make_report_order("2024-03-01 00:00:00", "cancelled")
        page = self.app.revenue_page
        self.app.navigate(4)
        page.mode.setCurrentIndex(page.mode.findData("month"))
        page.year.setCurrentText("2024 年")
        page.month.setCurrentIndex(1)
        self.assertEqual(page.metrics["total_cents"].text(), "￥95.01")
        self.assertEqual(page.metrics["count"].text(), "2 单")
        self.assertEqual(page.view.rowCount(), 2)
        page.mode.setCurrentIndex(page.mode.findData("year"))
        self.assertEqual(page.view.rowCount(), 1)
        page.view.selectRow(0)
        page.show_orders()
        history = self.app.history_page
        self.assertIs(self.app.stack.currentWidget(), history)
        self.assertEqual(history.view.rowCount(), 2)
        self.assertEqual(history.end_date.date(), QDate(2024, 2, 29))
        self.assertEqual(history.status_combo.currentData(), "paid")
        self.app.navigate(4)
        page.mode.setCurrentIndex(page.mode.findData("range"))
        page.date.setDate(QDate(2024, 2, 28))
        page.end_date.setDate(QDate(2024, 2, 29))
        self.assertEqual(page.metrics["total_cents"].text(), "￥95.01")
        self.make_report_order("2024-02-29 23:59:59", base="5", discount="10")
        self.app.refresh()
        self.assertEqual(page.metrics["total_cents"].text(), "￥100.01")
        page.mode.setCurrentIndex(page.mode.findData("day"))
        self.assertEqual(page.metrics["total_cents"].text(), "￥85.01")
        page.mode.setCurrentIndex(page.mode.findData("today"))
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self.assertEqual(page.report["start_date"], today)
        self.assertFalse(page.date.isEnabled())

    def test_calendar_popup_selection_themes_and_report_minimum_size(self):
        page = self.app.history_page
        for theme in (0, 1):
            self.app.theme_combo.setCurrentIndex(theme)
            self.app.navigate(3)
            page.set_filters("2024-02-28", "2024-02-28")
            self.app.resize(1100, 700)
            QTest.qWait(20)
            QTest.mouseClick(page.date, Qt.LeftButton, pos=QPoint(page.date.width()-16, page.date.height()//2))
            QTest.qWait(20)
            calendar = page.date.calendarWidget()
            self.assertTrue(calendar.isVisible())
            calendar_view = calendar.findChild(QAbstractItemView)
            QTest.keyClick(calendar_view, Qt.Key_Right)
            QTest.keyClick(calendar_view, Qt.Key_Return)
            QTest.qWait(20)
            self.assertEqual(page.date.date(), QDate(2024, 2, 29))
            self.assertFalse(calendar.isVisible())
            page.date_mode.setCurrentIndex(page.date_mode.findData("range"))
            for widget in (page.end_date, page.status_combo):
                corner = widget.mapTo(self.app, QPoint(widget.width()-1, widget.height()-1))
                self.assertTrue(self.app.rect().contains(corner))
            self.app.navigate(4)
            report = self.app.revenue_page
            report.mode.setCurrentIndex(report.mode.findData("range"))
            QTest.qWait(20)
            self.assertLessEqual(self.app.width(), 1100)
            for widget in (report.end_date, report.query_button, report.details_button):
                corner = widget.mapTo(self.app, QPoint(widget.width()-1, widget.height()-1))
                self.assertTrue(self.app.rect().contains(corner))

    def test_logo_upload_brand_name_theme_preview_and_removal(self):
        settings = self.app.settings_page
        filename = Path(self.temporary.name) / "brand.png"
        filename.write_bytes(sample_logo())
        self.app.navigate(5)
        settings.shop.setText("自定义小店")
        settings.save()
        with patch("sanmu.ui.open_logo_file", return_value=str(filename)):
            settings.upload_logo()
        self.assertTrue(self.app.store.logo())
        self.assertIsNotNone(self.app.brand_logo.image)
        self.assertEqual(self.app.brand_name.text(), "自定义小店")
        saved = self.app.store.logo()
        filename.unlink()
        for theme in (0, 1):
            self.app.theme_combo.setCurrentIndex(theme)
            settings.preview_receipt()
            self.qt.processEvents()
            dialog = settings.preview_dialog
            self.assertEqual(dialog.view.receipt_layout.payload["logo_png"], saved)
            self.assertEqual(dialog.view.receipt_layout.payload["style"]["shop_name"], "自定义小店")
            self.assertNotIn("折扣", dialog.receipt)
            self.assertGreater(dialog.view.image.height(), 0)
            dialog.close()
        with patch("sanmu.ui.open_logo_file", return_value=""):
            settings.upload_logo()
        self.assertEqual(self.app.store.logo(), saved)
        settings.remove_logo()
        self.assertEqual(self.app.store.logo(), b"")
        self.assertIsNone(self.app.brand_logo.image)

    def test_receipt_pixels_logo_center_and_long_item_columns_fit_both_widths(self):
        for width in ("58", "80"):
            payload = sample_receipt(width)
            payload["order"]["items"].append(dict(product_name="超长中英文餐品名称ABC" * 3, quantity=1, unit_cents=99999999))
            layout = ReceiptLayout(payload)
            pages = layout.pages()
            logo = next(command for command in pages[0].commands if command[0] == "image")
            self.assertAlmostEqual(logo[1].center().x(), layout.width / 2)
            self.assertAlmostEqual(logo[1].width() / logo[1].height(), 160 / 120)
            image = layout.render(pages[0])
            dark_x = [x for x in range(image.width()) if any(image.pixelColor(x, y).red() < 80
                       for y in range(int(logo[1].top()), int(logo[1].bottom())))]
            self.assertTrue(dark_x)
            self.assertLessEqual(abs((min(dark_x)+max(dark_x))/2 - layout.width/2), 2)
            for page in pages:
                for kind, rect, value, size, align, bold in page.commands:
                    self.assertGreaterEqual(rect.left(), 0)
                    self.assertLessEqual(rect.right(), layout.width)
                    self.assertLessEqual(rect.bottom(), page.height)
                    if kind == "text":
                        self.assertLessEqual(QFontMetricsF(font(size, bold)).horizontalAdvance(value), rect.width()+1, value)
                        self.assertNotIn("（", value)
                        self.assertNotIn("(", value)
            short_pages = layout.pages(420)
            self.assertGreater(len(short_pages), 1)
            before = [c[2] for page in pages for c in page.commands if c[0] == "text"]
            after = [c[2] for page in short_pages for c in page.commands if c[0] == "text"]
            self.assertEqual(before, after)

    def fake_gdi(self, fail_bitmap=False):
        api = MagicMock()
        api.CreateDCW.return_value = 123
        api.GetDeviceCaps.side_effect = lambda dc, cap: {8: 640, 10: 420, 88: 203, 90: 203, 110: 670, 112: 15}.get(cap, 0)
        api.StartDocW.return_value = 77
        for name in ("StartPage", "EndPage", "EndDoc", "AbortDoc", "DeleteDC"):
            getattr(api, name).return_value = 1
        api.StretchDIBits.return_value = 0 if fail_bitmap else 1
        return api

    def test_windows_print_submits_all_bitmap_pages_with_correct_orientation(self):
        api = self.fake_gdi()
        with patch("sanmu.printing.ctypes.WinDLL", return_value=api):
            job = print_receipt("测试打印机", sample_receipt())
        self.assertEqual(job, 77)
        self.assertGreater(api.StartPage.call_count, 1)
        self.assertEqual(api.StartPage.call_count, api.EndPage.call_count)
        self.assertEqual(api.StretchDIBits.call_count, api.EndPage.call_count)
        for call in api.StretchDIBits.call_args_list:
            args = call.args
            header = args[10]._obj
            self.assertLess(header.biHeight, 0)
            self.assertEqual(header.biBitCount, 32)
            self.assertLessEqual(args[1]+args[3], 640)
            self.assertLessEqual(args[4], 420)
            self.assertEqual(len(bytes(args[9]))-1, header.biSizeImage)
        api.EndDoc.assert_called_once()
        api.DeleteDC.assert_called_once()
        api.AbortDoc.assert_not_called()

    def test_windows_print_failure_aborts_job_and_releases_device(self):
        api = self.fake_gdi(True)
        with patch("sanmu.printing.ctypes.WinDLL", return_value=api), self.assertRaises(OSError):
            print_receipt("测试打印机", sample_receipt())
        api.AbortDoc.assert_called_once()
        api.EndDoc.assert_not_called()
        api.DeleteDC.assert_called_once()


if __name__ == "__main__":
    unittest.main()
