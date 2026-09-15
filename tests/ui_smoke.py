"""本机 Tk 界面集成检查，不连接打印机，不使用实际店铺数据。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanmu.storage import Store
from sanmu.ui import App, ReceiptDialog


class DesktopSmoke(unittest.TestCase):
    def test_complete_desktop_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = App(Store(Path(temporary) / "ui.sqlite3"))
            errors = []
            app.report_callback_exception = lambda *args: errors.append(args)
            try:
                app.update()
                self.assertGreater(app.winfo_height(), app.notebook.winfo_y() + app.notebook.winfo_height())
                for geometry in ("1340x850", "1100x700"):
                    app.geometry(geometry)
                    app.update()
                    self.assertTrue(app.checkout_button.winfo_ismapped())
                    self.assertLess(app.checkout_button.winfo_rooty() + app.checkout_button.winfo_height(),
                                    app.winfo_rooty() + app.winfo_height())
                app.menu.selection_set(app.menu.get_children()[0])
                app.add_item()
                app.update()
                self.assertEqual(len(app.current_order["items"]), 1)
                app.cart.selection_set(app.cart.get_children()[0])
                app.change_quantity(1)
                self.assertEqual(app.current_order["items"][0]["quantity"], 2)
                app.open_checkout()
                app.update()
                dialog = next(child for child in app.winfo_children() if child.winfo_class() == "Toplevel")
                dialog.base.set("100.01")
                dialog.discount.set("8.5")
                self.assertEqual(dialog.final.get(), "￥85.01")
                dialog.discount.set("invalid")
                self.assertEqual(str(dialog.confirm.cget("state")), "disabled")
                dialog.discount.set("8.5")
                with patch("sanmu.ui.messagebox.askyesno", return_value=True):
                    dialog.submit()
                app.update()
                self.assertIsNone(app.current_order)
                paid = app.store.history()[0]
                self.assertEqual(paid["final_cents"], 8501)
                receipt = ReceiptDialog(app, app.store.order(paid["id"]))
                app.update()
                receipt.destroy()
                for page in (app.products_page, app.tables_page, app.history_page, app.settings_page):
                    app.notebook.select(page)
                    app.update()
                app.products_page.clear()
                app.products_page.name.set("界面测试餐品")
                app.products_page.price.set("12.34")
                app.products_page.save()
                app.update()
                self.assertEqual(len(app.store.products()), 7)
                app.tables_page.count.set("12")
                app.tables_page.save()
                self.assertEqual(len(app.store.tables()), 12)
                app.history_page.date.set("unfinished date")
                app.refresh()  # An unsubmitted date must not break other pages.
                self.assertFalse(errors, errors)
            finally:
                app.close_app()


if __name__ == "__main__":
    unittest.main()
