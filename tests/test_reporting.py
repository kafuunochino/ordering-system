"""按真实结算流程生成临时账单，核对跨日、年月和状态组合筛选。"""

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanmu.money import ValidationError
from sanmu.reports import date_bounds, report_period
from sanmu.storage import Store


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "report.sqlite3"
        self.store = Store(self.path)
        self.product = self.store.save_product("统计测试餐品", "测试", "100.01")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def order(self, closed, base="100.01", discount="8.5", status="paid", opened=None, table=1):
        with patch("sanmu.storage.timestamp", return_value=opened or closed):
            order_id = self.store.add_item(table, self.product)
        with patch("sanmu.storage.timestamp", return_value=closed):
            if status == "paid":
                self.store.checkout(order_id, base, discount, "", self.store.order(order_id)["revision"])
            elif status == "cancelled":
                self.store.cancel_order(order_id)
        return order_id

    def test_income_uses_payment_time_adjusted_final_and_excludes_other_statuses(self):
        paid = self.order("2026-09-17 00:00:00", opened="2026-09-16 23:58:00")
        self.order("2026-09-17 12:00:00", status="cancelled")
        self.order("2026-09-17 13:00:00", status="open")
        self.assertEqual(self.store.revenue_report("2026-09-16", "2026-09-16")["count"], 0)
        report = self.store.revenue_report("2026-09-17", "2026-09-17")
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["total_cents"], 8501)
        self.assertEqual(report["discount_cents"], 1500)
        self.assertEqual(report["rows"][0]["period"], "2026-09-17")
        self.store.save_product("新菜名", "测试", "1", product_id=self.product)
        self.store.record_print(paid, "离线")
        self.assertEqual(self.store.revenue_report("2026-09-17", "2026-09-17"), report)

    def test_day_boundaries_include_last_second_but_not_next_midnight(self):
        self.order("2026-09-15 23:59:59", "1", "10")
        first = self.order("2026-09-16 00:00:00", "2", "10")
        last = self.order("2026-09-16 23:59:59", "3", "10")
        self.order("2026-09-17 00:00:00", "4", "10")
        report = self.store.revenue_report("2026-09-16", "2026-09-16")
        self.assertEqual((report["count"], report["total_cents"]), (2, 500))
        self.assertEqual([o["id"] for o in self.store.history("2026-09-16")], [last, first])

    def test_status_dropdown_values_and_inclusive_date_range_combine(self):
        a = self.order("2026-08-31 23:59:59")
        b = self.order("2026-09-01 00:00:00", status="cancelled")
        c = self.order("2026-09-02 23:59:59")
        self.order("2026-09-03 00:00:00", status="cancelled")
        self.order("2026-09-02 12:00:00", status="open")
        query = lambda status: {o["id"] for o in self.store.history("2026-09-01", status, "2026-09-02")}
        self.assertEqual(query("all"), {b, c})
        self.assertEqual(query("paid"), {c})
        self.assertEqual(query("cancelled"), {b})
        self.assertEqual({o["id"] for o in self.store.history(status="paid")}, {a, c})

    def test_month_and_year_grouping_with_leap_day_and_year_boundary(self):
        self.order("2023-12-31 23:59:59", "1", "10")
        self.order("2024-01-01 00:00:00", "2", "10")
        self.order("2024-02-28 12:00:00", "3", "10")
        self.order("2024-02-29 23:59:59", "4", "10")
        self.order("2024-12-31 23:59:59", "5", "10")
        self.order("2025-01-01 00:00:00", "6", "10")
        start, end, group = report_period("month", year=2024, month=2)
        month = self.store.revenue_report(start, end, group)
        self.assertEqual((month["count"], month["total_cents"]), (2, 700))
        start, end, group = report_period("year", year=2024)
        annual = self.store.revenue_report(start, end, group)
        self.assertEqual((annual["count"], annual["total_cents"]), (4, 1400))
        self.assertEqual([r["period"] for r in annual["rows"]], ["2024-12", "2024-02", "2024-01"])
        self.assertEqual(sum(row["total_cents"] for row in annual["rows"]), annual["total_cents"])

    def test_empty_period_and_zero_payment_orders(self):
        empty = self.store.revenue_report("2026-01-01", "2026-01-31")
        self.assertEqual(empty["rows"], [])
        for key in ("count", "subtotal_cents", "base_cents", "discount_cents", "total_cents", "average_cents"):
            self.assertEqual(empty[key], 0)
        self.order("2026-01-12 12:00:00", "100", "0")
        report = self.store.revenue_report("2026-01-01", "2026-01-31")
        self.assertEqual((report["count"], report["total_cents"], report["discount_cents"]), (1, 0, 10000))

    def test_large_totals_and_average_use_integer_cents(self):
        for _ in range(3):
            self.order("2026-09-01 12:00:00", "999999.99", "10")
        report = self.store.revenue_report("2026-09-01", "2026-09-01")
        self.assertEqual(report["total_cents"], 299999997)
        self.assertEqual(report["average_cents"], 99999999)
        self.order("2026-09-02 12:00:00", "0.01", "10")
        self.order("2026-09-02 12:00:00", "0.02", "10")
        self.assertEqual(self.store.revenue_report("2026-09-02", "2026-09-02")["average_cents"], 2)

    def test_invalid_dates_ranges_and_statuses_fail_clearly(self):
        for start, end in (("2026-02-29", "2026-03-01"), ("2026-9-1", "2026-09-02"),
                           ("2026-10-01", "2026-09-01"), ("", "2026-09-01"), ("9999-12-31", "9999-12-31")):
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                self.store.revenue_report(start, end)
        with self.assertRaises(ValidationError):
            self.store.history(status="paid' OR 1=1 --")
        with self.assertRaises(ValidationError):
            self.store.history(end_date="2026-09-01")
        with self.assertRaises(ValidationError):
            self.store.revenue_report("2026-09-01", "2026-09-01", "invalid")
        with self.assertRaises(ValidationError):
            report_period("month", year=2026, month=13)

    def test_period_choices_and_reopen_preserve_report(self):
        today = date.today().isoformat()
        self.assertEqual(report_period("today"), (today, today, "day"))
        self.assertEqual(report_period("day", date(2024, 2, 29)), ("2024-02-29", "2024-02-29", "day"))
        self.assertEqual(report_period("range", date(2023, 12, 31), end=date(2024, 1, 2)),
                         ("2023-12-31", "2024-01-02", "day"))
        self.assertEqual(date_bounds("2024-02-29", "2024-02-29"), ("2024-02-29", "2024-03-01"))
        self.order("2024-02-29 18:00:00")
        before = self.store.revenue_report("2024-01-01", "2024-12-31", "month")
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.revenue_report("2024-01-01", "2024-12-31", "month"), before)


if __name__ == "__main__":
    unittest.main()
