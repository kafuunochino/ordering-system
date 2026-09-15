"""SQLite repository. 每个业务写入操作都是独立事务。"""

from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
import json
import hashlib
import sqlite3

from .money import (MAX_CENTS, ValidationError, clean_text, discount_value,
                    discounted_cents, positive_int, to_cents)
from .reports import date_bounds

SCHEMA_VERSION = 3


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
        elif version == 1:
            self._migrate_v2()
        if self.db.execute("PRAGMA user_version").fetchone()[0] == 2:
            self._migrate_v3()

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
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 99999999),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1))
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
                receipt_style TEXT,
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
            CREATE TABLE branding_assets (id TEXT PRIMARY KEY, png BLOB NOT NULL);
            PRAGMA user_version=3;
        """)
        try:
            self.db.executemany("INSERT INTO dining_tables(id,name) VALUES (?,?)",
                                [(number, f"{number:02d}桌") for number in range(1, 9)])
            self.db.executemany("INSERT INTO products(name,category,price_cents) VALUES (?,?,?)", [
                ("宫保鸡丁", "热菜", 2800), ("米饭", "主食", 200), ("酸梅汤", "饮品", 600),
            ])
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _migrate_v2(self):
        """保留全部旧菜单和订单；迁移前生成可恢复的数据库备份。"""
        backup_path = self.path.with_name(f"{self.path.stem}.before-v2-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
        self.backup(backup_path)
        self.db.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.transaction():
                self.db.execute("""CREATE TABLE products_v2 (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
                    price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 99999999),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)))""")
                self.db.execute("INSERT INTO products_v2(id,name,category,price_cents,active) "
                                "SELECT id,name,category,price_cents,active FROM products")
                self.db.execute("DROP TABLE products")
                self.db.execute("ALTER TABLE products_v2 RENAME TO products")
                if self.db.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValidationError("数据关联校验失败，升级已回滚，请保留备份并检查数据库。")
                self.db.execute("PRAGMA user_version=2")
        finally:
            self.db.execute("PRAGMA foreign_keys=ON")

    def _migrate_v3(self):
        backup_path = self.path.with_name(f"{self.path.stem}.before-v3-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
        self.backup(backup_path)
        with self.transaction():
            self.db.execute("ALTER TABLE orders ADD COLUMN receipt_style TEXT")
            self.db.execute("CREATE TABLE branding_assets (id TEXT PRIMARY KEY, png BLOB NOT NULL)")
            self.db.execute("PRAGMA user_version=3")

    def close(self):
        self.db.close()

    def settings(self) -> dict:
        defaults = {"shop_name": "三木点餐系统", "receipt_footer": "谢谢惠顾，欢迎再次光临！",
                    "printer_name": "", "paper_width": "80", "auto_print": False, "theme": "light", "logo_id": ""}
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

    def set_theme(self, theme: str):
        if theme not in ("light", "dark", "system"):
            raise ValidationError("请选择浅色、深色或跟随系统。")
        with self.transaction():
            self.db.execute("INSERT INTO settings(key,value) VALUES ('theme',?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(theme),))

    def save_logo(self, png: bytes):
        from .branding import logo_image
        if not isinstance(png, bytes) or len(png) > 2 * 1024 * 1024:
            raise ValidationError("Logo 图片数据无效或过大。")
        image = logo_image(png)
        if max(image.width(), image.height()) > 512:
            raise ValidationError("请通过上传功能导入 Logo。")
        asset_id = hashlib.sha256(png).hexdigest()
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO branding_assets(id,png) VALUES (?,?)", (asset_id, png))
            self.db.execute("INSERT INTO settings(key,value) VALUES ('logo_id',?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(asset_id),))
        return asset_id

    def remove_logo(self):
        # 历史小票仍引用旧资源，清除当前设置时不删除图片。
        with self.transaction():
            self.db.execute("INSERT INTO settings(key,value) VALUES ('logo_id','\"\"') "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value")

    def logo(self, asset_id: str | None = None) -> bytes:
        asset_id = self.settings()["logo_id"] if asset_id is None else asset_id
        if not asset_id:
            return b""
        row = self.db.execute("SELECT png FROM branding_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise ValidationError("Logo 资源不存在，请检查数据库备份。")
        return bytes(row["png"])

    def receipt(self, order_id: int) -> dict:
        """返回不依赖数据库连接的打印数据，预览和后台打印共用。"""
        from .receipts import legacy_receipt_style
        order = self.order(order_id)
        if order["status"] != "paid":
            raise ValidationError("只有已结算订单可以打印结算小票。")
        style = json.loads(order["receipt_style"]) if order["receipt_style"] else legacy_receipt_style(
            order["receipt_text"], self.settings())
        return dict(order=order, style=style, logo_png=self.logo(style.get("logo_id", "")))

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
            for index in range(1, number + 1):
                if self.db.execute("SELECT id FROM dining_tables WHERE id=?", (index,)).fetchone():
                    continue
                name, suffix = f"{index:02d}桌", 1
                while self.db.execute("SELECT id FROM dining_tables WHERE name=?", (name,)).fetchone():
                    name, suffix = f"桌台{index}-{suffix}", suffix + 1
                self.db.execute("INSERT INTO dining_tables(id,name) VALUES (?,?)", (index, name))
            self.db.execute("UPDATE dining_tables SET active=(id<=?)", (number,))

    def rename_table(self, table_id: int, name: str):
        name = clean_text(name, "桌台名称", 20)
        try:
            with self.transaction():
                row = self.db.execute("SELECT name FROM dining_tables WHERE id=? AND active=1", (table_id,)).fetchone()
                if not row:
                    raise ValidationError("桌台不存在或已停用。")
                if row["name"] == name:
                    return
                self.db.execute("UPDATE dining_tables SET name=? WHERE id=?", (name, table_id))
                self.db.execute("UPDATE orders SET table_name=?,revision=revision+1 WHERE table_id=? AND status='open'",
                                (name, table_id))
        except sqlite3.IntegrityError:
            raise ValidationError("这个桌台名称已存在，请换一个名称。") from None

    def products(self, include_inactive: bool = False) -> list[dict]:
        sql = "SELECT * FROM products WHERE deleted=0" + ("" if include_inactive else " AND active=1")
        return [dict(row) for row in self.db.execute(sql + " ORDER BY category, id")]

    def categories(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT DISTINCT category FROM products WHERE deleted=0 ORDER BY category")]

    def delete_product(self, product_id: int):
        with self.transaction():
            cursor = self.db.execute("UPDATE products SET deleted=1,active=0 WHERE id=? AND deleted=0", (product_id,))
            if not cursor.rowcount:
                raise ValidationError("餐品不存在或已删除。")

    def restore_product(self, product_id: int, active: bool = True):
        with self.transaction():
            self.db.execute("UPDATE products SET deleted=0,active=? WHERE id=? AND deleted=1", (int(active), product_id))

    def save_product(self, name: str, category: str, price: str,
                     active: bool = True, product_id: int | None = None):
        name = clean_text(name, "餐品名称", 40)
        category = clean_text(category, "分类", 20, False) or "未分类"
        price_cents = to_cents(price, "单价")
        try:
            with self.transaction():
                if product_id is None:
                    return self.db.execute("INSERT INTO products(name,category,price_cents,active) "
                                           "VALUES (?,?,?,?)", (name, category, price_cents, int(active))).lastrowid
                cursor = self.db.execute("UPDATE products SET name=?,category=?,price_cents=?,active=? WHERE id=? AND deleted=0",
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
            product = self.db.execute("SELECT * FROM products WHERE id=? AND active=1 AND deleted=0", (product_id,)).fetchone()
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
        from .receipts import format_receipt, receipt_style

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
            style = receipt_style(self.settings())
            receipt = format_receipt(paid, style)
            style_json = json.dumps(style, ensure_ascii=False)
            self.db.execute("UPDATE orders SET receipt_text=?,receipt_style=? WHERE id=?", (receipt, style_json, order_id))
            paid["receipt_text"] = receipt
            paid["receipt_style"] = style_json
            return paid

    def history(self, date: str = "", status: str = "all", end_date: str = "") -> list[dict]:
        if status not in ("all", "paid", "cancelled"):
            raise ValidationError("请选择全部状态、已结算或已取消。")
        sql = "SELECT * FROM orders WHERE status!='open'"
        args = []
        if status != "all":
            sql += " AND status=?"
            args.append(status)
        if end_date and not date:
            raise ValidationError("请选择开始日期。")
        if date:
            start, end = date_bounds(date, end_date or date)
            sql += " AND closed_at>=? AND closed_at<?"
            args.extend((start, end))
        return [dict(row) for row in self.db.execute(sql + " ORDER BY closed_at DESC, id DESC", args)]

    def revenue_report(self, start_date: str, end_date: str, group_by: str = "day") -> dict:
        """一次聚合读取，汇总与明细使用同一快照；金额全程为整数分。"""
        start, end = date_bounds(start_date, end_date)
        if group_by not in ("day", "month"):
            raise ValidationError("请选择按日或按月汇总。")
        length = 10 if group_by == "day" else 7
        rows = [dict(row) for row in self.db.execute("""
            SELECT substr(closed_at,1,?) AS period, COUNT(*) AS count,
                   SUM(subtotal_cents) AS subtotal_cents, SUM(base_cents) AS base_cents,
                   SUM(base_cents-final_cents) AS discount_cents, SUM(final_cents) AS total_cents
            FROM orders WHERE status='paid' AND closed_at>=? AND closed_at<?
            GROUP BY period ORDER BY period DESC
        """, (length, start, end))]
        totals = {key: sum(row[key] for row in rows) for key in (
            "count", "subtotal_cents", "base_cents", "discount_cents", "total_cents")}
        count = totals["count"]
        totals["average_cents"] = (totals["total_cents"] + count // 2) // count if count else 0
        return dict(start_date=start_date, end_date=end_date, group_by=group_by, rows=rows, **totals)

    def today_summary(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        report = self.revenue_report(today, today)
        return {key: report[key] for key in ("count", "total_cents")}

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
