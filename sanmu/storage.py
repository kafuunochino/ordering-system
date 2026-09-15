"""SQLite repository. 每个业务写入操作都是独立事务。"""

from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
import json
import sqlite3

from .money import (MAX_CENTS, ValidationError, clean_text, discount_value,
                    discounted_cents, positive_int, to_cents)

SCHEMA_VERSION = 1


def timestamp() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.close()
            raise ValidationError("数据由较新版本创建，请使用新版三木点餐系统。")
        if version == 0:
            self._initialize()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _initialize(self):
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE dining_tables (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 99999999),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id INTEGER NOT NULL REFERENCES dining_tables(id),
                table_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','paid','cancelled')),
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                revision INTEGER NOT NULL DEFAULT 0,
                subtotal_cents INTEGER,
                base_cents INTEGER,
                discount TEXT,
                final_cents INTEGER,
                note TEXT NOT NULL DEFAULT '',
                receipt_text TEXT,
                print_status TEXT NOT NULL DEFAULT '未打印',
                print_error TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX one_open_order_per_table ON orders(table_id) WHERE status='open';
            CREATE INDEX orders_closed_at ON orders(closed_at);
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                product_name TEXT NOT NULL,
                unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0),
                quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
                UNIQUE(order_id, product_id, product_name, unit_cents)
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        try:
            self.db.executemany("INSERT INTO dining_tables(id,name) VALUES (?,?)",
                                [(number, f"{number:02d}桌") for number in range(1, 9)])
            self.db.executemany("INSERT INTO products(name,category,price_cents) VALUES (?,?,?)", [
                ("宫保鸡丁", "热菜", 2800), ("番茄炒蛋", "热菜", 1800),
                ("清炒时蔬", "热菜", 1600), ("米饭", "主食", 200),
                ("紫菜蛋花汤", "汤品", 1200), ("酸梅汤", "饮品", 600),
            ])
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def settings(self) -> dict:
        defaults = {"shop_name": "三木点餐系统", "receipt_footer": "谢谢惠顾，欢迎再次光临！",
                    "printer_name": "", "paper_width": "80", "auto_print": False}
        for row in self.db.execute("SELECT key,value FROM settings"):
            defaults[row["key"]] = json.loads(row["value"])
        return defaults

    def save_settings(self, values: dict):
        shop = clean_text(values.get("shop_name", ""), "店名", 40)
        footer = clean_text(values.get("receipt_footer", ""), "小票页脚", 80, False)
        printer = clean_text(values.get("printer_name", ""), "打印机名称", 255, False)
        width = str(values.get("paper_width", "80"))
        if width not in ("58", "80"):
            raise ValidationError("纸宽请选择 58 或 80 毫米。")
        auto = bool(values.get("auto_print", False))
        if auto and not printer:
            raise ValidationError("开启结算打印前，请先选择打印机。")
        with self.transaction():
            self.db.executemany("INSERT INTO settings(key,value) VALUES (?,?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", [
                (key, json.dumps(value, ensure_ascii=False)) for key, value in dict(
                    shop_name=shop, receipt_footer=footer, printer_name=printer,
                    paper_width=width, auto_print=auto).items()
            ])

    def tables(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("""
            SELECT t.*, o.id AS order_id, o.opened_at,
                   COALESCE(SUM(i.unit_cents*i.quantity),0) AS total_cents,
                   COALESCE(SUM(i.quantity),0) AS item_count
            FROM dining_tables t
            LEFT JOIN orders o ON o.table_id=t.id AND o.status='open'
            LEFT JOIN order_items i ON i.order_id=o.id
            WHERE t.active=1 GROUP BY t.id ORDER BY t.id
        """)]

    def set_table_count(self, count: str):
        number = positive_int(count, "桌号数量", 200)
        with self.transaction():
            occupied = self.db.execute("SELECT table_name FROM orders WHERE table_id>? AND status='open'",
                                       (number,)).fetchone()
            if occupied:
                raise ValidationError(f"{occupied['table_name']}有未结算订单，请先结算或取消后再减少桌数。")
            self.db.executemany("INSERT OR IGNORE INTO dining_tables(id,name) VALUES (?,?)",
                                [(index, f"{index:02d}桌") for index in range(1, number + 1)])
            self.db.execute("UPDATE dining_tables SET active=(id<=?)", (number,))

    def products(self, include_inactive: bool = False) -> list[dict]:
        sql = "SELECT * FROM products" + ("" if include_inactive else " WHERE active=1")
        return [dict(row) for row in self.db.execute(sql + " ORDER BY category, id")]

    def save_product(self, name: str, category: str, price: str,
                     active: bool = True, product_id: int | None = None):
        name = clean_text(name, "餐品名称", 40)
        category = clean_text(category, "分类", 20)
        price_cents = to_cents(price, "单价")
        try:
            with self.transaction():
                if product_id is None:
                    return self.db.execute("INSERT INTO products(name,category,price_cents,active) "
                                           "VALUES (?,?,?,?)", (name, category, price_cents, int(active))).lastrowid
                cursor = self.db.execute("UPDATE products SET name=?,category=?,price_cents=?,active=? WHERE id=?",
                                         (name, category, price_cents, int(active), product_id))
                if not cursor.rowcount:
                    raise ValidationError("餐品不存在，请刷新后重试。")
                return product_id
        except sqlite3.IntegrityError:
            raise ValidationError("餐品名称已存在，请使用不同名称。") from None

    def open_order(self, table_id: int) -> dict | None:
        row = self.db.execute("SELECT id FROM orders WHERE table_id=? AND status='open'", (table_id,)).fetchone()
        return self.order(row["id"]) if row else None

    def order(self, order_id: int) -> dict:
        row = self.db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise ValidationError("订单不存在。")
        result = dict(row)
        result["items"] = [dict(item) for item in self.db.execute(
            "SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,))]
        result["total_cents"] = sum(item["unit_cents"] * item["quantity"] for item in result["items"])
        return result

    def _require_open(self, order_id: int) -> dict:
        order = self.order(order_id)
        if order["status"] != "open":
            raise ValidationError("订单已结算或取消，不能再次修改。")
        return order

    def add_item(self, table_id: int, product_id: int, quantity: str = "1") -> int:
        quantity_int = positive_int(quantity, "数量")
        with self.transaction():
            table = self.db.execute("SELECT * FROM dining_tables WHERE id=? AND active=1", (table_id,)).fetchone()
            product = self.db.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
            if not table or not product:
                raise ValidationError("桌号或餐品已停用，请刷新后重试。")
            current = self.open_order(table_id)
            if current is None:
                order_id = self.db.execute("INSERT INTO orders(table_id,table_name,opened_at) VALUES (?,?,?)",
                                           (table_id, table["name"], timestamp())).lastrowid
                old_total = 0
            else:
                order_id, old_total = current["id"], current["total_cents"]
            if old_total + product["price_cents"] * quantity_int > MAX_CENTS:
                raise ValidationError("订单金额不能超过 999999.99 元。")
            item = self.db.execute("SELECT * FROM order_items WHERE order_id=? AND product_id=? "
                                   "AND product_name=? AND unit_cents=?",
                                   (order_id, product_id, product["name"], product["price_cents"])).fetchone()
            if item:
                new_quantity = item["quantity"] + quantity_int
                positive_int(str(new_quantity), "单项数量")
                self.db.execute("UPDATE order_items SET quantity=? WHERE id=?", (new_quantity, item["id"]))
            else:
                self.db.execute("INSERT INTO order_items(order_id,product_id,product_name,unit_cents,quantity) "
                                "VALUES (?,?,?,?,?)", (order_id, product_id, product["name"], product["price_cents"], quantity_int))
            self.db.execute("UPDATE orders SET revision=revision+1 WHERE id=?", (order_id,))
            return order_id

    def set_quantity(self, order_id: int, item_id: int, quantity: str):
        number = positive_int(quantity, "数量")
        with self.transaction():
            order = self._require_open(order_id)
            item = next((item for item in order["items"] if item["id"] == item_id), None)
            if item is None:
                raise ValidationError("此餐品不在当前订单内。")
            total = order["total_cents"] + (number - item["quantity"]) * item["unit_cents"]
            if total > MAX_CENTS:
                raise ValidationError("订单金额不能超过 999999.99 元。")
            self.db.execute("UPDATE order_items SET quantity=? WHERE id=?", (number, item_id))
            self.db.execute("UPDATE orders SET revision=revision+1 WHERE id=?", (order_id,))

    def remove_item(self, order_id: int, item_id: int):
        with self.transaction():
            self._require_open(order_id)
            cursor = self.db.execute("DELETE FROM order_items WHERE id=? AND order_id=?", (item_id, order_id))
            if not cursor.rowcount:
                raise ValidationError("此餐品不在当前订单内。")
            self.db.execute("UPDATE orders SET revision=revision+1 WHERE id=?", (order_id,))
            if not self.order(order_id)["items"]:
                self.db.execute("UPDATE orders SET status='cancelled',closed_at=? WHERE id=?", (timestamp(), order_id))

    def cancel_order(self, order_id: int):
        with self.transaction():
            self._require_open(order_id)
            self.db.execute("UPDATE orders SET status='cancelled',closed_at=?,revision=revision+1 WHERE id=?",
                            (timestamp(), order_id))

    def checkout(self, order_id: int, base: str, discount: str, note: str,
                 expected_revision: int) -> dict:
        from .printing import format_receipt

        base_cents = to_cents(base, "结算金额")
        discount_text = format(discount_value(discount).normalize(), "f")
        note = clean_text(note, "结算备注", 200, False)
        final_cents = discounted_cents(base_cents, discount)
        with self.transaction():
            order = self._require_open(order_id)
            if not order["items"]:
                raise ValidationError("空订单不能结算。")
            if order["revision"] != expected_revision:
                raise ValidationError("订单餐品已发生变化，请关闭结算窗口后重新核对。")
            closed = timestamp()
            self.db.execute("""UPDATE orders SET status='paid',closed_at=?,subtotal_cents=?,base_cents=?,
                discount=?,final_cents=?,note=?,revision=revision+1 WHERE id=?""",
                (closed, order["total_cents"], base_cents, discount_text, final_cents, note, order_id))
            paid = self.order(order_id)
            receipt = format_receipt(paid, self.settings())
            self.db.execute("UPDATE orders SET receipt_text=? WHERE id=?", (receipt, order_id))
            paid["receipt_text"] = receipt
            return paid

    def history(self, date: str = "") -> list[dict]:
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise ValidationError("日期格式为 YYYY-MM-DD，例如 2026-09-16。") from None
        sql = "SELECT * FROM orders WHERE status!='open'"
        args = ()
        if date:
            sql += " AND substr(closed_at,1,10)=?"
            args = (date,)
        return [dict(row) for row in self.db.execute(sql + " ORDER BY id DESC", args)]

    def today_summary(self) -> dict:
        row = self.db.execute("SELECT COUNT(*) AS count, COALESCE(SUM(final_cents),0) AS total_cents "
                               "FROM orders WHERE status='paid' AND substr(closed_at,1,10)=?",
                               (datetime.now().strftime("%Y-%m-%d"),)).fetchone()
        return dict(row)

    def record_print(self, order_id: int, error: str = ""):
        with self.transaction():
            self.db.execute("UPDATE orders SET print_status=?,print_error=? WHERE id=? AND status='paid'",
                            ("打印失败" if error else "已提交打印", error[:1000], order_id))

    def backup(self, destination: Path | str):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValidationError("备份位置不能与正在使用的数据库相同。")
        with closing(sqlite3.connect(destination)) as target:
            self.db.backup(target)
