from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sanmu.money import ValidationError, discounted_cents, money, to_cents
from sanmu.printing import display_width, format_receipt
from sanmu.storage import Store


class MoneyTests(unittest.TestCase):
    def test_exact_decimal_and_round_half_up(self):
        self.assertEqual(to_cents("0.29"), 29)
        self.assertEqual(discounted_cents(10001, "8.5"), 8501)
        self.assertEqual(discounted_cents(5, "5"), 3)
        self.assertEqual(discounted_cents(900, "0"), 0)
        self.assertEqual(money(123456), "1234.56")

    def test_invalid_money(self):
        for value in ("", "abc", "NaN", "Infinity", "-1", "1.001", "1000000", "1e999999999"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                to_cents(value)

    def test_invalid_discount(self):
        for value in ("", "85", "-1", "NaN", "Infinity", "8.555"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                discounted_cents(1000, value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.product_id = self.store.products()[0]["id"]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def checkout(self, order_id, base="100", discount="8.5"):
        return self.store.checkout(order_id, base, discount, "测试", self.store.order(order_id)["revision"])

    def test_initialization_and_reopen_persists_orders_menu_settings(self):
        self.store.set_table_count("15")
        product_id = self.store.save_product("测试新品", "新品", "19.99")
        order_id = self.store.add_item(15, product_id, "2")
        self.store.save_settings(dict(shop_name="三木测试店", receipt_footer="欢迎", printer_name="", paper_width="58"))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(len(self.store.tables()), 15)
        self.assertEqual(len(self.store.products()), 7)
        self.assertEqual(self.store.open_order(15)["id"], order_id)
        self.assertEqual(self.store.order(order_id)["total_cents"], 3998)
        self.assertEqual(self.store.settings()["shop_name"], "三木测试店")

    def test_add_merge_quantity_and_remove_last_item_frees_table(self):
        order_id = self.store.add_item(1, self.product_id, "2")
        self.store.add_item(1, self.product_id)
        order = self.store.order(order_id)
        self.assertEqual(len(order["items"]), 1)
        self.assertEqual(order["items"][0]["quantity"], 3)
        item_id = order["items"][0]["id"]
        self.store.set_quantity(order_id, item_id, "5")
        self.assertEqual(self.store.order(order_id)["items"][0]["quantity"], 5)
        self.store.remove_item(order_id, item_id)
        self.assertIsNone(self.store.open_order(1))
        self.assertEqual(self.store.order(order_id)["status"], "cancelled")

    def test_menu_change_preserves_existing_order_prices(self):
        order_id = self.store.add_item(1, self.product_id)
        old_item = self.store.order(order_id)["items"][0]
        self.store.save_product("修改后的菜名", "新品", "123.45", product_id=self.product_id)
        self.store.add_item(1, self.product_id)
        items = self.store.order(order_id)["items"]
        self.assertEqual(items[0], old_item)
        self.assertEqual(items[1]["unit_cents"], 12345)
        self.assertEqual(items[1]["product_name"], "修改后的菜名")

    def test_checkout_adjustment_discount_receipt_and_new_order(self):
        order_id = self.store.add_item(2, self.product_id)
        order = self.checkout(order_id, "100.01", "8.5")
        self.assertEqual(order["final_cents"], 8501)
        self.assertEqual(order["base_cents"], 10001)
        self.assertIn("最终实收：￥85.01", order["receipt_text"])
        self.assertIn("折扣：8.5 折", order["receipt_text"])
        self.assertIsNone(self.store.open_order(2))
        self.assertNotEqual(self.store.add_item(2, self.product_id), order_id)
        self.assertEqual(self.store.today_summary(), {"count": 1, "total_cents": 8501})

    def test_paid_receipt_is_immutable_after_menu_and_shop_edits(self):
        order_id = self.store.add_item(1, self.product_id)
        receipt = self.checkout(order_id, "10", "10")["receipt_text"]
        self.store.save_product("新菜名", "新品", "50", product_id=self.product_id)
        self.store.save_settings(dict(shop_name="新店名", receipt_footer="新页脚", printer_name="", paper_width="58"))
        self.assertEqual(self.store.order(order_id)["receipt_text"], receipt)
        self.assertIn("折扣：10 折", receipt)

    def test_double_checkout_and_changes_to_paid_order_are_rejected(self):
        order_id = self.store.add_item(1, self.product_id)
        item_id = self.store.order(order_id)["items"][0]["id"]
        self.checkout(order_id)
        for action in (lambda: self.checkout(order_id), lambda: self.store.cancel_order(order_id),
                       lambda: self.store.set_quantity(order_id, item_id, "2"),
                       lambda: self.store.remove_item(order_id, item_id)):
            with self.assertRaises(ValidationError):
                action()
        self.assertEqual(self.store.today_summary()["count"], 1)

    def test_second_connection_detects_checkout_conflict(self):
        order_id = self.store.add_item(1, self.product_id)
        revision = self.store.order(order_id)["revision"]
        other = Store(self.path)
        try:
            other.add_item(1, self.product_id)
            with self.assertRaisesRegex(ValidationError, "发生变化"):
                self.store.checkout(order_id, "10", "10", "", revision)
            paid = self.checkout(order_id)
            with self.assertRaises(ValidationError):
                other.checkout(order_id, "10", "10", "", paid["revision"])
        finally:
            other.close()

    def test_table_count_protects_open_orders_and_retains_history(self):
        order_id = self.store.add_item(8, self.product_id)
        with self.assertRaises(ValidationError):
            self.store.set_table_count("4")
        self.assertEqual(len(self.store.tables()), 8)
        self.checkout(order_id)
        self.store.set_table_count("4")
        self.assertEqual(len(self.store.tables()), 4)
        self.assertEqual(self.store.order(order_id)["table_name"], "08桌")
        self.store.set_table_count("8")
        self.assertIsNone(self.store.open_order(8))

    def test_transaction_rolls_back_an_oversized_new_order(self):
        product_id = self.store.save_product("大额测试餐品", "测试", "999999.99")
        with self.assertRaises(ValidationError):
            self.store.add_item(3, product_id, "2")
        self.assertIsNone(self.store.open_order(3))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_invalid_checkout_leaves_order_open(self):
        order_id = self.store.add_item(1, self.product_id)
        for amount, discount in (("NaN", "10"), ("10", "85"), ("-1", "10"), ("1.001", "10")):
            with self.assertRaises(ValidationError):
                self.checkout(order_id, amount, discount)
        self.assertEqual(self.store.order(order_id)["status"], "open")

    def test_archived_product_cannot_be_ordered(self):
        product_id = self.store.save_product("停用餐品", "测试", "5", False)
        with self.assertRaises(ValidationError):
            self.store.add_item(1, product_id)
        self.assertNotIn(product_id, {product["id"] for product in self.store.products()})

    def test_print_failure_cannot_undo_settlement(self):
        order_id = self.store.add_item(1, self.product_id)
        self.checkout(order_id)
        self.store.record_print(order_id, "打印机离线")
        order = self.store.order(order_id)
        self.assertEqual(order["status"], "paid")
        self.assertEqual(order["print_status"], "打印失败")
        self.store.record_print(order_id)
        self.assertEqual(self.store.order(order_id)["print_status"], "已提交打印")

    def test_backup_is_consistent_and_self_backup_is_rejected(self):
        self.store.add_item(1, self.product_id, "2")
        destination = Path(self.temp.name) / "backup.sqlite3"
        self.store.backup(destination)
        with closing(sqlite3.connect(destination)) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT quantity FROM order_items").fetchone()[0], 2)
        with self.assertRaises(ValidationError):
            self.store.backup(self.path)

    def test_long_chinese_receipt_wraps_at_selected_width(self):
        product_id = self.store.save_product("超长中文餐品名称" * 4, "测试", "100.05")
        order_id = self.store.add_item(1, product_id)
        order = self.checkout(order_id)
        receipt = format_receipt(order, dict(shop_name="三木餐厅", paper_width="58", receipt_footer="欢迎再来"))
        self.assertTrue(all(display_width(line) <= 32 for line in receipt.splitlines()))
        self.assertIn("最终实收", receipt)

    def test_input_validation_and_date_filter(self):
        for value in ("0", "201", "2.5", "abc"):
            with self.assertRaises(ValidationError):
                self.store.set_table_count(value)
        with self.assertRaises(ValidationError):
            self.store.save_product("换行\n菜", "测试", "1")
        with self.assertRaises(ValidationError):
            self.store.history("2026-99-01")
        self.assertEqual(self.store.history("2000-01-01"), [])


if __name__ == "__main__":
    unittest.main()
