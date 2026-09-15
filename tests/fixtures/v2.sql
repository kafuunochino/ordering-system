BEGIN TRANSACTION;
CREATE TABLE dining_tables (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            );
INSERT INTO "dining_tables" VALUES(1,'01桌',1);
INSERT INTO "dining_tables" VALUES(2,'02桌',1);
INSERT INTO "dining_tables" VALUES(3,'03桌',1);
INSERT INTO "dining_tables" VALUES(4,'04桌',1);
INSERT INTO "dining_tables" VALUES(5,'05桌',1);
INSERT INTO "dining_tables" VALUES(6,'06桌',1);
INSERT INTO "dining_tables" VALUES(7,'07桌',1);
INSERT INTO "dining_tables" VALUES(8,'08桌',1);
CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                product_name TEXT NOT NULL,
                unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0),
                quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
                UNIQUE(order_id, product_id, product_name, unit_cents)
            );
INSERT INTO "order_items" VALUES(1,1,2,'米饭',200,1);
INSERT INTO "order_items" VALUES(2,2,1,'宫保鸡丁',2800,1);
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
INSERT INTO "orders" VALUES(1,1,'01桌','paid','2026-09-16 12:30:00','2026-09-16 12:30:00',2,200,10001,'8.5',8501,'','升级测试店
结 算 单
------------------------------------------------
单号：SM00000001
桌号：01桌
开单：2026-09-16 12:30:00
结算：2026-09-16 12:30:00
------------------------------------------------
米饭
  1 × 2.00 = 2.00
------------------------------------------------
餐品合计：￥2.00
结算金额：￥100.01
金额调整：￥98.01
折扣：8.5 折（10 折为原价）
折扣优惠：￥15.00
最终实收：￥85.01
------------------------------------------------
谢谢惠顾，欢迎再次光临！
','未打印','');
INSERT INTO "orders" VALUES(2,2,'02桌','open','2026-09-16 12:30:00',NULL,1,NULL,NULL,NULL,NULL,'',NULL,'未打印','');
CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 99999999),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1))
            );
INSERT INTO "products" VALUES(1,'宫保鸡丁','热菜',2800,1,0);
INSERT INTO "products" VALUES(2,'米饭','主食',200,1,0);
INSERT INTO "products" VALUES(3,'酸梅汤','饮品',600,1,0);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "settings" VALUES('shop_name','"升级测试店"');
INSERT INTO "settings" VALUES('receipt_footer','"谢谢惠顾，欢迎再次光临！"');
INSERT INTO "settings" VALUES('printer_name','""');
INSERT INTO "settings" VALUES('paper_width','"80"');
INSERT INTO "settings" VALUES('auto_print','false');
CREATE UNIQUE INDEX one_open_order_per_table ON orders(table_id) WHERE status='open';
CREATE INDEX orders_closed_at ON orders(closed_at);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('orders',2);
INSERT INTO "sqlite_sequence" VALUES('order_items',2);
COMMIT;
PRAGMA user_version=2;
