"""三木点餐系统的 Windows / Tkinter 桌面界面。"""

from datetime import datetime
from pathlib import Path
import logging
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import APP_NAME, __version__
from .money import ValidationError, discounted_cents, money, to_cents
from .printing import available_printers, print_receipt
from .storage import Store

GREEN = "#235B48"
PALE = "#EAF3ED"
INK = "#233C32"
MUTED = "#6B7B73"
BACKGROUND = "#F4F6F2"


def label(parent, text="", style="TLabel", **kwargs):
    return ttk.Label(parent, text=text, style=style, **kwargs)


def button(parent, text, command, primary=False, **kwargs):
    return ttk.Button(parent, text=text, command=command,
                      style="Primary.TButton" if primary else "TButton", **kwargs)


def tree(parent, columns, height=12):
    """columns = [(key, title, width, anchor), ...]."""
    frame = ttk.Frame(parent)
    view = ttk.Treeview(frame, columns=[col[0] for col in columns], show="headings",
                        selectmode="browse", height=height)
    for key, title, width, anchor in columns:
        view.heading(key, text=title)
        view.column(key, width=width, minwidth=40, anchor=anchor, stretch=True)
    scrollbar = ttk.Scrollbar(frame, command=view.yview)
    view.configure(yscrollcommand=scrollbar.set)
    view.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    view.tag_configure("muted", foreground=MUTED)
    return frame, view


def refill(view, rows):
    selected = view.selection()
    view.delete(*view.get_children())
    for iid, values, tags in rows:
        view.insert("", "end", iid=str(iid), values=values, tags=tags)
    if selected and view.exists(selected[0]):
        view.selection_set(selected[0])


class App(tk.Tk):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.print_queue = queue.Queue()
        self.printing_ids = set()
        self.table_id = 1
        self.current_order = None
        self.title(f"{APP_NAME}  ·  v{__version__}")
        width, height = min(1340, self.winfo_screenwidth() - 60), min(850, self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.minsize(1100, 650)
        self.configure(background=BACKGROUND)
        self._style()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.report_callback_exception = self.report_error
        self._build()
        self.refresh()
        self.after(150, self._poll_print)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=INK)
        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabel", background=BACKGROUND, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"), foreground=GREEN)
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("Amount.TLabel", font=("Microsoft YaHei UI", 28, "bold"), foreground=GREEN)
        style.configure("Error.TLabel", foreground="#B33C32")
        style.configure("TButton", padding=(12, 9), background="white", borderwidth=1)
        style.map("TButton", background=[("active", PALE)])
        style.configure("Primary.TButton", background=GREEN, foreground="white", borderwidth=0)
        style.map("Primary.TButton", background=[("disabled", "#C9D3CB"), ("active", "#33725B")],
                  foreground=[("disabled", "#758179"), ("!disabled", "white")])
        style.configure("TNotebook", background=BACKGROUND, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(24, 12), background=BACKGROUND)
        style.map("TNotebook.Tab", background=[("selected", GREEN)], foreground=[("selected", "white")],
                  padding=[("selected", (24, 12)), ("!selected", (24, 12))])
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=39, borderwidth=0)
        style.configure("Treeview.Heading", background=PALE, font=("Microsoft YaHei UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", GREEN)], foreground=[("selected", "white")])
        style.configure("TEntry", padding=7)
        style.configure("TCombobox", padding=6)
        style.configure("TLabelframe", background=BACKGROUND)
        style.configure("TLabelframe.Label", background=BACKGROUND)

    def _build(self):
        header = ttk.Frame(self, padding=(24, 20, 24, 16))
        header.pack(fill="x")
        label(header, "三木", "Title.TLabel").pack(side="left")
        label(header, "点餐系统  /  店内收银", "Muted.TLabel", padding=(20, 0)).pack(side="left")
        self.summary = tk.StringVar()
        label(header, textvariable=self.summary).pack(side="right")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=24)
        self.order_page = ttk.Frame(self.notebook, padding=(0, 20, 0, 0))
        self.products_page = ProductsPage(self)
        self.tables_page = TablesPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        for page, title in [(self.order_page, "点餐收银"), (self.products_page, "餐品管理"),
                            (self.tables_page, "桌号设置"), (self.history_page, "历史订单"),
                            (self.settings_page, "系统设置")]:
            self.notebook.add(page, text=title)
        self._build_order()
        self.status = tk.StringVar(value="准备就绪 · 点餐操作自动保存")
        footer = ttk.Frame(self, padding=(24, 12))
        footer.pack(side="bottom", fill="x", before=self.notebook)
        label(footer, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        label(footer, f"本地离线使用  ·  v{__version__}", "Muted.TLabel").pack(side="right")
        self.bind("<F5>", lambda event: self.refresh())

    def _build_order(self):
        page = self.order_page
        page.columnconfigure(0, weight=2, minsize=225)
        page.columnconfigure(1, weight=3, minsize=330)
        page.columnconfigure(2, weight=3, minsize=360)
        page.rowconfigure(0, weight=1)
        left = ttk.Frame(page)
        middle = ttk.Frame(page, padding=(18, 0))
        right = ttk.Frame(page)
        left.grid(row=0, column=0, sticky="nsew")
        middle.grid(row=0, column=1, sticky="nsew")
        right.grid(row=0, column=2, sticky="nsew")
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        label(left, "选择桌号", "Heading.TLabel").pack(anchor="w")
        self.table_summary = tk.StringVar()
        label(left, textvariable=self.table_summary, style="Muted.TLabel", padding=(0, 5, 0, 12)).pack(anchor="w")
        wrapper = ttk.Frame(left)
        wrapper.pack(fill="both", expand=True)
        self.table_canvas = tk.Canvas(wrapper, background=BACKGROUND, highlightthickness=0, width=220)
        scroll = ttk.Scrollbar(wrapper, command=self.table_canvas.yview)
        self.table_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table_canvas.pack(fill="both", expand=True)
        self.table_grid = ttk.Frame(self.table_canvas)
        self.table_window = self.table_canvas.create_window((0, 0), window=self.table_grid, anchor="nw")
        self.table_grid.bind("<Configure>", lambda event: self.table_canvas.configure(scrollregion=self.table_canvas.bbox("all")))
        self.table_canvas.bind("<Configure>", lambda event: self.table_canvas.itemconfigure(self.table_window, width=event.width))
        self.table_grid.columnconfigure((0, 1), weight=1)

        label(middle, "选择餐品", "Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        filters = ttk.Frame(middle)
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.search = tk.StringVar()
        self.category = tk.StringVar(value="全部分类")
        ttk.Entry(filters, textvariable=self.search, width=14).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.category_combo = ttk.Combobox(filters, textvariable=self.category, state="readonly", width=9)
        self.category_combo.pack(side="right")
        self.search.trace_add("write", lambda *args: self._refresh_menu())
        self.category.trace_add("write", lambda *args: self._refresh_menu())
        label(middle, "输入菜名搜索 · 双击餐品即可添加", "Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8))
        frame, self.menu = tree(middle, [("name", "餐品", 155, "w"), ("category", "分类", 65, "w"),
                                         ("price", "单价 / 元", 90, "e")])
        frame.grid(row=3, column=0, sticky="nsew")
        self.menu.bind("<Double-1>", lambda event: self.add_item())
        self.menu.bind("<Return>", lambda event: self.add_item())
        actions = ttk.Frame(middle, padding=(0, 12, 0, 0))
        actions.grid(row=4, column=0, sticky="ew")
        label(actions, "数量").pack(side="left")
        self.add_quantity = tk.StringVar(value="1")
        ttk.Spinbox(actions, from_=1, to=999, textvariable=self.add_quantity, width=5).pack(side="left", padx=8)
        button(actions, "加入本桌 ＋", self.add_item, True).pack(side="right")

        self.cart_title = tk.StringVar()
        label(right, textvariable=self.cart_title, style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        self.order_hint = tk.StringVar()
        label(right, textvariable=self.order_hint, style="Muted.TLabel", padding=(0, 5, 0, 12)).grid(row=1, column=0, sticky="w")
        frame, self.cart = tree(right, [("name", "已点餐品", 150, "w"), ("quantity", "数量", 50, "center"),
                                       ("price", "小计 / 元", 90, "e")])
        frame.grid(row=2, column=0, sticky="nsew")
        actions = ttk.Frame(right, padding=(0, 10))
        actions.grid(row=3, column=0, sticky="ew")
        button(actions, "− 1", lambda: self.change_quantity(-1), width=4).pack(side="left")
        button(actions, "＋ 1", lambda: self.change_quantity(1), width=4).pack(side="left", padx=5)
        button(actions, "改数量", self.edit_quantity).pack(side="left")
        button(actions, "移除", self.remove_item).pack(side="right")
        total = ttk.Frame(right, padding=(0, 12, 0, 10))
        total.grid(row=4, column=0, sticky="ew")
        label(total, "餐品合计", "Muted.TLabel").pack(anchor="w")
        self.cart_total = tk.StringVar()
        label(total, textvariable=self.cart_total, style="Amount.TLabel").pack(anchor="e")
        self.checkout_button = button(right, "结算本桌 →", self.open_checkout, True)
        self.checkout_button.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        button(right, "取消本桌订单", self.cancel_order).grid(row=6, column=0, sticky="ew")

    def run_action(self, action):
        try:
            return action()
        except (ValidationError, sqlite3.Error, OSError) as error:
            logging.exception("操作失败")
            messagebox.showerror("操作未完成", str(error), parent=self)
            return None

    def report_error(self, error_type, error, traceback):
        logging.error("界面异常", exc_info=(error_type, error, traceback))
        messagebox.showerror("操作未完成", f"{error}\n\n请重试；错误详情已写入日志。", parent=self)

    def refresh(self):
        self._refresh_tables()
        self._refresh_menu()
        self._refresh_cart()
        self.products_page.refresh()
        self.history_page.refresh()
        self.tables_page.refresh()
        summary = self.store.today_summary()
        self.summary.set(f"今日已结算 {summary['count']} 单    ·    实收 ￥{money(summary['total_cents'])}")

    def _refresh_tables(self):
        tables = self.store.tables()
        if self.table_id not in {table["id"] for table in tables}:
            self.table_id = tables[0]["id"]
        for child in self.table_grid.winfo_children():
            child.destroy()
        occupied = sum(table["order_id"] is not None for table in tables)
        self.table_summary.set(f"{len(tables)} 桌  ·  用餐中 {occupied}  ·  空闲 {len(tables) - occupied}")
        for index, table in enumerate(tables):
            selected = table["id"] == self.table_id
            busy = table["order_id"] is not None
            text = f"{table['name']}\n{'用餐中' if busy else '空闲'}  ·  ￥{money(table['total_cents'])}"
            card = tk.Button(self.table_grid, text=text, relief="flat", borderwidth=0,
                             background=GREEN if selected else (PALE if busy else "white"),
                             foreground="white" if selected else INK, activebackground="#D3E5DA",
                             activeforeground=INK, font=("Microsoft YaHei UI", 10),
                             height=3, cursor="hand2", command=lambda tid=table["id"]: self.select_table(tid))
            card.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 6), pady=(0, 8))

    def _refresh_menu(self):
        products = self.store.products()
        categories = ["全部分类"] + sorted({product["category"] for product in products})
        self.category_combo.configure(values=categories)
        if self.category.get() not in categories:
            self.category.set("全部分类")
        query = self.search.get().strip().casefold()
        refill(self.menu, [(product["id"], (product["name"], product["category"], money(product["price_cents"])), ())
                           for product in products if query in product["name"].casefold()
                           and self.category.get() in ("全部分类", product["category"])])

    def _refresh_cart(self):
        self.current_order = self.store.open_order(self.table_id)
        self.cart_title.set(f"{self.table_id:02d}桌 · 当前订单")
        order = self.current_order
        self.order_hint.set(f"SM{order['id']:08d}  ·  {order['opened_at'][11:]} 开单" if order else "空闲桌号，添加餐品后自动开单")
        refill(self.cart, [(item["id"], (item["product_name"], item["quantity"],
                                        money(item["quantity"] * item["unit_cents"])), ())
                           for item in order["items"]] if order else [])
        self.cart_total.set(f"￥{money(order['total_cents'] if order else 0)}")
        self.checkout_button.configure(state="normal" if order and order["items"] else "disabled")

    def select_table(self, table_id):
        self.table_id = table_id
        self._refresh_tables()
        self._refresh_cart()

    def add_item(self):
        selection = self.menu.selection()
        if not selection:
            messagebox.showinfo("选择餐品", "请先选择要添加的餐品。", parent=self)
            return
        def action():
            self.store.add_item(self.table_id, int(selection[0]), self.add_quantity.get())
            self.add_quantity.set("1")
            self.status.set("已保存 · 本桌餐品已更新")
            self._refresh_tables()
            self._refresh_cart()
        self.run_action(action)

    def selected_item(self):
        if self.current_order and self.cart.selection():
            return next((item for item in self.current_order["items"] if str(item["id"]) == self.cart.selection()[0]), None)
        messagebox.showinfo("选择餐品", "请先在当前订单中选择一项餐品。", parent=self)
        return None

    def change_quantity(self, change):
        item = self.selected_item()
        if not item:
            return
        if item["quantity"] + change < 1:
            self.remove_item()
            return
        self._set_quantity(item, str(item["quantity"] + change))

    def _set_quantity(self, item, quantity):
        def action():
            self.store.set_quantity(self.current_order["id"], item["id"], quantity)
            self._refresh_tables()
            self._refresh_cart()
            self.status.set("已保存 · 餐品数量已更新")
        self.run_action(action)

    def edit_quantity(self):
        item = self.selected_item()
        if item:
            quantity = simpledialog.askstring("修改数量", item["product_name"] + "的数量：",
                                             initialvalue=str(item["quantity"]), parent=self)
            if quantity is not None:
                self._set_quantity(item, quantity)

    def remove_item(self):
        item = self.selected_item()
        if item and messagebox.askyesno("移除餐品", f"从本桌订单移除“{item['product_name']}”？", parent=self):
            def action():
                self.store.remove_item(self.current_order["id"], item["id"])
                self.refresh()
                self.status.set("已保存 · 餐品已移除")
            self.run_action(action)

    def cancel_order(self):
        if self.current_order and messagebox.askyesno("取消订单", "确认取消本桌全部餐品？取消记录会保留在历史订单中。", parent=self):
            def action():
                self.store.cancel_order(self.current_order["id"])
                self.refresh()
                self.status.set("已保存 · 本桌订单已取消")
            self.run_action(action)

    def open_checkout(self):
        self._refresh_cart()
        if self.current_order and self.current_order["items"]:
            CheckoutDialog(self, self.current_order)

    def enqueue_print(self, order):
        settings = self.store.settings()
        printer = settings["printer_name"]
        if not printer:
            messagebox.showinfo("未选择打印机", "结算记录已保存。请在系统设置选择打印机，再到历史订单补打。", parent=self)
            return
        if order["id"] in self.printing_ids:
            messagebox.showinfo("正在打印", "该账单正在提交打印，请稍候。", parent=self)
            return
        self.printing_ids.add(order["id"])
        self.status.set(f"SM{order['id']:08d} · 正在提交打印…")
        def worker():
            try:
                job_id = print_receipt(printer, order["receipt_text"], f"三木结算单 SM{order['id']:08d}")
                self.print_queue.put((order["id"], "", job_id))
            except Exception as error:
                logging.exception("打印失败")
                self.print_queue.put((order["id"], str(error), None))
        threading.Thread(target=worker, daemon=True, name=f"receipt-{order['id']}").start()

    def _poll_print(self):
        try:
            while True:
                order_id, error, job_id = self.print_queue.get_nowait()
                self.printing_ids.discard(order_id)
                self.run_action(lambda: self.store.record_print(order_id, error))
                if error:
                    self.status.set("打印失败 · 结算记录已保存，可在历史订单补打")
                    messagebox.showerror("打印未完成", f"结算记录已保存，无需再次结算。\n\n{error}\n\n请检查设备后在历史订单补打。", parent=self)
                else:
                    self.status.set(f"SM{order_id:08d} 已提交 Windows 打印队列（任务 {job_id}）")
                self.history_page.refresh()
        except queue.Empty:
            pass
        self.after(150, self._poll_print)

    def close_app(self):
        if self.printing_ids:
            messagebox.showinfo("打印进行中", "请等待打印任务提交完成后再退出。", parent=self)
            return
        self.store.close()
        self.destroy()


class CheckoutDialog(tk.Toplevel):
    def __init__(self, app, order):
        super().__init__(app)
        self.app, self.order = app, order
        self.title(f"{order['table_name']} · 确认结算")
        self.geometry("520x640")
        self.minsize(480, 620)
        self.configure(background=BACKGROUND)
        self.transient(app)
        self.grab_set()
        content = ttk.Frame(self, padding=28)
        content.pack(fill="both", expand=True)
        label(content, "核对本桌结算", "Heading.TLabel").pack(anchor="w")
        label(content, f"{order['table_name']}  ·  SM{order['id']:08d}", "Muted.TLabel").pack(anchor="w", pady=(6, 18))
        label(content, f"餐品合计    ￥{money(order['total_cents'])}").pack(anchor="w", pady=(0, 16))
        self.base = tk.StringVar(value=money(order["total_cents"]))
        self.discount = tk.StringVar(value="10")
        self.note = tk.StringVar()
        self.final = tk.StringVar()
        self.error = tk.StringVar()
        label(content, "结算金额（元，可修改）").pack(anchor="w")
        entry = ttk.Entry(content, textvariable=self.base)
        entry.pack(fill="x", pady=(6, 14))
        label(content, "折扣（折）").pack(anchor="w")
        ttk.Entry(content, textvariable=self.discount).pack(fill="x", pady=(6, 5))
        label(content, "10 = 不打折  ·  8.5 = 八五折  ·  0 = 免单", "Muted.TLabel").pack(anchor="w", pady=(0, 14))
        label(content, "结算备注（选填）").pack(anchor="w")
        ttk.Entry(content, textvariable=self.note).pack(fill="x", pady=(6, 12))
        label(content, "最终实收", "Muted.TLabel").pack(anchor="w")
        label(content, textvariable=self.final, style="Amount.TLabel").pack(anchor="e", pady=6)
        label(content, textvariable=self.error, style="Error.TLabel", wraplength=450).pack(anchor="w")
        settings = app.store.settings()
        self.print_after = tk.BooleanVar(value=settings["auto_print"])
        ttk.Checkbutton(content, text="结算后打印小票", variable=self.print_after).pack(anchor="w", pady=12)
        actions = ttk.Frame(content)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        button(actions, "返回核对", self.destroy).pack(side="left")
        self.confirm = button(actions, "确认收款并结算", self.submit, True)
        self.confirm.pack(side="right")
        self.base.trace_add("write", self.recalculate)
        self.discount.trace_add("write", self.recalculate)
        self.recalculate()
        entry.focus_set()
        self.bind("<Escape>", lambda event: self.destroy())

    def recalculate(self, *args):
        try:
            final = discounted_cents(to_cents(self.base.get(), "结算金额"), self.discount.get())
            self.final.set(f"￥{money(final)}")
            self.error.set("")
            self.confirm.configure(state="normal")
        except ValidationError as error:
            self.final.set("—")
            self.error.set(str(error))
            self.confirm.configure(state="disabled")

    def submit(self):
        if not messagebox.askyesno("确认已收款", f"{self.order['table_name']} 最终实收 {self.final.get()}\n\n确认已收款并完成结算？", parent=self):
            return
        self.confirm.configure(state="disabled")
        try:
            paid = self.app.store.checkout(self.order["id"], self.base.get(), self.discount.get(),
                                           self.note.get(), self.order["revision"])
        except (ValidationError, sqlite3.Error) as error:
            messagebox.showerror("结算未完成", str(error), parent=self)
            self.recalculate()
            return
        self.app.refresh()
        self.app.status.set(f"结算已保存 · SM{paid['id']:08d} · 实收 ￥{money(paid['final_cents'])}")
        print_after = self.print_after.get()
        self.destroy()
        if print_after:
            self.app.enqueue_print(paid)


class ProductsPage(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.notebook, padding=22)
        self.app = app
        self.product_id = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        label(self, "餐品与价格", "Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))
        frame, self.view = tree(self, [("name", "餐品", 200, "w"), ("category", "分类", 110, "w"),
                                      ("price", "单价 / 元", 100, "e"), ("active", "状态", 90, "center")])
        frame.grid(row=1, column=0, sticky="nsew", padx=(0, 24))
        self.view.bind("<<TreeviewSelect>>", self.select)
        form = ttk.Frame(self, width=290)
        form.grid(row=1, column=1, sticky="nsew")
        self.form_title = tk.StringVar(value="新增餐品")
        label(form, textvariable=self.form_title, style="Heading.TLabel").pack(anchor="w", pady=(0, 18))
        self.name, self.category, self.price = tk.StringVar(), tk.StringVar(value="热菜"), tk.StringVar()
        for title, variable in [("餐品名称", self.name), ("分类", self.category), ("单价（元）", self.price)]:
            label(form, title).pack(anchor="w")
            ttk.Entry(form, textvariable=variable, width=28).pack(fill="x", pady=(6, 14))
        self.active = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="上架，可在点餐页选择", variable=self.active).pack(anchor="w", pady=(0, 18))
        button(form, "保存餐品", self.save, True).pack(fill="x")
        button(form, "清空表单 / 新增", self.clear).pack(fill="x", pady=10)
        label(form, "首次启动附带 6 道示例餐品。\n请按实际菜单修改价格或下架。\n修改菜单不影响已点餐品和历史账单。",
              "Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=10)

    def refresh(self):
        refill(self.view, [(product["id"], (product["name"], product["category"], money(product["price_cents"]),
                                            "上架" if product["active"] else "下架"),
                            () if product["active"] else ("muted",)) for product in self.app.store.products(True)])

    def select(self, event=None):
        if not self.view.selection():
            return
        self.product_id = int(self.view.selection()[0])
        product = next(product for product in self.app.store.products(True) if product["id"] == self.product_id)
        self.form_title.set("编辑餐品")
        self.name.set(product["name"])
        self.category.set(product["category"])
        self.price.set(money(product["price_cents"]))
        self.active.set(bool(product["active"]))

    def clear(self):
        self.view.selection_remove(*self.view.selection())
        self.product_id = None
        self.form_title.set("新增餐品")
        self.name.set("")
        self.category.set("热菜")
        self.price.set("")
        self.active.set(True)

    def save(self):
        def action():
            product_id = self.app.store.save_product(self.name.get(), self.category.get(), self.price.get(),
                                                      self.active.get(), self.product_id)
            self.app.refresh()
            self.view.selection_set(str(product_id))
            self.app.status.set("已保存 · 餐品资料已更新")
        self.app.run_action(action)


class TablesPage(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.notebook, padding=28)
        self.app = app
        label(self, "设置桌号数量", "Heading.TLabel").pack(anchor="w")
        label(self, "桌号从 01桌 开始连续编号，最多可设置 200 桌。", "Muted.TLabel").pack(anchor="w", pady=12)
        self.count = tk.StringVar()
        row = ttk.Frame(self)
        row.pack(anchor="w", pady=20)
        ttk.Spinbox(row, from_=1, to=200, textvariable=self.count, width=10).pack(side="left", padx=(0, 18))
        button(row, "保存桌数", self.save, True).pack(side="left")
        label(self, "减少桌数会从末尾停用桌号；有未结算订单的桌号不能停用。\n历史账单会继续保留。",
              "Muted.TLabel", justify="left").pack(anchor="w", pady=12)

    def refresh(self):
        self.count.set(str(len(self.app.store.tables())))

    def save(self):
        def action():
            self.app.store.set_table_count(self.count.get())
            self.app.refresh()
            self.app.status.set("已保存 · 桌号数量已更新")
        self.app.run_action(action)


class HistoryPage(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.notebook, padding=22)
        self.app = app
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(0, 16))
        label(row, "历史订单", "Heading.TLabel").pack(side="left", padx=(0, 20))
        self.date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.filter_date = self.date.get()
        ttk.Entry(row, textvariable=self.date, width=12).pack(side="left", padx=(0, 8))
        button(row, "按日期查询", lambda: app.run_action(self.search)).pack(side="left")
        button(row, "全部记录", self.show_all).pack(side="left", padx=8)
        button(row, "查看小票 / 补打", self.preview, True).pack(side="right")
        frame, self.view = tree(self, [("number", "单号", 130, "w"), ("table", "桌号", 80, "w"),
                                      ("time", "结算 / 取消时间", 180, "w"), ("status", "状态", 90, "center"),
                                      ("subtotal", "餐品合计", 100, "e"), ("final", "实收 / 元", 110, "e"),
                                      ("print", "打印状态", 120, "center")])
        frame.pack(fill="both", expand=True)
        self.view.bind("<Double-1>", lambda event: self.preview())
        self.summary = tk.StringVar()
        label(self, textvariable=self.summary, style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(12, 0), before=frame)

    def refresh(self):
        orders = self.app.store.history(self.filter_date)
        refill(self.view, [(order["id"], (f"SM{order['id']:08d}", order["table_name"], order["closed_at"],
                                          "已结算" if order["status"] == "paid" else "已取消",
                                          money(order["subtotal_cents"]) if order["status"] == "paid" else "—",
                                          money(order["final_cents"]) if order["status"] == "paid" else "—",
                                          order["print_status"] if order["status"] == "paid" else "—"),
                            () if order["status"] == "paid" else ("muted",)) for order in orders])
        paid = [order for order in orders if order["status"] == "paid"]
        self.summary.set(f"已结算 {len(paid)} 单  ·  实收合计 ￥{money(sum(order['final_cents'] for order in paid))}  ·  已取消 {len(orders)-len(paid)} 单")

    def show_all(self):
        self.date.set("")
        self.filter_date = ""
        self.refresh()

    def search(self):
        selected_date = self.date.get().strip()
        self.app.store.history(selected_date)
        self.filter_date = selected_date
        self.refresh()

    def preview(self):
        if not self.view.selection():
            messagebox.showinfo("选择订单", "请先选择一笔历史订单。", parent=self)
            return
        order = self.app.store.order(int(self.view.selection()[0]))
        ReceiptDialog(self.app, order)


class ReceiptDialog(tk.Toplevel):
    def __init__(self, app, order):
        super().__init__(app)
        self.title(f"SM{order['id']:08d} · 订单详情")
        self.geometry("620x690")
        self.configure(background=BACKGROUND)
        self.transient(app)
        self.grab_set()
        content = ttk.Frame(self, padding=20)
        content.pack(fill="both", expand=True)
        paid = order["status"] == "paid"
        receipt = order["receipt_text"] if paid else (
            f"已取消订单 SM{order['id']:08d}\n桌号：{order['table_name']}\n取消时间：{order['closed_at']}\n\n" +
            "\n".join(f"{item['product_name']} × {item['quantity']}  ￥{money(item['unit_cents'] * item['quantity'])}" for item in order["items"]))
        view = tk.Text(content, wrap="word", font=("Microsoft YaHei UI", 11), background="white",
                       foreground=INK, borderwidth=0, padx=18, pady=18)
        view.insert("1.0", receipt)
        view.configure(state="disabled")
        scroll = ttk.Scrollbar(content, command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        row = ttk.Frame(self, padding=(20, 0, 20, 18))
        row.pack(side="bottom", fill="x", before=content)
        def export():
            path = filedialog.asksaveasfilename(parent=self, title="导出小票", defaultextension=".txt",
                                               initialfile=f"SM{order['id']:08d}.txt", filetypes=[("文本小票", "*.txt")])
            if path:
                app.run_action(lambda: Path(path).write_text(receipt, encoding="utf-8"))
        def reprint():
            if messagebox.askyesno("补打结算单", "确认打印这笔历史账单？", parent=self):
                app.enqueue_print(order)
        button(row, "导出文本", export).pack(side="left")
        if paid:
            button(row, "打印 / 补打", reprint, True).pack(side="right")
        self.bind("<Escape>", lambda event: self.destroy())


class SettingsPage(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.notebook, padding=24)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        left = ttk.Frame(self, padding=(0, 0, 36, 0))
        right = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew")
        settings = app.store.settings()
        label(left, "店铺与小票", "Heading.TLabel").pack(anchor="w", pady=(0, 18))
        self.shop = tk.StringVar(value=settings["shop_name"])
        self.footer = tk.StringVar(value=settings["receipt_footer"])
        for title, variable in [("小票店名", self.shop), ("小票页脚", self.footer)]:
            label(left, title).pack(anchor="w")
            ttk.Entry(left, textvariable=variable, width=38).pack(fill="x", pady=(6, 16))
        label(left, "Windows 已安装打印机").pack(anchor="w")
        self.printer = tk.StringVar(value=settings["printer_name"])
        self.printer_combo = ttk.Combobox(left, textvariable=self.printer, state="readonly", width=38)
        self.printer_combo.pack(fill="x", pady=(6, 10))
        button(left, "刷新打印机列表", self.load_printers).pack(anchor="w", pady=(0, 12))
        self.width = tk.StringVar(value=settings["paper_width"])
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(0, 12))
        label(row, "小票纸宽（毫米）").pack(side="left")
        ttk.Combobox(row, textvariable=self.width, values=["58", "80"], state="readonly", width=7).pack(side="left", padx=12)
        self.auto = tk.BooleanVar(value=settings["auto_print"])
        ttk.Checkbutton(left, text="结算时默认勾选打印小票", variable=self.auto).pack(anchor="w", pady=(0, 16))
        button(left, "保存设置", self.save, True).pack(fill="x")
        label(right, "打印与数据", "Heading.TLabel").pack(anchor="w", pady=(0, 18))
        label(right, "美团打印机接入说明", "Heading.TLabel").pack(anchor="w")
        label(right, "当前支持已安装 Windows 驱动的打印机。\n先安装对应型号驱动，并在 Windows 中打印测试页；\n再刷新列表、选择设备并保存设置。\n\n请在驱动中设置实际纸宽。此处纸宽控制小票换行，\n分页和切纸由设备驱动处理。\n\n只支持美团云打印的机型需要专用接口，\n确认型号前不能保证兼容。",
              "Muted.TLabel", justify="left", wraplength=450).pack(anchor="w", pady=(12, 22))
        label(right, "数据位置").pack(anchor="w")
        path = ttk.Entry(right, width=48)
        path.insert(0, str(app.store.path))
        path.configure(state="readonly")
        path.pack(fill="x", pady=(6, 12))
        button(right, "备份数据库…", self.backup).pack(anchor="w")
        label(right, "餐品、桌号、未结算订单和历史账单会自动保存。\n建议定期将备份文件复制到另一块磁盘。", "Muted.TLabel",
              justify="left", wraplength=450).pack(anchor="w", pady=12)

    def load_printers(self):
        def action():
            printers = available_printers()
            self.printer_combo.configure(values=[""] + printers)
            self.app.status.set(f"检测到 {len(printers)} 台 Windows 打印机")
            if not printers:
                messagebox.showinfo("未发现打印机", "请先在 Windows 中安装打印机及对应驱动。", parent=self)
        self.app.run_action(action)

    def save(self):
        def action():
            self.app.store.save_settings(dict(shop_name=self.shop.get(), receipt_footer=self.footer.get(),
                                              printer_name=self.printer.get(), paper_width=self.width.get(),
                                              auto_print=self.auto.get()))
            self.app.status.set("已保存 · 店铺与打印设置已更新")
        self.app.run_action(action)

    def backup(self):
        filename = filedialog.asksaveasfilename(parent=self, title="备份数据库", defaultextension=".sqlite3",
                                               initialfile=f"sanmu-backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3",
                                               filetypes=[("SQLite 数据库", "*.sqlite3")])
        if filename:
            def action():
                self.app.store.backup(filename)
                self.app.status.set("数据库备份已完成")
                messagebox.showinfo("备份完成", f"已备份到：\n{filename}", parent=self)
            self.app.run_action(action)
