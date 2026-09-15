"""收入统计页：选择自然日 / 月 / 年或日期范围，查看已结算实收。"""

from calendar import monthrange
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QWidget

from .money import money
from .reports import report_period
from .widgets import ComboBox, DateEdit, action, data_table, fill_table, hbox, panel, selected_id, text, vbox


class RevenuePage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.report = None
        self.setObjectName("Page")
        outer = vbox(self, 22, 16)
        filters = panel()
        layout = vbox(filters, 20, 14)
        heading = hbox()
        heading.addWidget(text("收入统计", "heading"))
        heading.addStretch()
        heading.addWidget(text("按结算时间统计最终实收", "muted"))
        layout.addLayout(heading)
        row = hbox(spacing=10)
        self.mode = ComboBox()
        for label, key in (("今日", "today"), ("按日", "day"), ("按月", "month"),
                           ("按年", "year"), ("日期范围", "range")):
            self.mode.addItem(label, key)
        self.mode.setFixedWidth(122)
        self.mode.setAccessibleName("收入统计方式")
        row.addWidget(self.mode)
        self.date = DateEdit()
        self.date.setAccessibleName("统计日期 / 开始日期")
        row.addWidget(self.date)
        self.year = ComboBox()
        today = date.today()
        self.year.addItems([f"{year} 年" for year in range(today.year + 1, 1899, -1)])
        self.year.setCurrentText(f"{today.year} 年")
        self.year.setFixedWidth(122)
        self.year.setAccessibleName("统计年份")
        row.addWidget(self.year)
        self.month = ComboBox()
        self.month.addItems([f"{month:02d} 月" for month in range(1, 13)])
        self.month.setCurrentIndex(today.month - 1)
        self.month.setFixedWidth(100)
        self.month.setAccessibleName("统计月份")
        row.addWidget(self.month)
        self.to_label = text("至", "muted")
        row.addWidget(self.to_label)
        self.end_date = DateEdit()
        self.end_date.setAccessibleName("统计结束日期")
        row.addWidget(self.end_date)
        row.addStretch()
        self.query_button = action("查询收入", self.search, "primary")
        row.addWidget(self.query_button)
        layout.addLayout(row)
        outer.addWidget(filters)
        cards = hbox(spacing=14)
        self.metrics = {}
        for key, title, hint in (("total_cents", "实收收入", "已确认收款的最终金额"),
                                 ("count", "结算单数", "包含免单的已结算订单"),
                                 ("average_cents", "平均每单", "实收收入 ÷ 结算单数"),
                                 ("discount_cents", "折扣优惠", "结算金额与实收的差额")):
            card = panel("RevenuePrimary" if key == "total_cents" else "Panel")
            card_layout = vbox(card, 18, 8)
            card_layout.addWidget(text(title, "muted"))
            value = text("—", "metric")
            value.setAccessibleName(title)
            card_layout.addWidget(value)
            card_layout.addWidget(text(hint, "small", wrap=True))
            self.metrics[key] = value
            cards.addWidget(card, 1)
        outer.addLayout(cards)
        content = panel()
        layout = vbox(content, 20, 14)
        top = hbox()
        top.addWidget(text("收入明细", "heading"))
        self.period_label = text("", "muted")
        top.addWidget(self.period_label)
        top.addStretch()
        self.details_button = action("查看所选账单", self.show_orders)
        top.addWidget(self.details_button)
        layout.addLayout(top)
        self.view = data_table(["日期", "结算单数", "餐品合计 / 元", "结算金额 / 元", "折扣优惠 / 元", "实收收入 / 元"])
        self.view.itemDoubleClicked.connect(lambda *args: self.show_orders())
        self.view.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.view, 1)
        self.empty = text("所选时间暂无已结算订单", "muted")
        layout.addWidget(self.empty)
        layout.addWidget(text("仅列出有结算的日期；未结算和已取消订单不计入收入。双击明细可查看对应账单。", "small", wrap=True))
        outer.addWidget(content, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.date.dateChanged.connect(lambda value: self._date_changed(True))
        self.end_date.dateChanged.connect(lambda value: self._date_changed(False))
        self.year.currentIndexChanged.connect(lambda value: self.search())
        self.month.currentIndexChanged.connect(lambda value: self.search())
        self._update_fields()

    def _selection_changed(self):
        self.details_button.setEnabled(selected_id(self.view) is not None)

    def _update_fields(self):
        mode = self.mode.currentData()
        self.date.setVisible(mode in ("today", "day", "range"))
        self.date.setEnabled(mode != "today")
        self.year.setVisible(mode in ("month", "year"))
        self.month.setVisible(mode == "month")
        self.to_label.setVisible(mode == "range")
        self.end_date.setVisible(mode == "range")
        if mode == "today":
            self.date.blockSignals(True)
            self.date.setDate(QDate.currentDate())
            self.date.blockSignals(False)

    def _mode_changed(self, *args):
        self._update_fields()
        self._date_changed(True)

    def _date_changed(self, start_changed):
        if self.mode.currentData() == "range" and self.date.date() > self.end_date.date():
            other, value = (self.end_date, self.date.date()) if start_changed else (self.date, self.end_date.date())
            other.blockSignals(True)
            other.setDate(value)
            other.blockSignals(False)
        self.search()

    def refresh(self):
        self._update_fields()
        start, end, grouping = report_period(self.mode.currentData(), self.date.date().toPython(),
            year=int(self.year.currentText().split()[0]), month=self.month.currentIndex() + 1,
            end=self.end_date.date().toPython())
        report = self.app.store.revenue_report(start, end, grouping)
        self.report = report
        for key, widget in self.metrics.items():
            widget.setText(f"{report[key]} 单" if key == "count" else f"￥{money(report[key])}")
            widget.setToolTip(widget.text())
        self.period_label.setText(start if start == end else f"{start} 至 {end}")
        self.view.horizontalHeaderItem(0).setText("月份" if grouping == "month" else "日期")
        fill_table(self.view, [(row["period"], (row["period"], f"{row['count']} 单", money(row["subtotal_cents"]),
                    money(row["base_cents"]), money(row["discount_cents"]), money(row["total_cents"]))) for row in report["rows"]])
        self.empty.setVisible(not report["rows"])
        self._selection_changed()

    def search(self):
        self.app.run_action(self.refresh)

    def show_orders(self):
        period = selected_id(self.view)
        if not period or not self.report:
            return
        if self.report["group_by"] == "month":
            year, month = map(int, period.split("-"))
            start, end = f"{period}-01", f"{period}-{monthrange(year, month)[1]}"
        else:
            start = end = period
        self.app.history_page.set_filters(start, end, "paid")
        self.app.navigate(self.app.stack.indexOf(self.app.history_page))
