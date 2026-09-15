-- Schema and seed data from Sanmu v0.1.0; contains no customer records.
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
CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 99999999),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            );
INSERT INTO "products" VALUES(1,'宫保鸡丁','热菜',2800,1);
INSERT INTO "products" VALUES(2,'番茄炒蛋','热菜',1800,1);
INSERT INTO "products" VALUES(3,'清炒时蔬','热菜',1600,1);
INSERT INTO "products" VALUES(4,'米饭','主食',200,1);
INSERT INTO "products" VALUES(5,'紫菜蛋花汤','汤品',1200,1);
INSERT INTO "products" VALUES(6,'酸梅汤','饮品',600,1);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE UNIQUE INDEX one_open_order_per_table ON orders(table_id) WHERE status='open';
CREATE INDEX orders_closed_at ON orders(closed_at);
DELETE FROM "sqlite_sequence";
COMMIT;
PRAGMA user_version=1;
